"""Dual-channel STT capture session for one call — ti-rnlqo.3.2."""
from __future__ import annotations

import logging
import time
from typing import Callable

from iris.audio.streaming import StreamingTranscriber
from iris.capture.processor import L1CaptureProcessor
from iris.capture.schemas import ActionItem, CapturedFact
from iris.capture.store import CallCardStore
from iris.capture.transcript import TranscriptStore

_log = logging.getLogger(__name__)


class CaptureSession:
    """Dual-channel audio capture for a single call.

    Wires two StreamingTranscribers (operator mic + far SCO) through
    L1CaptureProcessor and persists results to CallCardStore.
    """

    def __init__(
        self,
        *,
        session_id: str,
        transcript_store: TranscriptStore,
        processor: L1CaptureProcessor,
        store: CallCardStore,
        on_fact: Callable[[CapturedFact], None],
        on_action_item: Callable[[ActionItem], None],
    ) -> None:
        self._session_id = session_id
        self._transcript_store = transcript_store
        self._processor = processor
        self._store = store
        self._on_fact = on_fact
        self._on_action_item = on_action_item
        self._start_time: float | None = None

        self._op = StreamingTranscriber(
            self._utterance_callback,
            label="operator",
        )
        self._far = StreamingTranscriber(
            self._utterance_callback,
            label="far",
            backend="pw",
        )

    def _utterance_callback(self, text: str, speaker: str) -> None:
        t0 = self._start_time
        offset_s = time.time() - t0 if t0 is not None else 0.0
        self._on_utterance(text, speaker, offset_s)

    def _on_utterance(self, text: str, speaker: str, offset_s: float) -> None:
        try:
            turn_id = self._transcript_store.append(text, speaker, offset_s)
            results = self._processor.process(text, speaker, turn_id, offset_s)
            for result in results:
                if isinstance(result, CapturedFact):
                    self._store.add_fact(result)
                    self._on_fact(result)
                elif isinstance(result, ActionItem):
                    self._store.add_action_item(result)
                    self._on_action_item(result)
        except Exception:
            _log.exception(
                "CaptureSession._on_utterance error (session=%s speaker=%s)",
                self._session_id,
                speaker,
            )

    def start(self) -> None:
        """Start both channels immediately. Used by callers with no consent gate to honor."""
        self.start_operator()
        self.start_far()

    def start_operator(self) -> None:
        self._processor.session_id = self._session_id
        self._start_time = time.time()
        # Operator channel captures the default source. With ambient AEC that is
        # `iris_aec_src` (the echo-cancelled mic); without it, the raw mic — either
        # way, the operator's own voice.
        self._op.start()

    def start_far(self) -> None:
        # The far channel MUST target the live SCO downlink (bluez_input). The
        # default source is the operator's mic, so a bare default capture would
        # double-record the operator instead of the far party. The SCO nodes only
        # exist while a call is connected, so discover them here at start time.
        from iris.audio.endpoint import discover_sco_nodes  # noqa: PLC0415

        _sink, downlink = discover_sco_nodes()
        if downlink:
            self._far.source = downlink
            self._far.start()
        else:
            _log.warning(
                "CaptureSession %s: no SCO downlink found — far-party capture "
                "disabled (is an HFP call connected on the dongle?)",
                self._session_id,
            )

    def stop(self) -> None:
        self._op.stop()
        self._far.stop()
        for tr in (self._op, self._far):
            reader = getattr(tr, "_reader", None)
            if reader is not None and reader.is_alive():
                reader.join(timeout=5.0)
