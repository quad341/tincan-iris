"""Tests for _whisper_server.py + _kokoro_server.py HTTP servers (ti-qxel.1).

These tests FAIL until the builder implements the persistent HTTP servers.
No real model is loaded — handler logic is tested in isolation with the
model mocked out.
"""
from __future__ import annotations

import io
import json
import socket
import sys
from http.server import BaseHTTPRequestHandler
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Whisper server — /health
# ---------------------------------------------------------------------------

class _FakeRequest:
    """Minimal fake socket for BaseHTTPRequestHandler construction."""
    def __init__(self, raw: bytes):
        self._data = io.BytesIO(raw)
        self._out = io.BytesIO()

    def makefile(self, mode, *args, **kwargs):
        if "r" in mode:
            return io.TextIOWrapper(self._data, encoding="iso-8859-1")
        return self._out

    def sendall(self, data: bytes):
        self._out.write(data)


def _build_get(path: str) -> bytes:
    return f"GET {path} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode()


def _build_post(path: str, body: bytes, content_type: str = "application/octet-stream") -> bytes:
    return (
        f"POST {path} HTTP/1.1\r\n"
        f"Host: localhost\r\n"
        f"Content-Type: {content_type}\r\n"
        f"Content-Length: {len(body)}\r\n"
        "\r\n"
    ).encode() + body


def _response_code(raw: bytes) -> int:
    first_line = raw.split(b"\r\n")[0]
    return int(first_line.split()[1])


def _response_body(raw: bytes) -> bytes:
    idx = raw.find(b"\r\n\r\n")
    return raw[idx + 4:] if idx != -1 else b""


# ---------------------------------------------------------------------------
# Whisper server — /health
# ---------------------------------------------------------------------------

def test_whisper_health_returns_503_while_loading():
    from iris._whisper_server import WhisperHandler

    handler_cls = WhisperHandler
    server_state = MagicMock()
    server_state.ready = False
    server_state.model_name = "small"

    req = _FakeRequest(_build_get("/health"))
    handler = handler_cls.__new__(handler_cls)
    handler.server = MagicMock(state=server_state)
    handler.request = req
    handler.client_address = ("127.0.0.1", 9999)
    handler.rfile = io.BytesIO(_build_get("/health"))
    handler.wfile = io.BytesIO()
    handler.handle_one_request = lambda: handler.do_GET()
    handler.send_response = MagicMock(side_effect=lambda code: handler.wfile.write(
        f"HTTP/1.1 {code}\r\n".encode()))
    handler.send_header = MagicMock()
    handler.end_headers = MagicMock()

    # Use the public interface instead — instantiate fully via setup
    with patch("iris._whisper_server._SERVER_STATE", server_state):
        from iris._whisper_server import make_whisper_app
        app = make_whisper_app(state=server_state)
        resp = app.get("/health")
        assert resp.status_code == 503


def test_whisper_health_returns_200_when_ready():
    from iris._whisper_server import make_whisper_app

    state = MagicMock(ready=True, model_name="small")
    app = make_whisper_app(state=state)
    resp = app.get("/health")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["ready"] is True


# ---------------------------------------------------------------------------
# Whisper server — /transcribe
# ---------------------------------------------------------------------------

def test_whisper_transcribe_empty_body_returns_400():
    from iris._whisper_server import make_whisper_app

    state = MagicMock(ready=True, model_name="small")
    state.transcribe.return_value = "hello"
    app = make_whisper_app(state=state)
    resp = app.post("/transcribe", data=b"", content_type="application/octet-stream")
    assert resp.status_code == 400


def test_whisper_transcribe_valid_wav_returns_200_with_text():
    from iris._whisper_server import make_whisper_app

    state = MagicMock(ready=True, model_name="small")
    state.transcribe.return_value = "hello world"
    app = make_whisper_app(state=state)
    fake_wav = b"RIFF" + b"\x00" * 40  # minimal fake WAV header
    resp = app.post("/transcribe", data=fake_wav, content_type="application/octet-stream")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert "text" in data
    assert data["text"] == "hello world"


# ---------------------------------------------------------------------------
# Kokoro server — /health
# ---------------------------------------------------------------------------

def test_kokoro_health_returns_503_while_loading():
    from iris._kokoro_server import make_kokoro_app

    state = MagicMock(ready=False, model_name="kokoro-82M")
    app = make_kokoro_app(state=state)
    resp = app.get("/health")
    assert resp.status_code == 503


def test_kokoro_health_returns_200_when_ready():
    from iris._kokoro_server import make_kokoro_app

    state = MagicMock(ready=True, model_name="kokoro-82M")
    app = make_kokoro_app(state=state)
    resp = app.get("/health")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["ready"] is True


# ---------------------------------------------------------------------------
# Kokoro server — /synth
# ---------------------------------------------------------------------------

def test_kokoro_synth_missing_text_returns_400():
    from iris._kokoro_server import make_kokoro_app

    state = MagicMock(ready=True, model_name="kokoro-82M")
    app = make_kokoro_app(state=state)
    resp = app.post("/synth", json={"voice": "af_sky"},
                    content_type="application/json")
    assert resp.status_code == 400


def test_kokoro_synth_valid_json_returns_200_with_wav_bytes():
    from iris._kokoro_server import make_kokoro_app

    fake_wav = b"RIFF" + b"\x00" * 40
    state = MagicMock(ready=True, model_name="kokoro-82M")
    state.synth.return_value = fake_wav
    app = make_kokoro_app(state=state)
    resp = app.post("/synth", json={"text": "hello", "voice": "af_sky", "speed": 1.0},
                    content_type="application/json")
    assert resp.status_code == 200
    assert resp.data == fake_wav


# ---------------------------------------------------------------------------
# Port-in-use exits 1
# ---------------------------------------------------------------------------

def test_port_in_use_exits_with_code_1(tmp_path):
    """Binding a port already in use should exit(1), not hang."""
    # Bind the port first so it's occupied
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    try:
        with pytest.raises(SystemExit) as exc_info:
            from iris._whisper_server import run_server
            run_server(port=port, model_path="/nonexistent")
        assert exc_info.value.code == 1
    finally:
        sock.close()


# ---------------------------------------------------------------------------
# Startup loading state
# ---------------------------------------------------------------------------

def test_whisper_server_loading_state_before_model():
    from iris._whisper_server import WhisperServerState

    state = WhisperServerState()
    assert state.ready is False


def test_kokoro_server_loading_state_before_model():
    from iris._kokoro_server import KokoroServerState

    state = KokoroServerState()
    assert state.ready is False
