"""Speech-to-text providers. Local-first; swappable.

FasterWhisperSTT (faster-whisper / CTranslate2) is the real local STT. Like
Kokoro, it runs in a dedicated 3.12 venv (no ctranslate2 wheels for this box's
3.14), shelled out and wrapped in ``unshare -rn`` so the model runs with no
network egress — the model is pre-downloaded by scripts/setup_whisper.sh
(download != execute; see the sandbox-inference memory). WhisperCppSTT is the
documented C++ alternative, not wired. Until STT is set up, voice mode stays
text-in / voice-out.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Protocol


class STTError(Exception):
    """Raised when a server-mode STT call fails."""


_DEFAULT_STT_SERVER_URL = "http://127.0.0.1:8082"

# Resolve paths relative to the repo so the code is portable; override with the
# IRIS_WHISPER_* env vars. The transcribe script lives beside this module but
# runs under the 3.12 venv's interpreter, never imported into this package.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_TRANSCRIBE_SCRIPT = Path(__file__).resolve().parent / "_whisper_transcribe.py"
_DEFAULT_SIZE = os.environ.get("IRIS_WHISPER_MODEL_SIZE", "small.en")


class STT(Protocol):
    name: str

    def transcribe(self, wav_path: str) -> str:
        """Transcribe a WAV file to text."""
        ...


class FasterWhisperSTT:
    """Local faster-whisper STT via a network-isolated 3.12 venv."""

    name = "faster-whisper"

    def __init__(
        self,
        *,
        python: str | None = None,
        model: str | None = None,
        compute_type: str = "int8",
        language: str = "en",
        beam_size: int = 5,
        isolate: bool = True,
    ) -> None:
        self.python = python or os.environ.get(
            "IRIS_WHISPER_PYTHON",
            str(_REPO_ROOT / ".venv-whisper" / "bin" / "python"),
        )
        self.model = model or os.environ.get(
            "IRIS_WHISPER_DIR",
            str(_REPO_ROOT / "models" / "whisper" / _DEFAULT_SIZE),
        )
        self.compute_type = compute_type
        self.language = language
        self.beam_size = beam_size
        self.isolate = isolate

    def available(self) -> bool:
        """True only if the venv, model dir, and transcribe script all exist."""
        return all(
            Path(p).exists() for p in (self.python, self.model, _TRANSCRIBE_SCRIPT)
        )

    def transcribe(self, wav_path: str) -> str:
        cmd = [
            self.python, str(_TRANSCRIBE_SCRIPT),
            "--model", self.model, "--wav", wav_path,
            "--compute-type", self.compute_type,
            "--language", self.language, "--beam-size", str(self.beam_size),
        ]
        if self.isolate:
            cmd = ["unshare", "-rn", *cmd]  # fresh net namespace -> no egress
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(
                f"whisper transcribe failed (rc={proc.returncode}): "
                f"{proc.stderr.strip()[-500:]}"
            )
        return proc.stdout.strip()


class WhisperCppSTT:
    """whisper.cpp CLI wrapper — the documented C++ alternative. Not wired."""

    name = "whisper.cpp"

    def __init__(self, binary: str = "whisper-cli", model: str = "") -> None:
        self.binary = binary
        self.model = model

    def transcribe(self, wav_path: str) -> str:
        raise NotImplementedError(
            "whisper.cpp STT is an alternative; use FasterWhisperSTT"
        )


class FasterWhisperServerSTT:
    """STT via iris-whisper persistent HTTP server (port 8082).

    Falls back gracefully when the server is not running.
    """

    name = "faster-whisper-server"

    def __init__(self, server_url: str | None = None) -> None:
        self._server_url = (
            server_url or os.environ.get("IRIS_STT_SERVER_URL", _DEFAULT_STT_SERVER_URL)
        ).rstrip("/")

    def available(self) -> bool:
        try:
            req = urllib.request.Request(f"{self._server_url}/health")
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                data = json.loads(resp.read())
                return bool(data.get("ready"))
        except (urllib.error.URLError, socket.timeout, json.JSONDecodeError, OSError):
            return False

    def transcribe(self, wav_path: str) -> str:
        wav_bytes = Path(wav_path).read_bytes()
        req = urllib.request.Request(
            f"{self._server_url}/transcribe",
            data=wav_bytes,
            method="POST",
        )
        req.add_header("Content-Type", "audio/wav")
        try:
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read())
                return data["text"]
        except Exception as exc:
            raise STTError(f"transcribe failed: {exc}") from exc


def default_stt() -> STT:
    """Prefer server STT when running; fall back to subprocess faster-whisper."""
    server = FasterWhisperServerSTT()
    if server.available():
        return server
    return FasterWhisperSTT()
