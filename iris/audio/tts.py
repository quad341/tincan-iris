"""Text-to-speech providers. Local-first; swappable.

EspeakTTS works out of the box (robotic but instant, no model download) so the
voice loop is testable today. KokoroTTS (natural 82M voice) is the quality
swap-in — its own PR (needs the model + a 3.12/3.13 venv on this 3.14 box).
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Protocol

from .. import settings
from .assets import resolve_asset


class TTSError(Exception):
    """Raised when a server-mode TTS call fails."""


_DEFAULT_TTS_SERVER_URL = "http://127.0.0.1:8083"

# Kokoro runs in a dedicated 3.12 venv (onnxruntime has no 3.14 wheels) and is
# shelled out network-isolated. Paths resolve via assets.resolve_asset (env
# override -> repo-local -> shared XDG home) so any clone works without per-clone
# setup; override explicitly with the IRIS_KOKORO_* env vars.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SYNTH_SCRIPT = Path(__file__).resolve().parent / "_kokoro_synth.py"


class TTS(Protocol):
    name: str

    def synth(self, text: str, *, speed: float = 1.0) -> str:
        """Render ``text`` to a WAV file; return its path.

        speed is a cadence multiplier (1.0 = normal, 0.7 = slow-mode for re-ask turns).
        """
        ...


class EspeakTTS:
    """espeak-ng -> WAV. Present on most Linux boxes; zero setup."""

    name = "espeak-ng"

    def __init__(self, voice: str = "en", rate_wpm: int = 165) -> None:
        self.voice = voice
        self.rate_wpm = rate_wpm

    def synth(self, text: str, *, speed: float = 1.0) -> str:
        wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
        effective_wpm = max(1, round(self.rate_wpm * speed))
        subprocess.run(
            ["espeak-ng", "-v", self.voice, "-s", str(effective_wpm), "-w", wav, text],
            check=True,
        )
        return wav


class KokoroTTS:
    """Natural 82M voice (kokoro-82M) via a network-isolated 3.12 venv.

    Kokoro ships as ONNX and needs onnxruntime, which has no wheels for this
    box's Python 3.14 — so synthesis runs in a dedicated 3.12 venv, shelled out
    and wrapped in ``unshare -rn`` so the third-party model runs with no network
    egress (download != execute; see the sandbox-inference memory). ONNX here is
    operator-approved on the condition that inference stays network-isolated.
    """

    name = "kokoro"

    def __init__(
        self,
        voice: str = "af_heart",
        speed: float = 1.0,
        *,
        python: str | None = None,
        model: str | None = None,
        voices: str | None = None,
        isolate: bool = True,
    ) -> None:
        self.voice = settings.get("IRIS_KOKORO_VOICE", voice)
        self.speed = speed
        self.python = python or resolve_asset(
            "IRIS_KOKORO_PYTHON", ".venv-kokoro/bin/python", _REPO_ROOT
        )
        model_dir = Path(resolve_asset("IRIS_KOKORO_DIR", "models/kokoro", _REPO_ROOT))
        self.model = model or str(model_dir / "kokoro-v1.0.onnx")
        self.voices = voices or str(model_dir / "voices-v1.0.bin")
        self.isolate = isolate

    def available(self) -> bool:
        """True only if the venv, model, voices, and synth script all exist."""
        return all(
            Path(p).exists()
            for p in (self.python, self.model, self.voices, _SYNTH_SCRIPT)
        )

    def synth(self, text: str, *, speed: float = 1.0, lang: str | None = None) -> str:
        wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
        txt = tempfile.NamedTemporaryFile(
            suffix=".txt", delete=False, mode="w", encoding="utf-8"
        )
        try:
            txt.write(text)
            txt.close()
            cmd = [
                self.python, str(_SYNTH_SCRIPT),
                "--model", self.model, "--voices", self.voices,
                "--voice", self.voice, "--speed", str(self.speed * speed),
                "--text-file", txt.name, "--out", wav,
            ]
            if lang is not None:
                cmd += ["--lang", lang]
            if self.isolate:
                cmd = ["unshare", "-rn", *cmd]  # fresh net namespace -> no egress
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if proc.returncode != 0:
                raise RuntimeError(
                    f"kokoro synth failed (rc={proc.returncode}): "
                    f"{proc.stderr.strip()[-500:]}"
                )
            return wav
        finally:
            os.unlink(txt.name)


class KokoroServerTTS:
    """TTS via iris-kokoro persistent HTTP server (port 8083).

    Falls back gracefully when the server is not running.
    """

    name = "kokoro-server"

    def __init__(
        self,
        server_url: str | None = None,
        voice: str = "af_heart",
        speed: float = 1.0,
    ) -> None:
        self._server_url = (
            server_url or settings.get("IRIS_TTS_SERVER_URL", _DEFAULT_TTS_SERVER_URL)
        ).rstrip("/")
        self.voice = voice
        self.speed = speed

    def available(self) -> bool:
        try:
            req = urllib.request.Request(f"{self._server_url}/health")
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                data = json.loads(resp.read())
                return bool(data.get("ready"))
        except (TimeoutError, urllib.error.URLError, json.JSONDecodeError, OSError):
            return False

    def synth(self, text: str, *, voice: str | None = None, speed: float = 1.0,
              lang: str | None = None) -> str:
        payload: dict = {
            "text": text,
            "voice": voice if voice is not None else self.voice,
            "speed": self.speed * speed,
        }
        if lang is not None:
            payload["lang"] = lang
        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{self._server_url}/synth",
            data=body,
            method="POST",
        )
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30.0) as resp:
                wav_bytes = resp.read()
        except Exception as exc:
            raise TTSError(f"synth failed: {exc}") from exc
        wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        wav.write(wav_bytes)
        wav.close()
        return wav.name


def default_tts() -> TTS:
    """Prefer server TTS when running; fall back to subprocess KokoroTTS."""
    server = KokoroServerTTS()
    if server.available():
        return server
    return KokoroTTS()
