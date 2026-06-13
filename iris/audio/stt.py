"""Speech-to-text providers. Local-first; swappable.

WhisperCppSTT shells out to whisper.cpp's CLI once it's built; until then the
voice mode is text-in / voice-out (no mic). The full mic loop is the next PR.
"""
from __future__ import annotations

from typing import Protocol


class STT(Protocol):
    name: str

    def transcribe(self, wav_path: str) -> str:
        """Transcribe a WAV file to text."""
        ...


class WhisperCppSTT:
    """whisper.cpp CLI wrapper. Build whisper.cpp + grab a model first."""

    name = "whisper.cpp"

    def __init__(self, binary: str = "whisper-cli", model: str = "") -> None:
        self.binary = binary
        self.model = model

    def transcribe(self, wav_path: str) -> str:
        raise NotImplementedError("whisper.cpp STT lands in its own PR (build + model)")
