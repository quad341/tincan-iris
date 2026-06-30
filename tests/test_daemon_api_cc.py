"""Tests for DaemonAPI call-card command handlers (ti-rnlqo.4.1).

Covers all 4 new CC commands via the socket round-trip pattern from test_daemon_api.py:
  confirm_fact, confirm_action_item, disclosure_ack, get_call_card

Two paths per command:
  (a) call_card_host=None  → {ok: False, error: 'call_card not configured'}
  (b) call_card_host=mock  → delegates to host, returns {ok: True}

Missing-field rejection paths also tested for commands that require session_id.
"""
from __future__ import annotations

import json
import socket
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from iris.daemon.api import DaemonAPI
from iris.daemon.posture import PostureManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_db(tmp_path):
    return tmp_path / "test.db"


@pytest.fixture
def tmp_sock(tmp_path):
    return tmp_path / "daemon_cc.sock"


@pytest.fixture
def posture(tmp_db):
    return PostureManager(path=tmp_db)


@pytest.fixture
def engine():
    mock = MagicMock()
    mock._attention.active_call_id = None
    return mock


@pytest.fixture
def api_no_cc(posture, engine, tmp_sock):
    """DaemonAPI with no call_card_host."""
    a = DaemonAPI(posture=posture, engine=engine, socket_path=tmp_sock)
    a.start()
    yield a
    a.stop()


@pytest.fixture
def cc_host():
    mock = MagicMock()
    mock.get_call_card.return_value = {"session_id": "s1", "facts": [], "action_items": []}
    return mock


@pytest.fixture
def api_with_cc(posture, engine, cc_host, tmp_sock):
    """DaemonAPI with a mocked call_card_host."""
    a = DaemonAPI(posture=posture, engine=engine, call_card_host=cc_host, socket_path=tmp_sock)
    a.start()
    yield a
    a.stop()


def _connect(sock_path: Path):
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(str(sock_path))
    return sock.makefile("rb"), sock.makefile("wb"), sock


def _send_recv(rfile, wfile, cmd: dict) -> dict:
    line = json.dumps(cmd, separators=(",", ":")) + "\n"
    wfile.write(line.encode())
    wfile.flush()
    raw = rfile.readline()
    return json.loads(raw)


# ---------------------------------------------------------------------------
# confirm_fact
# ---------------------------------------------------------------------------

def test_confirm_fact_no_cc_host(api_no_cc, tmp_sock):
    rfile, wfile, sock = _connect(tmp_sock)
    resp = _send_recv(rfile, wfile, {"cmd": "confirm_fact", "session_id": "s1", "fact_id": "f1"})
    assert resp["ok"] is False
    assert "call_card not configured" in resp["error"]
    sock.close()


def test_confirm_fact_delegates_to_host(api_with_cc, cc_host, tmp_sock):
    rfile, wfile, sock = _connect(tmp_sock)
    resp = _send_recv(rfile, wfile, {
        "cmd": "confirm_fact", "session_id": "s1", "fact_id": "f1", "confirmed": True,
    })
    assert resp["ok"] is True
    cc_host.confirm_fact.assert_called_once()
    sock.close()


def test_confirm_fact_missing_fields(api_with_cc, tmp_sock):
    rfile, wfile, sock = _connect(tmp_sock)
    resp = _send_recv(rfile, wfile, {"cmd": "confirm_fact", "session_id": "s1"})
    assert resp["ok"] is False
    assert "Missing" in resp["error"]
    sock.close()


# ---------------------------------------------------------------------------
# confirm_action_item
# ---------------------------------------------------------------------------

def test_confirm_action_item_no_cc_host(api_no_cc, tmp_sock):
    rfile, wfile, sock = _connect(tmp_sock)
    resp = _send_recv(rfile, wfile, {"cmd": "confirm_action_item", "session_id": "s1", "item_id": "a1"})
    assert resp["ok"] is False
    assert "call_card not configured" in resp["error"]
    sock.close()


def test_confirm_action_item_delegates_to_host(api_with_cc, cc_host, tmp_sock):
    rfile, wfile, sock = _connect(tmp_sock)
    resp = _send_recv(rfile, wfile, {
        "cmd": "confirm_action_item", "session_id": "s1", "item_id": "a1", "confirmed": True,
    })
    assert resp["ok"] is True
    cc_host.confirm_action_item.assert_called_once()
    sock.close()


def test_confirm_action_item_missing_fields(api_with_cc, tmp_sock):
    rfile, wfile, sock = _connect(tmp_sock)
    resp = _send_recv(rfile, wfile, {"cmd": "confirm_action_item", "session_id": "s1"})
    assert resp["ok"] is False
    assert "Missing" in resp["error"]
    sock.close()


# ---------------------------------------------------------------------------
# disclosure_ack
# ---------------------------------------------------------------------------

def test_disclosure_ack_no_cc_host(api_no_cc, tmp_sock):
    rfile, wfile, sock = _connect(tmp_sock)
    resp = _send_recv(rfile, wfile, {"cmd": "disclosure_ack", "session_id": "s1"})
    assert resp["ok"] is False
    assert "call_card not configured" in resp["error"]
    sock.close()


def test_disclosure_ack_delegates_to_host(api_with_cc, cc_host, tmp_sock):
    rfile, wfile, sock = _connect(tmp_sock)
    resp = _send_recv(rfile, wfile, {"cmd": "disclosure_ack", "session_id": "s1"})
    assert resp["ok"] is True
    cc_host.disclosure_ack.assert_called_once_with("s1")
    sock.close()


def test_disclosure_ack_missing_session_id(api_with_cc, tmp_sock):
    rfile, wfile, sock = _connect(tmp_sock)
    resp = _send_recv(rfile, wfile, {"cmd": "disclosure_ack"})
    assert resp["ok"] is False
    assert "Missing" in resp["error"]
    sock.close()


# ---------------------------------------------------------------------------
# get_call_card
# ---------------------------------------------------------------------------

def test_get_call_card_no_cc_host(api_no_cc, tmp_sock):
    rfile, wfile, sock = _connect(tmp_sock)
    resp = _send_recv(rfile, wfile, {"cmd": "get_call_card", "session_id": "s1"})
    assert resp["ok"] is False
    assert "call_card not configured" in resp["error"]
    sock.close()


def test_get_call_card_delegates_to_host(api_with_cc, cc_host, tmp_sock):
    rfile, wfile, sock = _connect(tmp_sock)
    resp = _send_recv(rfile, wfile, {"cmd": "get_call_card", "session_id": "s1"})
    assert resp["ok"] is True
    assert "call_card" in resp
    cc_host.get_call_card.assert_called_once()
    sock.close()
