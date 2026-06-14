"""Text-to-speech providers. Local-first; swappable.

EspeakTTS works out of the box (robotic but instant, no model download) so the
voice loop is testable today. KokoroTTS (natural 82M voice) is the quality
swap-in — its own PR (needs the model + a 3.12/3.13 venv on this 3.14 box).
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Protocol

# Kokoro runs in a dedicated 3.12 venv (onnxruntime has no 3.14 wheels) and is
# shelled out network-isolated. Paths resolve relative to the repo so the code
# is portable; override with the IRIS_KOKORO_* env vars.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SYNTH_SCRIPT = Path(__file__).resolve().parent / "_kokoro_synth.py"


class TTS(Protocol):
    name: str

    def synth(self, text: str) -> str:
        """Render ``text`` to a WAV file; return its path."""
        ...


class EspeakTTS:
    """espeak-ng -> WAV. Present on most Linux boxes; zero setup."""

    name = "espeak-ng"

    def __init__(self, voice: str = "en", rate_wpm: int = 165) -> None:
        self.voice = voice
        self.rate_wpm = rate_wpm

    def synth(self, text: str) -> str:
        wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
        subprocess.run(
            ["espeak-ng", "-v", self.voice, "-s", str(self.rate_wpm), "-w", wav, text],
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
        self.voice = os.environ.get("IRIS_KOKORO_VOICE", voice)
        self.speed = speed
        self.python = python or os.environ.get(
            "IRIS_KOKORO_PYTHON", str(_REPO_ROOT / ".venv-kokoro" / "bin" / "python")
        )
        model_dir = Path(
            os.environ.get("IRIS_KOKORO_DIR", str(_REPO_ROOT / "models" / "kokoro"))
        )
        self.model = model or str(model_dir / "kokoro-v1.0.onnx")
        self.voices = voices or str(model_dir / "voices-v1.0.bin")
        self.isolate = isolate

    def available(self) -> bool:
        """True only if the venv, model, voices, and synth script all exist."""
        return all(
            Path(p).exists()
            for p in (self.python, self.model, self.voices, _SYNTH_SCRIPT)
        )

    def synth(self, text: str) -> str:
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
                "--voice", self.voice, "--speed", str(self.speed),
                "--text-file", txt.name, "--out", wav,
            ]
            if self.isolate:
                cmd = ["unshare", "-rn", *cmd]  # fresh net namespace -> no egress
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode != 0:
                raise RuntimeError(
                    f"kokoro synth failed (rc={proc.returncode}): "
                    f"{proc.stderr.strip()[-500:]}"
                )
            return wav
        finally:
            os.unlink(txt.name)


def default_tts() -> TTS:
    """Kokoro (natural) when its model + venv are present; else espeak placeholder."""
    kokoro = KokoroTTS()
    return kokoro if kokoro.available() else EspeakTTS()
