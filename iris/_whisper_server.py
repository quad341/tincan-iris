"""iris-whisper — persistent HTTP server for faster-whisper STT.

Runs INSIDE the 3.12 whisper venv. Binds 127.0.0.1:8082.
Override port/URL with IRIS_STT_SERVER_URL env var.

    python -m iris._whisper_server --model models/whisper/small.en

API:
    GET  /health   -> 200 {"status":"ok","model":"...","ready":true}
                    | 503 {"status":"loading","model":"...","ready":false}
    POST /transcribe  body: raw WAV bytes
                   -> 200 {"text":"..."}
                    | 400 {"error":"no audio data"}
                    | 500 {"error":"..."}
"""
from __future__ import annotations

import datetime
import json
import os
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

_DEFAULT_PORT = 8082


def _ts() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


@dataclass
class WhisperServerState:
    model_name: str = ""
    ready: bool = False
    _model: object = field(default=None, repr=False)

    def load(self, model_path: str, compute_type: str = "int8") -> None:
        self.model_name = Path(model_path).name
        print(f"{_ts()} loading whisper model {model_path!r}", file=sys.stderr, flush=True)
        from faster_whisper import WhisperModel
        self._model = WhisperModel(model_path, device="cpu", compute_type=compute_type)
        self.ready = True
        print(f"{_ts()} whisper ready", file=sys.stderr, flush=True)

    def transcribe(self, wav_path: str) -> str:
        segments, _ = self._model.transcribe(wav_path, language="en", beam_size=5)
        return "".join(seg.text for seg in segments).strip()


class _Response:
    def __init__(self, status_code: int, data: bytes, content_type: str = "application/json"):
        self.status_code = status_code
        self.data = data
        self.content_type = content_type


def _handle_whisper_get(path: str, state: WhisperServerState) -> _Response:
    if path != "/health":
        return _Response(404, b'{"error":"not found"}')
    if state.ready:
        body = json.dumps({"status": "ok", "model": state.model_name, "ready": True}).encode()
        return _Response(200, body)
    body = json.dumps({"status": "loading", "model": state.model_name, "ready": False}).encode()
    return _Response(503, body)


def _handle_whisper_post(
    path: str, body: bytes, state: WhisperServerState
) -> _Response:
    if path != "/transcribe":
        return _Response(404, b'{"error":"not found"}')
    if not state.ready:
        return _Response(503, b'{"error":"model loading"}')
    if not body:
        return _Response(400, b'{"error":"no audio data"}')
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(body)
            tmp = f.name
        try:
            text = state.transcribe(tmp)
        finally:
            os.unlink(tmp)
        return _Response(200, json.dumps({"text": text}).encode())
    except Exception as exc:
        return _Response(500, json.dumps({"error": str(exc)}).encode())


class _TestAppWhisper:
    """Minimal test client for whisper app — no HTTP server required."""

    def __init__(self, state: WhisperServerState) -> None:
        self._state = state

    def get(self, path: str) -> _Response:
        return _handle_whisper_get(path, self._state)

    def post(self, path: str, data: bytes = b"", content_type: str = "") -> _Response:
        return _handle_whisper_post(path, data, self._state)


def make_whisper_app(state: WhisperServerState) -> _TestAppWhisper:
    return _TestAppWhisper(state)


# Module-level server state (used by the actual HTTP handler)
_SERVER_STATE: WhisperServerState = WhisperServerState()


class WhisperHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{_ts()} {fmt % args}", file=sys.stderr, flush=True)

    def do_GET(self) -> None:
        resp = _handle_whisper_get(self.path, _SERVER_STATE)
        self.send_response(resp.status_code)
        self.send_header("Content-Type", resp.content_type)
        self.send_header("Content-Length", str(len(resp.data)))
        self.end_headers()
        self.wfile.write(resp.data)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        resp = _handle_whisper_post(self.path, body, _SERVER_STATE)
        self.send_response(resp.status_code)
        self.send_header("Content-Type", resp.content_type)
        self.send_header("Content-Length", str(len(resp.data)))
        self.end_headers()
        self.wfile.write(resp.data)


def run_server(port: int = _DEFAULT_PORT, model_path: str = "", compute_type: str = "int8") -> None:
    try:
        server = HTTPServer(("127.0.0.1", port), WhisperHandler)
    except OSError as exc:
        print(f"{_ts()} iris-whisper: port {port} in use — {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    if model_path:
        t = threading.Thread(
            target=_SERVER_STATE.load, args=(model_path, compute_type), daemon=True
        )
        t.start()
    server.serve_forever()


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--compute-type", default="int8")
    ap.add_argument("--port", type=int, default=_DEFAULT_PORT)
    args = ap.parse_args()
    run_server(port=args.port, model_path=args.model, compute_type=args.compute_type)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
