"""The local voice loop's conductor — UI-agnostic state + pipeline.

Owns the capture -> STT -> brain -> TTS -> playback pipeline and the session
state, but knows nothing about curses. Any front-end (the console, a future web
UI, tests) drives it via these methods and consumes ``emit``ted events. The split
keeps the pipeline testable without a terminal or real audio.

Interruption (barge-in): ``interrupt()`` cuts playback instantly and cancels the
in-flight turn. A turn already inside the LLM call still finishes in its worker
thread, but its result is dropped — true mid-LLM cancel is a later optimization.
"""
from __future__ import annotations

import threading
import time
from enum import Enum

from ..trust import TrustMode


class State(str, Enum):
    IDLE = "idle"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"
    THINKING = "thinking"
    SPEAKING = "speaking"


class Conductor:
    """Drives one local voice turn at a time. ``emit`` is a thread-safe sink for
    event tuples; the front-end consumes them to render."""

    CADENCE_SLOW: float = 0.7   # speed multiplier for re-ask turns (will move to cfg.cadence_slow when ti-140k lands)
    CADENCE_NORMAL: float = 1.0

    def __init__(self, stt, brain, tts, mic, emit, *, pick=None) -> None:
        self.stt = stt
        self.brain = brain
        self.tts = tts
        self.mic = mic
        self.emit = emit                       # callable(event: tuple) — thread-safe
        self.pick = pick or (lambda: "one sec")
        self.state = State.IDLE
        self.muted = False
        self._trust: TrustMode = TrustMode.NONE  # current trust level (NONE/LOCAL/BOTH)
        self._armed: bool = False               # True once arm() is called
        self._rec = None
        self._play = None
        self._cancel = threading.Event()

    @property
    def trust_state(self) -> TrustMode:
        """Current trust level: NONE / LOCAL / BOTH."""
        return self._trust

    @property
    def op_trust(self) -> TrustMode:
        """Operator trust: FULL when armed (LOCAL or BOTH), DEMO otherwise."""
        return TrustMode.FULL if self._trust in (TrustMode.LOCAL, TrustMode.BOTH) else TrustMode.DEMO

    @property
    def far_trust(self) -> TrustMode:
        """Far-party trust derived from current level (BOTH → FULL; anything else → NONE/DEMO)."""
        return TrustMode.BOTH if self._trust is TrustMode.BOTH else TrustMode.NONE

    @property
    def speaking(self) -> bool:
        """True while Iris is generating or playing output (THINKING or SPEAKING).

        Used as a speaking gate: while True, the operator mic stream is suppressed so
        Iris does not transcribe her own voice coming out of the speakers."""
        return self.state in (State.THINKING, State.SPEAKING)

    def _set_state(self, s: State) -> None:
        self.state = s
        self.emit(("state", s))

    def start_recording(self) -> None:
        if self.state is not State.IDLE:
            return
        self._cancel.clear()
        self._rec = self.mic.start_capture()
        self._set_state(State.RECORDING)

    def stop_and_respond(self) -> None:
        """Finish recording and run the rest of the pipeline. Blocking — call it
        from a worker thread so the UI stays responsive (and ``interrupt`` works)."""
        if self.state is not State.RECORDING or self._rec is None:
            return
        wav = self._rec.stop()
        self._rec = None

        self._set_state(State.TRANSCRIBING)
        t0 = time.monotonic()
        try:
            text = self.stt.transcribe(wav)
        except Exception as exc:  # noqa: BLE001 — surface, return to idle
            self.emit(("error", f"stt: {exc}"))
            self._set_state(State.IDLE)
            return
        stt_ms = (time.monotonic() - t0) * 1000
        if self._cancel.is_set():
            self._set_state(State.IDLE)
            return
        self.emit(("transcript", text, stt_ms))
        if not text:
            self._set_state(State.IDLE)
            return
        self.respond_to(text)

    # --- trust arm/grant cycle (ti-qt1i.1.2) ---

    def arm(self) -> None:
        """Enable the grant cycle.  Does not elevate far party."""
        if not self._armed:
            self._armed = True
            self.emit(("armed", True))

    def disarm(self) -> None:
        """Disable grant cycle and revoke any far-party elevation."""
        self._armed = False
        self._trust = TrustMode.NONE
        self.emit(("armed", False))
        self.emit(("far_trust", self.far_trust))

    _GRANT_CYCLE = {
        TrustMode.NONE: TrustMode.LOCAL,
        TrustMode.LOCAL: TrustMode.BOTH,
        TrustMode.BOTH: TrustMode.NONE,
    }

    def grant(self) -> None:
        """Cycle trust NONE→LOCAL→BOTH→NONE.  Emits error when not armed."""
        if not self._armed:
            self.emit(("error", "grant is no-op: not armed"))
            return
        self._trust = self._GRANT_CYCLE[self._trust]
        self.emit(("trust", self._trust))

    def grant_far(self) -> None:
        """Elevate the far party to BOTH/FULL immediately.  Backward-compat helper."""
        self._armed = True
        self._trust = TrustMode.BOTH
        self.emit(("far_trust", self.far_trust))

    def reset_far_trust(self) -> None:
        """Revert far-party grant only (BOTH→LOCAL); op_trust stays unchanged."""
        if self._trust is TrustMode.BOTH:
            self._trust = TrustMode.LOCAL
        self.emit(("far_trust", self.far_trust))

    def respond_to(self, text: str, *, speaker: str = "") -> None:
        """Brain + speak for one utterance (the post-STT half). Blocking — call from
        a worker thread. Shared by push-to-talk and streaming/listen mode."""
        if not text or self.state in (State.THINKING, State.SPEAKING):
            return
        self._cancel.clear()
        self._set_state(State.THINKING)
        try:
            reply = self.brain.respond(
                text, speaker=speaker, far_trust=self.far_trust,
                op_trust=self.op_trust,
                on_filler=lambda i: self.emit(("filler", self.pick())),
            )
        except Exception as exc:  # noqa: BLE001
            self.emit(("error", f"brain: {exc}"))
            self._set_state(State.IDLE)
            return
        if self._cancel.is_set():
            self._set_state(State.IDLE)
            return
        tag = reply.lane + (f"/{reply.skill}" if reply.skill else "")
        self.emit(("reply", reply.text, tag, reply.timeline.summary()))
        if not self.muted:
            self._set_state(State.SPEAKING)
            speed = self.CADENCE_SLOW if reply.re_ask else self.CADENCE_NORMAL
            try:
                self._play = self.mic.start_playback(self.tts.synth(reply.text, speed=speed))
                self._play.wait()
            except Exception as exc:  # noqa: BLE001
                self.emit(("error", f"tts: {exc}"))
            finally:
                self._play = None
        self._set_state(State.IDLE)

    def say(self, text: str) -> None:
        """Speak a canned phrase directly via TTS — no brain call. Blocking."""
        if self.muted or not text or self.state is not State.IDLE:
            return
        self._set_state(State.SPEAKING)
        try:
            self._play = self.mic.start_playback(self.tts.synth(text))
            self._play.wait()
        except Exception as exc:  # noqa: BLE001
            self.emit(("error", f"tts: {exc}"))
        finally:
            self._play = None
            self._set_state(State.IDLE)

    def interrupt(self) -> None:
        """Barge-in: cut playback now, discard any in-flight take/turn."""
        self._cancel.set()
        if self._play is not None:
            self._play.stop()
        if self._rec is not None:
            self._rec.stop()
            self._rec = None
        self._set_state(State.IDLE)

    def toggle_mute(self) -> bool:
        self.muted = not self.muted
        # Muting mid-speech cuts the current utterance too, not just the next one.
        if self.muted and self._play is not None:
            self._play.stop()
        self.emit(("mute", self.muted))
        return self.muted

    def close(self) -> None:
        self.brain.close()
