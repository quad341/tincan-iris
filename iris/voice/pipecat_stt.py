"""IrisSTTService: Pipecat STTService wrapping FasterWhisperSTT (or any STT protocol)."""
from __future__ import annotations

import asyncio
import os
import tempfile
import wave
from typing import AsyncGenerator

try:
    from pipecat.frames.frames import TranscriptionFrame
    from pipecat.services.stt_service import STTService
except ImportError as exc:
    raise ImportError(
        "pipecat-ai is required for IrisSTTService — "
        "install pipecat-ai or run iris without the Pipecat voice pipeline."
    ) from exc


class IrisSTTService(STTService):
    """Wraps any STT with .transcribe(wav_path) / .language as a Pipecat STTService.

    Runs transcribe() in a ThreadPoolExecutor so it never blocks the event loop.
    Empty transcripts produce no frame (silence guard).
    """

    def __init__(self, stt) -> None:
        super().__init__()
        self._stt = stt

    async def run_stt(self, audio: bytes) -> AsyncGenerator:  # type: ignore[override]
        loop = asyncio.get_running_loop()

        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp_path = tmp.name
        tmp.close()

        try:
            with wave.open(tmp_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(audio)

            text: str = await loop.run_in_executor(None, self._stt.transcribe, tmp_path)

            if text:
                yield TranscriptionFrame(text=text)
        finally:
            os.unlink(tmp_path)

    def set_language_hint(self, lang: str | None) -> None:
        self._stt.language = lang
