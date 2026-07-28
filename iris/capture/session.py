"""Dual-channel STT capture session for one call — ti-rnlqo.3.2."""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from iris.audio.streaming import StreamingTranscriber
from iris.capture.asr_gate import is_hallucinated_segment
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
        on_far_lost: Callable[[str], None] | None = None,
    ) -> None:
        self._session_id = session_id
        self._transcript_store = transcript_store
        self._processor = processor
        self._store = store
        self._on_fact = on_fact
        self._on_action_item = on_action_item
        self._on_far_lost = on_far_lost
        self._far_watchdog_stop = threading.Event()
        self._far_lost_reported = False
        self._start_time: float | None = None

        self._op = StreamingTranscriber(
            self._utterance_callback,
            label="operator",
        )
        self._far = StreamingTranscriber(
            self._utterance_callback,
            label="far",
            backend="pw",
            on_stream_end=self._on_far_stream_end,
        )

    def _utterance_callback(self, text: str, speaker: str) -> None:
        t0 = self._start_time
        offset_s = time.time() - t0 if t0 is not None else 0.0
        src = self._op if speaker == self._op.label else self._far
        self._on_utterance(
            text, speaker, offset_s,
            no_speech_prob=src.last_no_speech_prob,
            avg_logprob=src.last_avg_logprob,
        )

    def _on_utterance(
        self,
        text: str,
        speaker: str,
        offset_s: float,
        *,
        no_speech_prob: float | None = None,
        avg_logprob: float | None = None,
    ) -> None:
        # The only live trace that capture is hearing anything — without it a
        # silent far channel is indistinguishable from a broken one (ti-wunrs).
        _log.info(
            "CaptureSession %s: [%s] %.80s", self._session_id, speaker, text
        )
        try:
            turn_id = self._transcript_store.append(text, speaker, offset_s)
            if no_speech_prob is not None and is_hallucinated_segment(
                text, no_speech_prob, avg_logprob
            ):
                _log.info(
                    "CaptureSession %s: [%s] gated ASR hallucination "
                    "(no_speech_prob=%.2f avg_logprob=%s): %.80s",
                    self._session_id, speaker, no_speech_prob, avg_logprob, text,
                )
                return
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
        from iris.audio.endpoint import discover_sco_nodes

        _sink, downlink = discover_sco_nodes()
        if downlink:
            self._far.source = downlink
            self._far.start()
            # BINDING IS NOT TRUSTED: PipeWire silently reroutes a capture to
            # the default mic when its target is missing or disappears (e.g.
            # the operator moves the call off the Bluetooth route), which
            # relabels the operator's room as "far" — attribution fiction and
            # a hole under the channel-identity trust model (ADR-0002).
            # Verify the actual link and keep watching it for the whole call.
            self._far_watchdog_stop.clear()
            threading.Thread(
                target=self._far_binding_watchdog,
                name=f"far-watchdog-{self._session_id}",
                daemon=True,
            ).start()
        else:
            _log.warning(
                "CaptureSession %s: no SCO downlink found — far-party capture "
                "disabled (is an HFP call connected on the dongle?)",
                self._session_id,
            )

    def _far_binding_watchdog(self) -> None:
        """Verify the far stream stays bound to the SCO downlink; kill it loudly if not.

        First check is delayed so the link has time to appear; then re-checked
        every 2s. Transcribing from the wrong source is worse than silence, so
        a bad binding stops the channel rather than limping on.
        """
        interval_s = 2.0
        deadline_first = time.time() + 4.0
        while not self._far_watchdog_stop.wait(interval_s):
            ok, detail = self._far.verify_target_bound()
            if ok:
                continue
            if time.time() < deadline_first and "no incoming links" in detail:
                continue  # link may still be forming right after start
            self._report_far_lost(detail)
            return

    def _on_far_stream_end(self, label: str) -> None:
        self._report_far_lost("far pipeline exited unexpectedly")

    def _report_far_lost(self, reason: str) -> None:
        if self._far_lost_reported:
            return
        self._far_lost_reported = True
        self._far_watchdog_stop.set()
        _log.warning(
            "CaptureSession %s: FAR CHANNEL LOST — stopping far capture: %s",
            self._session_id, reason,
        )
        try:
            self._far.stop()
        except Exception:
            _log.exception("far stop failed")
        if self._on_far_lost is not None:
            try:
                self._on_far_lost(reason)
            except Exception:
                _log.exception("on_far_lost callback failed")

    def stop(self) -> None:
        self._far_watchdog_stop.set()
        self._op.stop()
        self._far.stop()
        for tr in (self._op, self._far):
            reader = getattr(tr, "_reader", None)
            if reader is not None and reader.is_alive():
                reader.join(timeout=5.0)
