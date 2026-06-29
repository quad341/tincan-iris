"""Unit tests for iris/voice/pipecat_stt.py (ti-eq6d.1.1).

IrisSTTService wraps FasterWhisperSTT as a Pipecat STTService.

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
# Pipecat stubs — installed before importing the module under test
# ---------------------------------------------------------------------------

def _make_pipecat_stub_frames():
    """Minimal pipecat frame classes."""

    class Frame:
        pass

    @dataclass
    class AudioRawFrame(Frame):
        audio: bytes
        sample_rate: int
        num_channels: int

    @dataclass
    class TranscriptionFrame(Frame):
        text: str
        user_id: str = ""
        timestamp: str = ""

    return Frame, AudioRawFrame, TranscriptionFrame


def _install_pipecat_stubs() -> None:
    """Inject minimal pipecat stubs into sys.modules (idempotent)."""
    if "pipecat.services.stt_service" in sys.modules:
        return

    Frame, AudioRawFrame, TranscriptionFrame = _make_pipecat_stub_frames()

    class STTService:
        def __init__(self, **kwargs):
            pass

        async def run_stt(self, audio: bytes):
            return
            yield  # noqa — makes it an async generator

    pipecat = types.ModuleType("pipecat")
    frames_pkg = types.ModuleType("pipecat.frames")
    frames_mod = types.ModuleType("pipecat.frames.frames")
    frames_mod.Frame = Frame
    frames_mod.AudioRawFrame = AudioRawFrame
    frames_mod.TranscriptionFrame = TranscriptionFrame

    services_pkg = types.ModuleType("pipecat.services")
    stt_mod = types.ModuleType("pipecat.services.stt_service")
    stt_mod.STTService = STTService
    ai_mod = types.ModuleType("pipecat.services.ai_service")

    class AIService:
        def __init__(self, **kwargs):
            pass

    ai_mod.AIService = AIService

    sys.modules.update({
        "pipecat": pipecat,
        "pipecat.frames": frames_pkg,
        "pipecat.frames.frames": frames_mod,
        "pipecat.services": services_pkg,
        "pipecat.services.stt_service": stt_mod,
        "pipecat.services.ai_service": ai_mod,
    })


_install_pipecat_stubs()

from iris.voice.pipecat_stt import IrisSTTService  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DUMMY_AUDIO = b"\x00\x00" * 3200  # 100 ms of silence (16 kHz 16-bit mono)


def _make_wav_bytes(rate: int = 16000, duration_ms: int = 50) -> bytes:
    """Build a valid WAV byte string at the given rate (silence)."""
    n_frames = int(rate * duration_ms / 1000)
    buf = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    buf.close()
    try:
        with wave.open(buf.name, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(rate)
            wf.writeframes(b"\x00\x00" * n_frames)
        with open(buf.name, "rb") as f:
            return f.read()
    finally:
        os.unlink(buf.name)


async def _collect(gen) -> list:
    """Drain an async generator into a list."""
    return [f async for f in gen]


def _mock_stt(*, language: str = "en", return_value: str = "hello") -> MagicMock:
    mock = MagicMock()
    mock.language = language
    mock.transcribe.return_value = return_value
    return mock


# ---------------------------------------------------------------------------
# 1. Non-empty audio → TranscriptionFrame
# ---------------------------------------------------------------------------

def test_run_stt_returns_transcription_frame_for_non_empty_audio():
    """Non-empty Whisper output yields exactly one TranscriptionFrame."""
    stt = _mock_stt(return_value="hello there")
    service = IrisSTTService(stt)
    frames = asyncio.run(_collect(service.run_stt(DUMMY_AUDIO)))

    assert len(frames) == 1
    assert frames[0].text == "hello there"


# ---------------------------------------------------------------------------
# 2. Empty transcript → nothing yielded
# ---------------------------------------------------------------------------

def test_run_stt_with_empty_transcript_yields_nothing():
    """Whisper returning empty string produces no frame (silence guard)."""
    stt = _mock_stt(return_value="")
    service = IrisSTTService(stt)
    frames = asyncio.run(_collect(service.run_stt(DUMMY_AUDIO)))

    assert frames == []


# ---------------------------------------------------------------------------
# 3. Executor path exercised
# ---------------------------------------------------------------------------

def test_run_stt_does_not_block_event_loop():
    """transcribe() must run in a ThreadPoolExecutor thread, not the event-loop thread."""
    caller_threads: list[threading.Thread] = []

    def _transcribe(wav_path: str) -> str:
        caller_threads.append(threading.current_thread())
        return "spoken words"

    stt = _mock_stt()
    stt.transcribe.side_effect = _transcribe
    service = IrisSTTService(stt)
    asyncio.run(_collect(service.run_stt(DUMMY_AUDIO)))

    assert caller_threads, "transcribe() was never called"
    assert caller_threads[0] is not threading.main_thread(), (
        "transcribe() ran on the main thread — run_in_executor was not used"
    )


# ---------------------------------------------------------------------------
# 4. set_language_hint passes lang to STT
# ---------------------------------------------------------------------------

def test_set_language_hint_passes_lang_to_stt():
    """set_language_hint() updates .language on the underlying STT object."""
    stt = _mock_stt(language="en")
    service = IrisSTTService(stt)
    service.set_language_hint("es")

    assert stt.language == "es"


def test_set_language_hint_none_resets_language():
    """set_language_hint(None) resets to a default or None (no crash)."""
    stt = _mock_stt(language="es")
    service = IrisSTTService(stt)
    service.set_language_hint(None)  # must not raise


# ---------------------------------------------------------------------------
# 5. Temp WAV cleaned up even when transcribe() raises
# ---------------------------------------------------------------------------

def test_temp_wav_cleaned_up_on_transcribe_error():
    """Temp WAV is deleted via try/finally even when transcribe() raises."""
    wav_path_seen: list[str] = []

    def _failing_transcribe(wav_path: str) -> str:
        wav_path_seen.append(wav_path)
        raise RuntimeError("whisper exploded")

    stt = _mock_stt()
    stt.transcribe.side_effect = _failing_transcribe
    service = IrisSTTService(stt)

    with pytest.raises(RuntimeError, match="whisper exploded"):
        asyncio.run(_collect(service.run_stt(DUMMY_AUDIO)))

    assert wav_path_seen, "transcribe() was not called — test is inconclusive"
    for path in wav_path_seen:
        assert not os.path.exists(path), f"temp WAV not cleaned up after error: {path}"


# ---------------------------------------------------------------------------
# 6. ImportError when pipecat-ai absent
# ---------------------------------------------------------------------------

def test_import_error_without_pipecat():
    """Importing iris.voice.pipecat_stt without pipecat-ai installed raises
    ImportError with a message that names 'pipecat'."""
    import importlib

    # Save current module state
    saved_pipecat = {k: sys.modules.pop(k) for k in list(sys.modules) if k.startswith("pipecat")}
    saved_voice = {k: sys.modules.pop(k) for k in list(sys.modules) if "iris.voice" in k}

    try:
        with pytest.raises(ImportError, match=r"pipecat"):
            importlib.import_module("iris.voice.pipecat_stt")
    finally:
        sys.modules.update(saved_pipecat)
        sys.modules.update(saved_voice)
