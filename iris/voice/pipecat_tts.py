"""IrisTTSService: Pipecat TTSService wrapping KokoroTTS/EspeakTTS (or any TTS protocol)."""
from __future__ import annotations

import asyncio
import os
import wave
from collections.abc import AsyncGenerator

try:
    from pipecat.frames.frames import AudioRawFrame, TTSStartedFrame, TTSStoppedFrame
    from pipecat.services.tts_service import TTSService
except ImportError as exc:
    raise ImportError(
        "pipecat-ai is required for IrisTTSService — "
        "install pipecat-ai or run iris without the Pipecat voice pipeline."
    ) from exc

_CHUNK_MS = 20  # 20 ms chunks to minimise output latency


class IrisTTSService(TTSService):
    """Wraps any TTS with .synth(text) -> wav_path as a Pipecat TTSService.

    Sets voice and speed on the TTS before each synth call, runs synth() in a
    ThreadPoolExecutor (never blocks the event loop), reads sample_rate from the
    WAV header (not hard-coded), and cleans up the temp WAV when done.
    """

    def __init__(self, tts, voice: str, speed: float = 1.0) -> None:
        super().__init__()
        self._tts = tts
        self._voice = voice
        self._speed = speed

    async def run_tts(self, text: str, context_id: str = "") -> AsyncGenerator:  # type: ignore[override]
        loop = asyncio.get_running_loop()

        self._tts.voice = self._voice
        self._tts.speed = self._speed

        yield TTSStartedFrame(context_id=context_id)

        wav_path: str = await loop.run_in_executor(None, self._tts.synth, text)

        try:
            with wave.open(wav_path, "rb") as wf:
                sample_rate = wf.getframerate()
                n_channels = wf.getnchannels()
                chunk_frames = int(sample_rate * _CHUNK_MS / 1000)
                while True:
                    data = wf.readframes(chunk_frames)
                    if not data:
                        break
                    yield AudioRawFrame(
                        audio=data,
                        sample_rate=sample_rate,
                        num_channels=n_channels,
                    )
        finally:
            os.unlink(wav_path)

        yield TTSStoppedFrame(context_id=context_id)
