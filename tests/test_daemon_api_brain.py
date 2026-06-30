"""Tests for DaemonAPI brain command handlers (ti-s9mm.2.2).

Written BEFORE the builder implements ti-s9mm.2.1.  All tests that construct
DaemonAPI with brain_host= WILL FAIL until DaemonAPI accepts that parameter
and dispatches turn/stream_turn/call_context commands.

Covers:
  1. turn — {ack:turn, ok:True} proxied from BrainHost.async_turn
  2. stream_turn — {ack:stream_turn, ok:True} + brain_chunk x N + brain_reply
  3. call_context — {ack:call_context, contact_id, contact_name, in_call:True}
  4. busy rejection — {ack:turn, ok:False, error:busy}
  5. no-brain fallback — turn/call_context with brain_host=None return ok=False
  6. unknown command regression — still rejected when brain_host is present
"""
from __future__ import annotations

import json
import socket
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from iris.daemon.api import DaemonAPI
from iris.daemon.brain_host import BrainHost
from iris.daemon.posture import PostureManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _BroadcastRef:
    """Mutable callable so BrainHost's broadcast can be wired to api.broadcast
    after both objects are constructed (breaks the circular dependency)."""

    def __init__(self):
        self._target = None

    def set(self, fn):
        self._target = fn

    def __call__(self, ev: dict) -> None:
        if self._target is not None:
            self._target(ev)


def _make_chunk(text, *, lane="tier0", skill=None, final=False):
    return SimpleNamespace(text=text, lane=lane, skill=skill, final=final, denied=False)


def _connect(sock_path: Path):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(str(sock_path))
    return s.makefile("rb"), s.makefile("wb"), s


def _send(wfile, cmd: dict) -> None:
    wfile.write((json.dumps(cmd, separators=(",", ":")) + "\n").encode())
    wfile.flush()


def _recv(rfile) -> dict:
    return json.loads(rfile.readline())


def _send_recv(rfile, wfile, cmd: dict) -> dict:
    _send(wfile, cmd)
    return _recv(rfile)


def _collect_lines(rfile, *, expected: int, timeout: float = 2.0) -> list[dict]:
    """Read up to `expected` JSON lines in a background thread; return
    whatever arrived within `timeout` seconds.  The background thread is a
    daemon so it never prevents test exit."""
    results: list[dict] = []

    def _reader():
        try:
            for _ in range(expected):
                raw = rfile.readline()
                if not raw:
                    break
                results.append(json.loads(raw))
        except Exception:
            pass

    t = threading.Thread(target=_reader, daemon=True)
    t.start()
    t.join(timeout=timeout)
    return results


# ---------------------------------------------------------------------------
# Fixtures — shared
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
    m = MagicMock()
    m._attention.active_call_id = None
    return m


@pytest.fixture
def mock_brain_host():
    """Minimal MagicMock stand-in for BrainHost (turn/busy tests)."""
    bh = MagicMock()
    bh.async_turn.return_value = {"ack": "turn", "ok": True}
    return bh


@pytest.fixture
def api_with_brain(posture, engine, tmp_sock, mock_brain_host):
    a = DaemonAPI(
        posture=posture, engine=engine, socket_path=tmp_sock,
        brain_host=mock_brain_host,
    )
    a.start()
    yield a, mock_brain_host
    a.stop()


@pytest.fixture
def api_no_brain(posture, engine, tmp_sock):
    a = DaemonAPI(posture=posture, engine=engine, socket_path=tmp_sock)
    a.start()
    yield a
    a.stop()


# ---------------------------------------------------------------------------
# Fixture — streaming_api: real BrainHost wired to api.broadcast
# ---------------------------------------------------------------------------


@pytest.fixture
def streaming_api(posture, engine, tmp_sock, tmp_db):
    """DaemonAPI wired to a real BrainHost backed by a mock Brain.

    respond_stream yields two chunks so every stream_turn test gets:
      brain_turn_started  (broadcast from async_turn before lock)
      ack                 (writer.write after async_turn returns)
      brain_chunk x 2    (thread broadcasts)
      brain_reply        (thread broadcast)
    — five lines total.
    """
    bcast = _BroadcastRef()

    mock_brain = MagicMock()
    mock_brain.call_context = ""
    mock_brain.respond_stream.side_effect = lambda text, **kw: iter([
        _make_chunk("Hello ", lane="tier0", final=False),
        _make_chunk("world.", lane="tier0", final=True),
    ])

    host = BrainHost(brain=mock_brain, db_path=tmp_db, broadcast=bcast)
    a = DaemonAPI(
        posture=posture, engine=engine, socket_path=tmp_sock,
        brain_host=host,
    )
    a.start()
    bcast.set(a.broadcast)  # wire BrainHost events → all connected clients

    yield a, host
    a.stop()


# ---------------------------------------------------------------------------
# Fixture — context_api: BrainHost with call context pre-set
# ---------------------------------------------------------------------------


@pytest.fixture
def context_api(posture, engine, tmp_sock, tmp_db):
    bcast = _BroadcastRef()

    mock_brain = MagicMock()
    mock_brain.call_context = ""

    host = BrainHost(brain=mock_brain, db_path=tmp_db, broadcast=bcast)
    host.set_call_context("cid-999", "Jane Doe", "+15551234567")

    a = DaemonAPI(
        posture=posture, engine=engine, socket_path=tmp_sock,
        brain_host=host,
    )
    a.start()
    bcast.set(a.broadcast)

    yield a, host
    a.stop()


# ---------------------------------------------------------------------------
# 1. turn command
# ---------------------------------------------------------------------------


def test_turn_ack(api_with_brain, tmp_sock):
    """turn returns {ack:turn, ok:True} proxied from BrainHost.async_turn."""
    _, bh = api_with_brain
    rfile, wfile, sock = _connect(tmp_sock)
    try:
        ack = _send_recv(rfile, wfile, {"cmd": "turn", "text": "hello iris", "speaker": "operator"})
        assert ack["ack"] == "turn"
        assert ack["ok"] is True
        bh.async_turn.assert_called_once_with("hello iris", "operator")
    finally:
        sock.close()


# ---------------------------------------------------------------------------
# 2. stream_turn command
# ---------------------------------------------------------------------------


def test_stream_turn_ack(streaming_api, tmp_sock):
    """{ack:stream_turn, ok:True} must arrive (ack key differs from 'turn')."""
    api, _ = streaming_api
    rfile, wfile, sock = _connect(tmp_sock)
    try:
        _send(wfile, {"cmd": "stream_turn", "text": "hi", "speaker": "operator"})
        # 5 lines: brain_turn_started + ack + chunk1 + chunk2 + brain_reply
        lines = _collect_lines(rfile, expected=5)
        ack_lines = [l for l in lines if l.get("ack") == "stream_turn"]
        assert ack_lines, f"No stream_turn ack found; got: {lines}"
        assert ack_lines[0]["ok"] is True
    finally:
        sock.close()


def test_stream_turn_chunks_then_reply(streaming_api, tmp_sock):
    """brain_chunk events arrive before brain_reply; reply accumulates text."""
    api, _ = streaming_api
    rfile, wfile, sock = _connect(tmp_sock)
    try:
        _send(wfile, {"cmd": "stream_turn", "text": "hi", "speaker": "operator"})
        lines = _collect_lines(rfile, expected=5)

        event_types = [l.get("event") for l in lines if "event" in l]
        assert "brain_chunk" in event_types, f"Missing brain_chunk; lines={lines}"
        assert "brain_reply" in event_types, f"Missing brain_reply; lines={lines}"

        chunk_idxs = [i for i, l in enumerate(lines) if l.get("event") == "brain_chunk"]
        reply_idxs = [i for i, l in enumerate(lines) if l.get("event") == "brain_reply"]
        assert chunk_idxs, "No brain_chunk events found"
        assert reply_idxs, "No brain_reply event found"
        assert max(chunk_idxs) < reply_idxs[0], (
            "brain_reply must arrive after all brain_chunk events"
        )

        reply = next(l for l in lines if l.get("event") == "brain_reply")
        assert reply["text"] == "Hello world."
        assert reply["lane"] == "tier0"
    finally:
        sock.close()


# ---------------------------------------------------------------------------
# 3. call_context command
# ---------------------------------------------------------------------------


def test_call_context_response(context_api, tmp_sock):
    """call_context returns contact_id, contact_name, in_call=True after set_call_context."""
    _, _ = context_api
    rfile, wfile, sock = _connect(tmp_sock)
    try:
        ack = _send_recv(rfile, wfile, {"cmd": "call_context"})
        assert ack["ack"] == "call_context"
        assert ack["ok"] is True
        assert ack["contact_id"] == "cid-999"
        assert ack["contact_name"] == "Jane Doe"
        assert ack["in_call"] is True
    finally:
        sock.close()


# ---------------------------------------------------------------------------
# 4. busy rejection
# ---------------------------------------------------------------------------


def test_turn_busy_rejection(api_with_brain, tmp_sock):
    """BrainHost returning busy ack propagates {ack:turn, ok:False, error:busy}."""
    _, bh = api_with_brain
    bh.async_turn.return_value = {"ack": "turn", "ok": False, "error": "busy"}
    rfile, wfile, sock = _connect(tmp_sock)
    try:
        ack = _send_recv(rfile, wfile, {"cmd": "turn", "text": "hi", "speaker": "operator"})
        assert ack["ack"] == "turn"
        assert ack["ok"] is False
        assert ack.get("error") == "busy"
    finally:
        sock.close()


# ---------------------------------------------------------------------------
# 5. no-brain fallback (brain_host=None)
# ---------------------------------------------------------------------------


def test_turn_without_brain_host(api_no_brain, tmp_sock):
    """turn with no brain_host returns ok=False with a brain-specific error."""
    rfile, wfile, sock = _connect(tmp_sock)
    try:
        ack = _send_recv(rfile, wfile, {"cmd": "turn", "text": "hello", "speaker": "operator"})
        assert ack["ack"] == "turn"
        assert ack["ok"] is False
        # Must be a deliberate no-brain rejection, not "unknown command"
        assert "brain" in ack.get("error", "").lower(), (
            f"Expected brain-specific error; got: {ack}"
        )
    finally:
        sock.close()


def test_call_context_without_brain_host(api_no_brain, tmp_sock):
    """call_context with no brain_host returns ok=False with a brain-specific error."""
    rfile, wfile, sock = _connect(tmp_sock)
    try:
        ack = _send_recv(rfile, wfile, {"cmd": "call_context"})
        assert ack["ack"] == "call_context"
        assert ack["ok"] is False
        assert "brain" in ack.get("error", "").lower(), (
            f"Expected brain-specific error; got: {ack}"
        )
    finally:
        sock.close()


# ---------------------------------------------------------------------------
# 6. unknown command regression
# ---------------------------------------------------------------------------


def test_unknown_command_still_rejected_with_brain(api_with_brain, tmp_sock):
    """Unknown commands return ok=False even when brain_host is present."""
    _, _ = api_with_brain
    rfile, wfile, sock = _connect(tmp_sock)
    try:
        ack = _send_recv(rfile, wfile, {"cmd": "frobnicate"})
        assert ack["ack"] == "frobnicate"
        assert ack["ok"] is False
    finally:
        sock.close()
