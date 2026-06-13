"""Text-to-speech providers. Local-first; swappable.

EspeakTTS works out of the box (robotic but instant, no model download) so the
voice loop is testable today. KokoroTTS (natural 82M voice) is the quality
swap-in — its own PR (needs the model + a 3.12/3.13 venv on this 3.14 box).
"""
from __future__ import annotations

import subprocess
import tempfile
from typing import Protocol


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
    """Natural 82M voice (kokoro-82M). Not wired yet — the quality swap-in."""

    name = "kokoro"

    def synth(self, text: str) -> str:
        raise NotImplementedError(
            "Kokoro TTS lands in its own PR (needs the kokoro-82M model + a venv)"
        )
