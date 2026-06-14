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

import os
import subprocess
from pathlib import Path
from typing import Protocol

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


def default_stt() -> STT:
    """faster-whisper STT. Callers should check ``.available()`` first — there is
    no zero-setup STT fallback (unlike espeak for TTS), so run setup_whisper.sh."""
    return FasterWhisperSTT()
