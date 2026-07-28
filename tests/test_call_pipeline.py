"""Integration tests for iris/voice/call_pipeline.py (ti-eq6d.3.1).

CallPipeline + AudioEndpointSource/Sink using LoopbackAudioEndpoint as the
hardware-free seam.

pipecat-ai is not installed in the test environment — a minimal stub is
injected into sys.modules.  A LoopbackAudioEndpoint stub is also defined
here (the real one lives in ti-wth9; once that lands, replace _LoopbackStub
with the real import).

All tests that exercise the full pipeline depend on ti-eq6d.1 (IrisSTTService),
ti-eq6d.2 (IrisTTSService), ti-jbm6.1 (BrainLLMService), and ti-wth9
(LoopbackAudioEndpoint) being merged — they will remain failing until then.
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
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Pipecat stubs — comprehensive set for the pipeline infrastructure
# ---------------------------------------------------------------------------

def _install_pipecat_stubs() -> None:
    """Inject minimal pipecat stubs into sys.modules (idempotent)."""
    if "pipecat.pipeline.pipeline" in sys.modules:
        return

    # --- Frames ---

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
    class TranscriptionFrame(Frame):
        text: str
        user_id: str = ""
        timestamp: str = ""

    @dataclass
    class VADUserStartedSpeakingFrame(Frame):
        start_secs: float = 0.0

    @dataclass
    class TTSStartedFrame(Frame):
        context_id: str | None = None

    @dataclass
    class TTSStoppedFrame(Frame):
        context_id: str | None = None

    @dataclass
    class LLMFullResponseEndFrame(Frame):
        pass

    @dataclass
    class LLMFullResponseStartFrame(Frame):
        pass

    @dataclass
    class CancelFrame(Frame):
        pass

    @dataclass
    class EndFrame(Frame):
        pass

    frames_mod = types.ModuleType("pipecat.frames.frames")
    for cls in [
        Frame, AudioRawFrame, TTSAudioRawFrame, TranscriptionFrame,
        VADUserStartedSpeakingFrame, TTSStartedFrame, TTSStoppedFrame,
        LLMFullResponseEndFrame, LLMFullResponseStartFrame, CancelFrame, EndFrame,
    ]:
        setattr(frames_mod, cls.__name__, cls)

    # --- Services ---

    class AIService:
        def __init__(self, **kwargs):
            pass

    class STTService(AIService):
        async def run_stt(self, audio: bytes):
            return; yield

    class TTSService(AIService):
        async def run_tts(self, text: str, context_id: str = ""):
            return; yield

    class LLMService(AIService):
        async def process_frame(self, frame, direction):
            pass

    stt_mod = types.ModuleType("pipecat.services.stt_service")
    stt_mod.STTService = STTService
    tts_mod = types.ModuleType("pipecat.services.tts_service")
    tts_mod.TTSService = TTSService
    ai_mod = types.ModuleType("pipecat.services.ai_service")
    ai_mod.AIService = AIService
    llm_mod = types.ModuleType("pipecat.services.llm_service")
    llm_mod.LLMService = LLMService
    llm_mod.LLMTextFrame = TranscriptionFrame  # alias for simplicity

    # --- Processors ---

    class FrameDirection:
        DOWNSTREAM = "downstream"
        UPSTREAM = "upstream"

    class FrameProcessor:
        def __init__(self, **kwargs):
            pass

        async def process_frame(self, frame, direction):
            pass

        async def push_frame(self, frame, direction=None):
            pass

    fp_mod = types.ModuleType("pipecat.processors.frame_processor")
    fp_mod.FrameProcessor = FrameProcessor
    fp_mod.FrameDirection = FrameDirection

    # --- Pipeline ---

    class Pipeline:
        def __init__(self, processors, **kwargs):
            self.processors = processors

    class PipelineTask:
        def __init__(self, pipeline, **kwargs):
            self.pipeline = pipeline
            self._cancelled = False

        def cancel(self):
            self._cancelled = True

    class PipelineRunner:
        async def run(self, task):
            pass

    pipeline_pipeline_mod = types.ModuleType("pipecat.pipeline.pipeline")
    pipeline_pipeline_mod.Pipeline = Pipeline
    pipeline_task_mod = types.ModuleType("pipecat.pipeline.task")
    pipeline_task_mod.PipelineTask = PipelineTask
    pipeline_runner_mod = types.ModuleType("pipecat.pipeline.runner")
    pipeline_runner_mod.PipelineRunner = PipelineRunner

    # --- VAD ---

    class SileroVADAnalyzer:
        def __init__(self, **kwargs):
            pass

    vad_mod = types.ModuleType("pipecat.vad.silero")
    vad_mod.SileroVADAnalyzer = SileroVADAnalyzer
    vad_pkg = types.ModuleType("pipecat.vad")

    sys.modules.update({
        "pipecat": types.ModuleType("pipecat"),
        "pipecat.frames": types.ModuleType("pipecat.frames"),
        "pipecat.frames.frames": frames_mod,
        "pipecat.services": types.ModuleType("pipecat.services"),
        "pipecat.services.stt_service": stt_mod,
        "pipecat.services.tts_service": tts_mod,
        "pipecat.services.ai_service": ai_mod,
        "pipecat.services.llm_service": llm_mod,
        "pipecat.processors": types.ModuleType("pipecat.processors"),
        "pipecat.processors.frame_processor": fp_mod,
        "pipecat.pipeline": types.ModuleType("pipecat.pipeline"),
        "pipecat.pipeline.pipeline": pipeline_pipeline_mod,
        "pipecat.pipeline.task": pipeline_task_mod,
        "pipecat.pipeline.runner": pipeline_runner_mod,
        "pipecat.vad": vad_pkg,
        "pipecat.vad.silero": vad_mod,
    })


_install_pipecat_stubs()

from iris.voice.call_pipeline import CallPipeline

# Grab stub frame classes for use in tests
_frames_mod = sys.modules["pipecat.frames.frames"]
VADUserStartedSpeakingFrame = _frames_mod.VADUserStartedSpeakingFrame
TTSStartedFrame = _frames_mod.TTSStartedFrame
TTSStoppedFrame = _frames_mod.TTSStoppedFrame
LLMFullResponseEndFrame = _frames_mod.LLMFullResponseEndFrame
_FrameProcessor = sys.modules["pipecat.processors.frame_processor"].FrameProcessor
_FrameDirection = sys.modules["pipecat.processors.frame_processor"].FrameDirection


# ---------------------------------------------------------------------------
# LoopbackAudioEndpoint stub (replace with real import once ti-wth9 lands)
# ---------------------------------------------------------------------------

class _LoopbackStub:
    """Minimal AudioEndpoint stub — no hardware, no subprocess."""

    name = "loopback-stub"
    far_source = None
    far_backend = "pulse"

    def __init__(self):
        self.played: list[str] = []

    def capture(self, seconds: float) -> str:
        """Return a tiny silence WAV."""
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        n_frames = int(16000 * max(seconds, 0.01))
        with wave.open(path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(b"\x00\x00" * n_frames)
        return path

    def playback(self, wav_path: str) -> None:
        self.played.append(wav_path)

    def start_capture(self):
        class _Rec:
            def stop(self_):
                return self.capture(0.05)
        return _Rec()

    def start_playback(self, wav_path: str):
        class _Play:
            def wait(self_): pass
            def stop(self_): pass
        self.played.append(wav_path)
        return _Play()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_brain() -> MagicMock:
    brain = MagicMock()
    brain.respond_stream.return_value = iter([])
    return brain


def _make_pipeline(*, emit=None, brain=None, endpoint=None):
    """Create a CallPipeline with a mock pipecat runner that completes immediately."""
    emit = emit or (lambda e: None)
    brain = brain or _mock_brain()
    endpoint = endpoint or _LoopbackStub()

    runner_cls = sys.modules["pipecat.pipeline.runner"].PipelineRunner

    async def _instant_run(self, task):
        pass  # pipeline completes immediately

    with patch.object(runner_cls, "run", new=_instant_run):
        cp = CallPipeline()
        cp.start(brain=brain, endpoint=endpoint, emit=emit)

    return cp


# ---------------------------------------------------------------------------
# 1. start() completes end-to-end without error
# ---------------------------------------------------------------------------

def test_start_with_loopback_completes_without_error():
    """CallPipeline.start() with LoopbackAudioEndpoint + mock Brain raises no exception."""
    events: list = []
    runner_cls = sys.modules["pipecat.pipeline.runner"].PipelineRunner

    async def _instant_run(self, task):
        pass

    with patch.object(runner_cls, "run", new=_instant_run):
        cp = CallPipeline()
        cp.start(brain=_mock_brain(), endpoint=_LoopbackStub(), emit=events.append)

    # Reaching here without exception is the assertion.


# ---------------------------------------------------------------------------
# 2. stop() cancels cleanly; no orphan threads
# ---------------------------------------------------------------------------

def test_stop_cancels_pipeline_task_cleanly():
    """stop() cancels the pipecat task and returns; no daemon threads linger."""
    threads_before = {t.ident for t in threading.enumerate()}

    runner_cls = sys.modules["pipecat.pipeline.runner"].PipelineRunner
    started = threading.Event()
    async def _blocking_run(self, task):
        started.set()
        await asyncio.sleep(0)  # yield control once
        # In a real pipeline, task.cancel() would break out of run().
        # Here we just wait for the stop signal to be sent, then return.

    with patch.object(runner_cls, "run", new=_blocking_run):
        cp = CallPipeline()

        def _start():
            cp.start(brain=_mock_brain(), endpoint=_LoopbackStub(), emit=lambda e: None)

        t = threading.Thread(target=_start, daemon=True)
        t.start()
        started.wait(timeout=2)
        cp.stop()
        t.join(timeout=2)

    assert not t.is_alive(), "start() thread did not exit after stop()"

    # No new non-daemon threads should remain
    threads_after = {t.ident for t in threading.enumerate() if not t.daemon}
    threads_before_non_daemon = {
        t.ident for t in threading.enumerate() if not t.daemon and t.ident in threads_before
    }
    assert not (threads_after - threads_before_non_daemon - {threading.main_thread().ident}), \
        "Orphan non-daemon threads left after stop()"


# ---------------------------------------------------------------------------
# 3. emit() receives ('pipeline_start',) and ('pipeline_stop',)
# ---------------------------------------------------------------------------

def test_emit_receives_pipeline_start_and_stop():
    """emit() is called with ('pipeline_start',) before the pipeline runs and
    ('pipeline_stop',) after it stops."""
    events: list = []
    runner_cls = sys.modules["pipecat.pipeline.runner"].PipelineRunner

    async def _instant_run(self, task):
        pass

    with patch.object(runner_cls, "run", new=_instant_run):
        cp = CallPipeline()
        cp.start(brain=_mock_brain(), endpoint=_LoopbackStub(), emit=events.append)

    assert ("pipeline_start",) in events, f"pipeline_start not in events: {events}"
    assert ("pipeline_stop",) in events, f"pipeline_stop not in events: {events}"

    start_idx = events.index(("pipeline_start",))
    stop_idx = events.index(("pipeline_stop",))
    assert start_idx < stop_idx, "pipeline_start must precede pipeline_stop"


# ---------------------------------------------------------------------------
# 4. Second start() raises RuntimeError if already running
# ---------------------------------------------------------------------------

def test_second_start_raises_runtime_error():
    """Calling start() while the pipeline is already running raises RuntimeError."""
    runner_cls = sys.modules["pipecat.pipeline.runner"].PipelineRunner
    running = threading.Event()
    allow_exit = threading.Event()

    async def _hold_run(self, task):
        running.set()
        # Block until the test allows exit
        while not allow_exit.is_set():
            await asyncio.sleep(0.005)

    cp = CallPipeline()

    def _start():
        with patch.object(runner_cls, "run", new=_hold_run):
            cp.start(brain=_mock_brain(), endpoint=_LoopbackStub(), emit=lambda e: None)

    t = threading.Thread(target=_start, daemon=True)
    t.start()
    running.wait(timeout=2)

    try:
        with pytest.raises(RuntimeError):
            cp.start(brain=_mock_brain(), endpoint=_LoopbackStub(), emit=lambda e: None)
    finally:
        allow_exit.set()
        t.join(timeout=2)


# ---------------------------------------------------------------------------
# 5. emit() receives ('state', 'listening') on VADUserStartedSpeakingFrame
#    — NOT on Pipeline.start()
# ---------------------------------------------------------------------------

def test_emit_state_listening_on_vad_user_started_speaking():
    """('state', 'listening') fires when VADUserStartedSpeakingFrame arrives,
    not at Pipeline.start() time."""
    events: list = []
    captured_processors: list = []
    Pipeline_cls = sys.modules["pipecat.pipeline.pipeline"].Pipeline
    runner_cls = sys.modules["pipecat.pipeline.runner"].PipelineRunner

    real_pipeline_init = Pipeline_cls.__init__

    def _capturing_init(self, processors, **kw):
        captured_processors.extend(processors)
        real_pipeline_init(self, processors, **kw)

    async def _instant_run(self, task):
        pass

    with patch.object(Pipeline_cls, "__init__", new=_capturing_init), \
         patch.object(runner_cls, "run", new=_instant_run):
        cp = CallPipeline()
        cp.start(brain=_mock_brain(), endpoint=_LoopbackStub(), emit=events.append)

    # ('state', 'listening') must NOT be in events yet (pipeline hasn't processed frames)
    assert ("state", "listening") not in events, (
        "('state', 'listening') was emitted at pipeline start — it should fire only "
        "on VADUserStartedSpeakingFrame"
    )

    # Find the state observer processor and feed it a VAD frame
    observer = _find_state_observer(captured_processors)
    assert observer is not None, (
        "No state-observer FrameProcessor found in the pipeline — "
        "CallPipeline must add a frame processor that maps VAD frames to emit() calls"
    )

    asyncio.run(observer.process_frame(
        VADUserStartedSpeakingFrame(), _FrameDirection.DOWNSTREAM
    ))

    assert ("state", "listening") in events, (
        f"Expected ('state', 'listening') after VADUserStartedSpeakingFrame; events={events}"
    )


# ---------------------------------------------------------------------------
# 6. emit() receives ('state', 'idle') on TTSStoppedFrame and LLMFullResponseEndFrame
# ---------------------------------------------------------------------------

def test_emit_state_idle_on_tts_stopped_frame():
    """('state', 'idle') fires on TTSStoppedFrame."""
    events: list = []
    observer = _make_state_observer_from_pipeline(events)

    asyncio.run(observer.process_frame(TTSStoppedFrame(), _FrameDirection.DOWNSTREAM))

    assert ("state", "idle") in events, (
        f"Expected ('state', 'idle') after TTSStoppedFrame; events={events}"
    )


def test_emit_state_idle_on_llm_full_response_end_frame():
    """('state', 'idle') fires on LLMFullResponseEndFrame."""
    events: list = []
    observer = _make_state_observer_from_pipeline(events)

    asyncio.run(observer.process_frame(LLMFullResponseEndFrame(), _FrameDirection.DOWNSTREAM))

    assert ("state", "idle") in events, (
        f"Expected ('state', 'idle') after LLMFullResponseEndFrame; events={events}"
    )


def test_emit_state_speaking_on_tts_started_frame():
    """('state', 'speaking') fires on TTSStartedFrame."""
    events: list = []
    observer = _make_state_observer_from_pipeline(events)

    asyncio.run(observer.process_frame(TTSStartedFrame(), _FrameDirection.DOWNSTREAM))

    assert ("state", "speaking") in events, (
        f"Expected ('state', 'speaking') after TTSStartedFrame; events={events}"
    )


# ---------------------------------------------------------------------------
# 7. ImportError when pipecat-ai absent
# ---------------------------------------------------------------------------

def test_import_error_without_pipecat():
    """Importing iris.voice.call_pipeline without pipecat-ai raises ImportError
    naming 'pipecat'."""
    import importlib

    saved_pipecat = {k: sys.modules.pop(k) for k in list(sys.modules) if k.startswith("pipecat")}
    saved_voice = {k: sys.modules.pop(k) for k in list(sys.modules) if "iris.voice" in k}

    try:
        with pytest.raises(ImportError, match=r"pipecat"):
            importlib.import_module("iris.voice.call_pipeline")
    finally:
        sys.modules.update(saved_pipecat)
        sys.modules.update(saved_voice)


# ---------------------------------------------------------------------------
# Internal helpers for tests 5 & 6
# ---------------------------------------------------------------------------

def _find_state_observer(processors: list):
    """Return the first FrameProcessor in the list that has an _emit attribute
    (the state observer CallPipeline installs to translate frames → emit() calls)."""
    for p in processors:
        if hasattr(p, "_emit") and callable(getattr(p, "_emit", None)):
            return p
    return None


def _make_state_observer_from_pipeline(events: list):
    """Start a CallPipeline, capture the state-observer processor, return it."""
    captured: list = []
    Pipeline_cls = sys.modules["pipecat.pipeline.pipeline"].Pipeline
    runner_cls = sys.modules["pipecat.pipeline.runner"].PipelineRunner
    real_init = Pipeline_cls.__init__

    def _capturing_init(self, processors, **kw):
        captured.extend(processors)
        real_init(self, processors, **kw)

    async def _instant_run(self, task):
        pass

    with patch.object(Pipeline_cls, "__init__", new=_capturing_init), \
         patch.object(runner_cls, "run", new=_instant_run):
        cp = CallPipeline()
        cp.start(brain=_mock_brain(), endpoint=_LoopbackStub(), emit=events.append)

    observer = _find_state_observer(captured)
    assert observer is not None, (
        "No state-observer FrameProcessor found — CallPipeline must add one "
        "with an _emit attribute for tests 5/6 to work"
    )
    return observer
