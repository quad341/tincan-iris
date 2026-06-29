"""Unit tests for iris/voice/pipecat_tts.py (ti-eq6d.2.1).

IrisTTSService wraps KokoroTTS/EspeakTTS as a Pipecat TTSService.

pipecat-ai is not installed in the test environment — a minimal stub is
injected into sys.modules before the iris.voice import so the module loads.
The ImportError case removes the stubs and verifies re-import raises.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import threading
import types
import wave
from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Pipecat stubs
# ---------------------------------------------------------------------------

def _install_pipecat_stubs() -> None:
    """Inject minimal pipecat stubs into sys.modules (idempotent)."""
    if "pipecat.services.tts_service" in sys.modules:
        return

    class Frame:
        pass

    @dataclass
    class AudioRawFrame(Frame):
        audio: bytes
        sample_rate: int
        num_channels: int

    @dataclass
    class TTSAudioRawFrame(AudioRawFrame):
        context_id: str | None = None

    @dataclass
    class TTSStartedFrame(Frame):
        context_id: str | None = None

    @dataclass
    class TTSStoppedFrame(Frame):
        context_id: str | None = None

    class AIService:
        def __init__(self, **kwargs):
            pass

    class TTSService(AIService):
        async def run_tts(self, text: str, context_id: str = ""):
            return
            yield  # unreachable — makes it an async generator

    pipecat = types.ModuleType("pipecat")
    frames_pkg = types.ModuleType("pipecat.frames")
    frames_mod = types.ModuleType("pipecat.frames.frames")
    frames_mod.Frame = Frame
    frames_mod.AudioRawFrame = AudioRawFrame
    frames_mod.TTSAudioRawFrame = TTSAudioRawFrame
    frames_mod.TTSStartedFrame = TTSStartedFrame
    frames_mod.TTSStoppedFrame = TTSStoppedFrame

    services_pkg = types.ModuleType("pipecat.services")
    tts_mod = types.ModuleType("pipecat.services.tts_service")
    tts_mod.TTSService = TTSService
    ai_mod = types.ModuleType("pipecat.services.ai_service")
    ai_mod.AIService = AIService

    sys.modules.update({
        "pipecat": pipecat,
        "pipecat.frames": frames_pkg,
        "pipecat.frames.frames": frames_mod,
        "pipecat.services": services_pkg,
        "pipecat.services.tts_service": tts_mod,
        "pipecat.services.ai_service": ai_mod,
    })


_install_pipecat_stubs()

from iris.voice.pipecat_tts import IrisTTSService  # noqa: E402

# Grab the stub AudioRawFrame so tests can do isinstance checks
_AudioRawFrame = sys.modules["pipecat.frames.frames"].AudioRawFrame


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_wav_file(*, rate: int = 24000, duration_ms: int = 40) -> str:
    """Write a minimal WAV file to a temp path; return the path."""
    n_frames = int(rate * duration_ms / 1000)
    fd, path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"\x00\x00" * n_frames)
    return path


def _mock_tts(*, rate: int = 24000) -> MagicMock:
    """Return a mock TTS whose synth() writes a real WAV and returns its path."""
    mock = MagicMock()
    mock.voice = "af_heart"
    mock.speed = 1.0

    def _synth(text: str) -> str:
        return _make_wav_file(rate=rate)

    mock.synth.side_effect = _synth
    return mock


async def _collect(gen) -> list:
    return [f async for f in gen]


# ---------------------------------------------------------------------------
# 1. run_tts emits >=1 AudioRawFrame for non-empty text
# ---------------------------------------------------------------------------

def test_run_tts_emits_at_least_one_audio_frame():
    """Non-empty text synthesis yields at least one AudioRawFrame."""
    service = IrisTTSService(_mock_tts(), voice="af_heart", speed=1.0)
    frames = asyncio.run(_collect(service.run_tts("Hello, world.", "ctx-1")))

    audio_frames = [f for f in frames if isinstance(f, _AudioRawFrame)]
    assert len(audio_frames) >= 1, "No AudioRawFrame yielded for non-empty text"


# ---------------------------------------------------------------------------
# 2. sample_rate matches WAV header (not hard-coded 24000)
# ---------------------------------------------------------------------------

def test_sample_rate_matches_wav_header():
    """Emitted AudioRawFrame.sample_rate is read from the WAV header, not hard-coded."""
    UNUSUAL_RATE = 22050  # deliberately different from the default 24000

    service = IrisTTSService(_mock_tts(rate=UNUSUAL_RATE), voice="af_heart", speed=1.0)
    frames = asyncio.run(_collect(service.run_tts("Test.", "ctx-1")))

    audio_frames = [f for f in frames if isinstance(f, _AudioRawFrame)]
    assert audio_frames, "No AudioRawFrame yielded"
    for frame in audio_frames:
        assert frame.sample_rate == UNUSUAL_RATE, (
            f"Expected sample_rate={UNUSUAL_RATE} (from WAV header), got {frame.sample_rate}"
        )


# ---------------------------------------------------------------------------
# 3. Executor path exercised
# ---------------------------------------------------------------------------

def test_run_tts_does_not_block_event_loop():
    """tts.synth() must run in a ThreadPoolExecutor thread, not the event-loop thread."""
    caller_threads: list[threading.Thread] = []

    mock_tts = MagicMock()
    mock_tts.voice = "af_heart"
    mock_tts.speed = 1.0

    def _synth(text: str) -> str:
        caller_threads.append(threading.current_thread())
        return _make_wav_file(rate=24000)

    mock_tts.synth.side_effect = _synth

    service = IrisTTSService(mock_tts, voice="af_heart", speed=1.0)
    asyncio.run(_collect(service.run_tts("Hello.", "ctx-1")))

    assert caller_threads, "synth() was never called"
    assert caller_threads[0] is not threading.main_thread(), (
        "synth() ran on the main thread — run_in_executor was not used"
    )


# ---------------------------------------------------------------------------
# 4. voice and speed forwarded to tts.synth()
# ---------------------------------------------------------------------------

def test_voice_and_speed_forwarded_to_tts():
    """Constructor voice and speed values are applied to the TTS before synth() runs."""
    voice_at_synth: list[str] = []
    speed_at_synth: list[float] = []

    mock_tts = MagicMock()
    mock_tts.voice = None
    mock_tts.speed = None

    def _synth(text: str) -> str:
        voice_at_synth.append(mock_tts.voice)
        speed_at_synth.append(mock_tts.speed)
        return _make_wav_file(rate=24000)

    mock_tts.synth.side_effect = _synth

    service = IrisTTSService(mock_tts, voice="af_bella", speed=0.8)
    asyncio.run(_collect(service.run_tts("Test.", "ctx-1")))

    assert voice_at_synth, "synth() was not called"
    assert voice_at_synth[0] == "af_bella", (
        f"Expected voice='af_bella', got '{voice_at_synth[0]}'"
    )
    assert abs(speed_at_synth[0] - 0.8) < 1e-9, (
        f"Expected speed=0.8, got {speed_at_synth[0]}"
    )


# ---------------------------------------------------------------------------
# 5. Temp WAV cleaned up after all frames are yielded
# ---------------------------------------------------------------------------

def test_temp_wav_cleaned_up_after_frames_yielded():
    """The WAV file returned by tts.synth() is deleted after the generator completes."""
    synth_paths: list[str] = []

    mock_tts = MagicMock()
    mock_tts.voice = "af_heart"
    mock_tts.speed = 1.0

    def _synth(text: str) -> str:
        path = _make_wav_file(rate=24000)
        synth_paths.append(path)
        return path

    mock_tts.synth.side_effect = _synth

    service = IrisTTSService(mock_tts, voice="af_heart", speed=1.0)
    asyncio.run(_collect(service.run_tts("Hello.", "ctx-1")))

    assert synth_paths, "synth() was not called"
    for path in synth_paths:
        assert not os.path.exists(path), f"temp WAV not cleaned up: {path}"


# ---------------------------------------------------------------------------
# 6. ImportError when pipecat-ai absent
# ---------------------------------------------------------------------------

def test_import_error_without_pipecat():
    """Importing iris.voice.pipecat_tts without pipecat-ai raises ImportError
    naming 'pipecat'."""
    import importlib

    saved_pipecat = {k: sys.modules.pop(k) for k in list(sys.modules) if k.startswith("pipecat")}
    saved_voice = {k: sys.modules.pop(k) for k in list(sys.modules) if "iris.voice" in k}

    try:
        with pytest.raises(ImportError, match=r"pipecat"):
            importlib.import_module("iris.voice.pipecat_tts")
    finally:
        sys.modules.update(saved_pipecat)
        sys.modules.update(saved_voice)
