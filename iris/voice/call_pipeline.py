"""CallPipeline + AudioEndpointSource/Sink — Pipecat voice pipeline for phone calls."""
from __future__ import annotations

import asyncio
import logging as _logging
import threading
from collections.abc import Callable

try:
    from pipecat.frames.frames import (
        LLMFullResponseEndFrame,
        TTSStartedFrame,
        TTSStoppedFrame,
        VADUserStartedSpeakingFrame,
    )
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.runner import PipelineRunner
    from pipecat.pipeline.task import PipelineTask
    from pipecat.processors.frame_processor import FrameProcessor
except ImportError as exc:
    raise ImportError(
        "pipecat-ai is required for CallPipeline — "
        "install pipecat-ai or run iris without the Pipecat voice pipeline."
    ) from exc

_logging.getLogger("pipecat").setLevel(_logging.WARNING)


class _StateObserver(FrameProcessor):
    """Translates pipeline frames to emit() state events for the console status strip."""

    def __init__(self, emit: Callable) -> None:
        super().__init__()
        self._emit = emit

    async def process_frame(self, frame, direction) -> None:
        if isinstance(frame, VADUserStartedSpeakingFrame):
            self._emit(("state", "listening"))
        elif isinstance(frame, TTSStartedFrame):
            self._emit(("state", "speaking"))
        elif isinstance(frame, (TTSStoppedFrame, LLMFullResponseEndFrame)):
            self._emit(("state", "idle"))
        await self.push_frame(frame, direction)


class CallPipeline:
    """Assembles and runs the Pipecat voice pipeline for a live phone call.

    One instance per call. start() runs the event loop in the calling thread
    (blocks until the pipeline finishes). stop() cancels the pipeline task from
    any thread. Raises RuntimeError if start() is called while already running.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._running = False
        self._task: PipelineTask | None = None

    def start(self, brain, endpoint, emit: Callable) -> None:
        """Assemble and run the pipeline. Emits ('pipeline_start',) before running
        and ('pipeline_stop',) after. Blocks until the pipeline finishes or stop()
        is called. Raises RuntimeError if already running.
        """
        with self._lock:
            if self._running:
                raise RuntimeError("CallPipeline is already running — call stop() first")
            self._running = True

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        emit(("pipeline_start",))
        try:
            loop.run_until_complete(self._run(brain, endpoint, emit))
        finally:
            loop.close()
            asyncio.set_event_loop(None)
            with self._lock:
                self._task = None
                self._running = False
            emit(("pipeline_stop",))

    async def _run(self, brain, endpoint, emit: Callable) -> None:
        observer = _StateObserver(emit)
        pipeline = Pipeline([observer])
        task = PipelineTask(pipeline)

        with self._lock:
            self._task = task

        runner = PipelineRunner()
        await runner.run(task)

    def stop(self) -> None:
        """Cancel the running pipeline task (safe to call from any thread)."""
        with self._lock:
            task = self._task
        if task is not None:
            task.cancel()
