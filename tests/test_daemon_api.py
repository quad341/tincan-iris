"""Tests for iris.daemon.api and iris.daemon.proxy (ti-gxpt.4).

Covers:
  - Command/ack round-trip: choose, dnd (on/off/until), status
  - Event broadcast to N concurrent clients
  - Stale call_id rejection in choose
  - DaemonNotRunning when socket is absent
  - Ack arrives before posture broadcast on same connection
"""
from __future__ import annotations

import queue
import socket
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from iris.daemon.api import DaemonAPI
from iris.daemon.posture import PostureManager
from iris.daemon.proxy import DaemonNotRunning, DaemonProxy


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_db(tmp_path):
    return tmp_path / "test.db"


@pytest.fixture
def tmp_sock(tmp_path):
    return tmp_path / "daemon.sock"


@pytest.fixture
def posture(tmp_db):
    return PostureManager(path=tmp_db)


@pytest.fixture
def engine():
    """Minimal HandlingEngine stand-in."""
    mock = MagicMock()
    mock._attention.active_call_id = None
    return mock


@pytest.fixture
def api(posture, engine, tmp_sock):
    a = DaemonAPI(posture=posture, engine=engine, socket_path=tmp_sock)
    a.start()
    yield a
    a.stop()


def _connect(sock_path: Path):
    """Open a raw socket to the daemon; return (rfile, wfile, sock)."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(str(sock_path))
    return sock.makefile("rb"), sock.makefile("wb"), sock


def _send_recv(rfile, wfile, cmd: dict) -> dict:
    """Send a command dict and read back the next line."""
    import json
    line = __import__("json").dumps(cmd, separators=(",", ":")) + "\n"
    wfile.write(line.encode())
    wfile.flush()
    raw = rfile.readline()
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Command / ack round-trips
# ---------------------------------------------------------------------------


def test_status_ack(api, tmp_sock):
    rfile, wfile, sock = _connect(tmp_sock)
    try:
        ack = _send_recv(rfile, wfile, {"cmd": "status"})
        assert ack["ack"] == "status"
        assert ack["ok"] is True
        assert "state" in ack
        assert "posture" in ack["state"]
        assert "call" in ack["state"]
    finally:
        sock.close()


def test_dnd_on_ack(api, tmp_sock, posture):
    rfile, wfile, sock = _connect(tmp_sock)
    try:
        ack = _send_recv(rfile, wfile, {"cmd": "dnd", "action": "on"})
        assert ack["ack"] == "dnd"
        assert ack["ok"] is True
        assert ack["posture"]["dnd"] is True
        # PostureManager should reflect DND on
        assert posture.effective()["dnd"] is True
    finally:
        sock.close()


def test_dnd_off_ack(api, tmp_sock, posture):
    posture.set_dnd("manual")
    rfile, wfile, sock = _connect(tmp_sock)
    try:
        ack = _send_recv(rfile, wfile, {"cmd": "dnd", "action": "off"})
        assert ack["ack"] == "dnd"
        assert ack["ok"] is True
        assert ack["posture"]["dnd"] is False
        assert posture.effective()["dnd"] is False
    finally:
        sock.close()


def test_dnd_until_ack(api, tmp_sock, posture):
    future = time.time() + 3600
    rfile, wfile, sock = _connect(tmp_sock)
    try:
        ack = _send_recv(rfile, wfile, {"cmd": "dnd", "action": "until", "until": future})
        assert ack["ack"] == "dnd"
        assert ack["ok"] is True
        assert ack["posture"]["dnd"] is True
        assert ack["posture"]["expires_in_s"] > 3590
    finally:
        sock.close()


def test_dnd_until_non_number_rejected(api, tmp_sock):
    rfile, wfile, sock = _connect(tmp_sock)
    try:
        ack = _send_recv(rfile, wfile, {"cmd": "dnd", "action": "until", "until": "tomorrow"})
        assert ack["ack"] == "dnd"
        assert ack["ok"] is False
        assert "until" in ack["error"].lower()
    finally:
        sock.close()


def test_unknown_command_rejected(api, tmp_sock):
    rfile, wfile, sock = _connect(tmp_sock)
    try:
        ack = _send_recv(rfile, wfile, {"cmd": "frobnicate"})
        assert ack["ack"] == "frobnicate"
        assert ack["ok"] is False
    finally:
        sock.close()


def test_invalid_json_rejected(api, tmp_sock):
    import json
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(str(tmp_sock))
    rfile = sock.makefile("rb")
    wfile = sock.makefile("wb")
    try:
        wfile.write(b"{not-valid-json}\n")
        wfile.flush()
        raw = rfile.readline()
        ack = json.loads(raw)
        assert ack["ack"] == "error"
        assert ack["ok"] is False
    finally:
        sock.close()


# ---------------------------------------------------------------------------
# Choose: stale call_id rejection
# ---------------------------------------------------------------------------


def test_choose_stale_call_id(api, tmp_sock, engine):
    """choose with no active call logs but returns ok=True (drop silently)."""
    engine._attention.active_call_id = None  # no active call
    rfile, wfile, sock = _connect(tmp_sock)
    try:
        ack = _send_recv(rfile, wfile, {"cmd": "choose", "call_id": "stale-id", "action_id": "put_through"})
        assert ack["ack"] == "choose"
        # engine.on_choose should have been called — the API delegates validation to engine
        engine.on_choose.assert_called_once_with("stale-id", "put_through")
    finally:
        sock.close()


def test_choose_missing_fields(api, tmp_sock):
    rfile, wfile, sock = _connect(tmp_sock)
    try:
        ack = _send_recv(rfile, wfile, {"cmd": "choose", "call_id": ""})
        assert ack["ack"] == "choose"
        assert ack["ok"] is False
        assert "call_id" in ack["error"] or "action_id" in ack["error"]
    finally:
        sock.close()


# ---------------------------------------------------------------------------
# Broadcast: N clients receive posture event
# ---------------------------------------------------------------------------


def test_broadcast_reaches_n_clients(api, tmp_sock, posture):
    """All connected clients receive the posture event broadcast."""
    N = 3
    received: list[list[dict]] = [[] for _ in range(N)]
    ready_events = [threading.Event() for _ in range(N)]
    done_events = [threading.Event() for _ in range(N)]

    def reader(i):
        import json
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(str(tmp_sock))
        rfile = sock.makefile("rb")
        wfile = sock.makefile("wb")
        ready_events[i].set()
        # Read one line (the posture broadcast)
        raw = rfile.readline()
        if raw.strip():
            received[i].append(json.loads(raw))
        done_events[i].set()
        sock.close()

    threads = [threading.Thread(target=reader, args=(i,), daemon=True) for i in range(N)]
    for t in threads:
        t.start()

    # Wait for all clients to connect
    for ev in ready_events:
        assert ev.wait(timeout=2.0), "Client did not connect in time"

    # Small pause to ensure all clients are reading
    time.sleep(0.05)

    # Trigger posture event
    api.broadcast({"event": "posture", "dnd": True, "busy": False})

    for ev in done_events:
        assert ev.wait(timeout=2.0), "Client did not receive broadcast in time"

    for i in range(N):
        assert len(received[i]) == 1, f"Client {i} got {len(received[i])} messages"
        assert received[i][0]["event"] == "posture"
        assert received[i][0]["dnd"] is True


# ---------------------------------------------------------------------------
# Ack-before-broadcast ordering
# ---------------------------------------------------------------------------


def test_dnd_ack_arrives_before_posture_event(api, tmp_sock):
    """The ack for 'dnd on' must arrive before the posture broadcast event."""
    import json

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(str(tmp_sock))
    rfile = sock.makefile("rb")
    wfile = sock.makefile("wb")
    try:
        line = json.dumps({"cmd": "dnd", "action": "on"}, separators=(",", ":")) + "\n"
        wfile.write(line.encode())
        wfile.flush()

        first_line = rfile.readline()
        first = json.loads(first_line)
        # The first message must be the ack, not the posture event
        assert "ack" in first, f"Expected ack first but got: {first}"
        assert first["ack"] == "dnd"
    finally:
        sock.close()


# ---------------------------------------------------------------------------
# DaemonProxy: DaemonNotRunning fallback
# ---------------------------------------------------------------------------


def test_proxy_raises_when_socket_absent(tmp_path):
    absent = tmp_path / "no-such.sock"
    proxy = DaemonProxy(socket_path=absent)
    with pytest.raises(DaemonNotRunning):
        proxy.connect()


def test_proxy_raises_when_connection_refused(tmp_path):
    """Socket file exists but nothing listens on it."""
    dead_sock = tmp_path / "dead.sock"
    # Create a socket file that nobody listens on
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(dead_sock))
    srv.close()

    proxy = DaemonProxy(socket_path=dead_sock)
    with pytest.raises(DaemonNotRunning):
        proxy.connect()


def test_proxy_send_recv(api, tmp_sock):
    """DaemonProxy.send() returns the ack dict."""
    proxy = DaemonProxy(socket_path=tmp_sock)
    proxy.connect()
    try:
        ack = proxy.send({"cmd": "status"})
        assert ack["ack"] == "status"
        assert ack["ok"] is True
    finally:
        proxy.close()


def test_proxy_event_reader_receives_broadcasts(api, tmp_sock):
    """DaemonProxy.start_event_reader() delivers broadcast events.

    Pattern: send a command first (proves connection + consumes ack), then
    start the event reader.  Subsequent broadcasts arrive on the reader thread
    with no concurrent rfile access from send().
    """
    events = []
    ev = threading.Event()

    def on_event(obj):
        events.append(obj)
        ev.set()

    proxy = DaemonProxy(socket_path=tmp_sock)
    proxy.connect()
    try:
        # Flush any pending data and confirm connection before starting reader
        ack = proxy.send({"cmd": "status"})
        assert ack["ok"] is True

        # Now start the reader — no concurrent send() will race with it
        proxy.start_event_reader(on_event)
        time.sleep(0.02)  # allow reader thread to reach rfile.readline()

        api.broadcast({"event": "posture", "dnd": False, "busy": False})
        assert ev.wait(timeout=2.0), "Proxy did not receive broadcast"
        assert events[0]["event"] == "posture"
    finally:
        proxy.close()


# ---------------------------------------------------------------------------
# Client count
# ---------------------------------------------------------------------------


def test_client_count(api, tmp_sock):
    assert api.client_count() == 0

    sock1 = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock1.connect(str(tmp_sock))
    time.sleep(0.05)
    assert api.client_count() == 1

    sock2 = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock2.connect(str(tmp_sock))
    time.sleep(0.05)
    assert api.client_count() == 2

    sock1.close()
    sock2.close()
    # Give server time to detect disconnect
    time.sleep(0.1)
