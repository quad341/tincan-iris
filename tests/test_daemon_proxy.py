"""Tests: DaemonProxy single-reader ack routing (console-freeze fix, 2026-07-05).

The old design had send() and the event reader both reading one buffered
socket stream; whoever lost the race swallowed the other's line, freezing the
console UI thread inside send() forever. These tests drive a real Unix-socket
fake daemon to prove acks route to senders (FIFO) while events flow to the
callback, with timeouts instead of hangs on every failure path.
"""
from __future__ import annotations

import json
import queue
import socket
import threading
import time
from pathlib import Path

import pytest

from iris.daemon.proxy import DaemonNotRunning, DaemonProxy


class _FakeDaemon:
    """Accepts one client; test scripts responses via send_line()."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._listener.bind(str(path))
        self._listener.listen(1)
        self.conn: socket.socket | None = None
        self.received: queue.Queue = queue.Queue()
        self._accepted = threading.Event()
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        conn, _ = self._listener.accept()
        self.conn = conn
        self._accepted.set()
        f = conn.makefile("rb")
        for raw in f:
            if raw.strip():
                self.received.put(json.loads(raw))

    def wait_client(self, timeout: float = 5.0) -> None:
        assert self._accepted.wait(timeout), "client never connected"

    def send_line(self, obj: dict) -> None:
        self.conn.sendall((json.dumps(obj) + "\n").encode())

    def close(self) -> None:
        if self.conn is not None:
            try:
                self.conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.conn.close()
        self._listener.close()


@pytest.fixture
def daemon_pair(tmp_path):
    path = tmp_path / "daemon.sock"
    fake = _FakeDaemon(path)
    proxy = DaemonProxy(socket_path=path)
    proxy.connect()
    fake.wait_client()
    yield fake, proxy
    proxy.close()
    fake.close()


def _wait_for(pred, timeout=3.0):
    deadline = time.monotonic() + timeout
    while not pred() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert pred(), "condition not met in time"


def test_send_gets_ack_while_events_interleave(daemon_pair):
    """The console-freeze scenario: events on the wire must not eat the ack."""
    fake, proxy = daemon_pair
    events: list = []
    proxy.start_event_reader(on_event=events.append)

    fake.send_line({"event": "posture", "dnd": False})
    result_box: list = []
    t = threading.Thread(target=lambda: result_box.append(proxy.send({"cmd": "dnd"})))
    t.start()
    _wait_for(lambda: not fake.received.empty())
    fake.send_line({"event": "call_card_started", "session_id": "x"})
    fake.send_line({"ack": "dnd", "ok": True})
    fake.send_line({"event": "call_ended"})
    t.join(timeout=3)
    assert not t.is_alive(), "send() hung — ack was swallowed"
    assert result_box == [{"ack": "dnd", "ok": True}]
    _wait_for(lambda: len(events) == 3)
    assert [e.get("event") for e in events] == ["posture", "call_card_started", "call_ended"]


def test_acks_route_fifo_to_sequential_senders(daemon_pair):
    fake, proxy = daemon_pair
    results: dict = {}

    def sender(name):
        results[name] = proxy.send({"cmd": name})

    t1 = threading.Thread(target=sender, args=("first",))
    t1.start()
    _wait_for(lambda: fake.received.qsize() >= 1)
    t2 = threading.Thread(target=sender, args=("second",))
    t2.start()
    _wait_for(lambda: fake.received.qsize() >= 2)
    fake.send_line({"ack": "first", "ok": True})
    fake.send_line({"ack": "second", "ok": True})
    t1.join(timeout=3)
    t2.join(timeout=3)
    assert results["first"]["ack"] == "first"
    assert results["second"]["ack"] == "second"


def test_event_before_callback_registered_is_dropped_quietly(daemon_pair):
    fake, proxy = daemon_pair
    fake.send_line({"event": "early_bird"})
    time.sleep(0.2)  # reader must consume it without crashing
    fake.send_line({"ack": "status", "ok": True})
    t = threading.Thread(target=lambda: proxy.send({"cmd": "status"}))
    # ordering: ack already on the wire before send — FIFO slot still catches it?
    # No: ack-with-no-pending is logged and dropped; this send needs its own ack.
    t.start()
    _wait_for(lambda: not fake.received.empty())
    fake.send_line({"ack": "status", "ok": True})
    t.join(timeout=3)
    assert not t.is_alive()


def test_send_times_out_instead_of_hanging(daemon_pair, monkeypatch):
    fake, proxy = daemon_pair
    monkeypatch.setattr(DaemonProxy, "ACK_TIMEOUT_S", 0.3)
    t0 = time.monotonic()
    with pytest.raises(DaemonNotRunning, match="did not ack"):
        proxy.send({"cmd": "dnd"})
    assert time.monotonic() - t0 < 3.0


def test_daemon_close_wakes_pending_send(daemon_pair):
    fake, proxy = daemon_pair
    errs: list = []

    def sender():
        try:
            proxy.send({"cmd": "dnd"})
        except DaemonNotRunning as e:
            errs.append(str(e))

    t = threading.Thread(target=sender)
    t.start()
    _wait_for(lambda: not fake.received.empty())
    fake.close()  # daemon dies mid-command
    t.join(timeout=3)
    assert not t.is_alive(), "send() hung after daemon death"
    assert errs, "send() should raise DaemonNotRunning"


def test_deliberate_close_does_not_fire_on_disconnect(daemon_pair):
    fake, proxy = daemon_pair
    disconnects: list = []
    proxy.start_event_reader(on_event=lambda e: None,
                             on_disconnect=lambda: disconnects.append(1))
    proxy.close()
    time.sleep(0.2)
    assert disconnects == []


def test_daemon_death_fires_on_disconnect(daemon_pair):
    fake, proxy = daemon_pair
    disconnects: list = []
    proxy.start_event_reader(on_event=lambda e: None,
                             on_disconnect=lambda: disconnects.append(1))
    fake.close()
    _wait_for(lambda: disconnects == [1])
