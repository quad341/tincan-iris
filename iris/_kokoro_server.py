"""iris-kokoro — persistent HTTP server for Kokoro TTS.

Runs INSIDE the 3.12 kokoro venv. Binds 127.0.0.1:8083.
Override port/URL with IRIS_TTS_SERVER_URL env var.

    python -m iris._kokoro_server --model kokoro-v1.0.onnx --voices voices.bin

API:
    GET  /health  -> 200 {"status":"ok","model":"kokoro-82M","ready":true}
                  | 503 {"status":"loading","model":"kokoro-82M","ready":false}
    POST /synth   Content-Type: application/json
                  body: {"text":"...", "voice":"af_heart", "speed":1.0}
                  -> 200 Content-Type: audio/wav  (raw WAV bytes)
                   | 400 {"error":"missing text"}
                   | 500 {"error":"..."}
"""
from __future__ import annotations

import datetime
import io
import json
import sys
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer

_DEFAULT_PORT = 8083


def _ts() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


@dataclass
class KokoroServerState:
    model_name: str = "kokoro-82M"
    ready: bool = False
    _kokoro: object = field(default=None, repr=False)

    def load(self, model: str, voices: str) -> None:
        print(f"{_ts()} loading kokoro model {model!r}", file=sys.stderr, flush=True)
        from kokoro_onnx import Kokoro
        self._kokoro = Kokoro(model, voices)
        self.ready = True
        print(f"{_ts()} kokoro ready", file=sys.stderr, flush=True)

    def synth(self, text: str, voice: str = "af_heart", speed: float = 1.0) -> bytes:
        import soundfile as sf
        samples, sample_rate = self._kokoro.create(text, voice=voice, speed=speed, lang="en-us")
        buf = io.BytesIO()
        sf.write(buf, samples, sample_rate, format="WAV")
        return buf.getvalue()


class _Response:
    def __init__(self, status_code: int, data: bytes, content_type: str = "application/json"):
        self.status_code = status_code
        self.data = data
        self.content_type = content_type


def _handle_kokoro_get(path: str, state: KokoroServerState) -> _Response:
    if path != "/health":
        return _Response(404, b'{"error":"not found"}')
    if state.ready:
        body = json.dumps({"status": "ok", "model": state.model_name, "ready": True}).encode()
        return _Response(200, body)
    body = json.dumps({"status": "loading", "model": state.model_name, "ready": False}).encode()
    return _Response(503, body)


def _handle_kokoro_post(path: str, body: bytes, state: KokoroServerState) -> _Response:
    if path != "/synth":
        return _Response(404, b'{"error":"not found"}')
    if not state.ready:
        return _Response(503, b'{"error":"model loading"}')
    try:
        data = json.loads(body) if body else {}
    except json.JSONDecodeError:
        return _Response(400, b'{"error":"invalid JSON"}')
    text = data.get("text", "").strip()
    if not text:
        return _Response(400, b'{"error":"missing text"}')
    voice = data.get("voice", "af_heart")
    speed = float(data.get("speed", 1.0))
    try:
        wav_bytes = state.synth(text, voice=voice, speed=speed)
        return _Response(200, wav_bytes, content_type="audio/wav")
    except Exception as exc:
        return _Response(500, json.dumps({"error": str(exc)}).encode())


class _TestAppKokoro:
    """Minimal test client for kokoro app — no HTTP server required."""

    def __init__(self, state: KokoroServerState) -> None:
        self._state = state

    def get(self, path: str) -> _Response:
        return _handle_kokoro_get(path, self._state)

    def post(self, path: str, json: dict | None = None, data: bytes = b"",
             content_type: str = "") -> _Response:
        if json is not None:
            import json as _json
            data = _json.dumps(json).encode()
        return _handle_kokoro_post(path, data, self._state)


def make_kokoro_app(state: KokoroServerState) -> _TestAppKokoro:
    return _TestAppKokoro(state)


_SERVER_STATE: KokoroServerState = KokoroServerState()


class KokoroHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{_ts()} {fmt % args}", file=sys.stderr, flush=True)

    def do_GET(self) -> None:
        resp = _handle_kokoro_get(self.path, _SERVER_STATE)
        self.send_response(resp.status_code)
        self.send_header("Content-Type", resp.content_type)
        self.send_header("Content-Length", str(len(resp.data)))
        self.end_headers()
        self.wfile.write(resp.data)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        resp = _handle_kokoro_post(self.path, body, _SERVER_STATE)
        self.send_response(resp.status_code)
        self.send_header("Content-Type", resp.content_type)
        self.send_header("Content-Length", str(len(resp.data)))
        self.end_headers()
        self.wfile.write(resp.data)


def run_server(port: int = _DEFAULT_PORT, model_path: str = "", voices_path: str = "") -> None:
    try:
        server = HTTPServer(("127.0.0.1", port), KokoroHandler)
    except OSError as exc:
        print(f"{_ts()} iris-kokoro: port {port} in use — {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    if model_path and voices_path:
        t = threading.Thread(
            target=_SERVER_STATE.load, args=(model_path, voices_path), daemon=True
        )
        t.start()
    server.serve_forever()


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--voices", required=True)
    ap.add_argument("--port", type=int, default=_DEFAULT_PORT)
    args = ap.parse_args()
    run_server(port=args.port, model_path=args.model, voices_path=args.voices)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
