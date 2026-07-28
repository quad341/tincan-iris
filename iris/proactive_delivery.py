"""Proactive delivery engine for v1.5 context-inference notifications (ti-ccc.17.2.3).

SilenceTracker          — tracks when the operator last spoke.
ContextInferenceTrigger — converts skill events to ProactiveItem rows.
ProactiveDelivery       — tick()-based runtime that dispatches pending items.

Guardrails (see SPEAK_DURING_CALL in config.py):
  - mode 'far': zero tts_fn calls under any condition.
  - no Brain.respond() calls in this file.
  - SilenceTracker.touch() must only be called from the operator mic path.
"""
from __future__ import annotations

import time
from collections.abc import Callable

from .mode import IrisMode
from .notify_sink import DesktopNotifySink
from .proactive_store import ProactiveStore

_SILENCE_GAP_S = 3.0
_PRUNE_INTERVAL_S = 3600.0
_AUTO_DISMISS_S = 10.0


class SilenceTracker:
    """Tracks elapsed time since the operator last spoke.

    touch() must only be called from _on_heard_main() (operator mic path),
    never from _on_heard_far(), to avoid the far party resetting the timer.
    """

    def __init__(self) -> None:
        self._last_heard: float = 0.0

    def touch(self) -> None:
        """Call from operator mic path only."""
        self._last_heard = time.time()

    def silent_for(self) -> float:
        return time.time() - self._last_heard

    def is_silent(self, threshold_s: float) -> bool:
        return self.silent_for() >= threshold_s


class ContextInferenceTrigger:
    """Converts list skill lookup events to proactive queue entries.

    on_lookup_done  → enqueue with trigger_class='context_inference'
    on_lookup_failed → ignored (failure shown in console transcript only)
    """

    def __init__(self, *, store: ProactiveStore) -> None:
        self._store = store

    def on_lookup_done(self, *, skill: str, source_id: str, message: str) -> None:
        self._store.enqueue(
            trigger_class="context_inference",
            priority=2,
            message=message[:80],
            source_skill=skill,
            source_id=source_id,
        )

    def on_lookup_failed(self, *, skill: str, source_id: str) -> None:
        pass


class ProactiveDelivery:
    """Tick-based runtime that delivers pending proactive notifications.

    Call tick() every ~0.5s from the console main loop.

    Mode is determined by ``mode_fn`` (a callable set at construction) if provided,
    otherwise falls back to ``self._mode`` (string set externally, default 'idle').
    All other dependencies are injected via constructor for unit-testability.

    10s auto-dismiss: an item that has been delivered but not cycled away by
    the operator within ``_AUTO_DISMISS_S`` seconds is dismissed and the badge
    is cleared (PM decision Q1).
    """

    def __init__(
        self,
        *,
        store: ProactiveStore,
        cfg,
        silence_tracker: SilenceTracker,
        tts_fn: Callable[[str], None],
        emit: Callable[[tuple], None],
        mode_fn: Callable[[], str] | None = None,
        iris_mode_fn: Callable[[], IrisMode] | None = None,
        notify_sink: DesktopNotifySink | None = None,
        last_delivered: float = 0.0,
    ) -> None:
        self._store = store
        self._cfg = cfg
        self.silence_tracker = silence_tracker
        self._tts_fn = tts_fn
        self._emit = emit
        self._mode_fn = mode_fn
        self._iris_mode_fn = iris_mode_fn
        self._notify_sink = notify_sink
        self.last_delivered = last_delivered
        self._last_prune: float = 0.0
        self._mode: str = "idle"
        self._shown_id: int | None = None
        self._shown_at: float = 0.0

    def reset_shown(self) -> None:
        """Call when the operator cycles away from the current badge item."""
        self._shown_id = None
        self._shown_at = 0.0

    def tick(self) -> None:
        if not self._cfg.proactive_enabled:
            return

        now = time.time()

        if self._shown_id is not None and now - self._shown_at > _AUTO_DISMISS_S:
            self._store.dismiss(self._shown_id)
            self._emit(("proactive_badge", "", 0))
            self._shown_id = None
            self._shown_at = 0.0

        if now - self._last_prune >= _PRUNE_INTERVAL_S:
            self._store.prune()
            self._last_prune = now

        item = self._store.next_pending(
            self._cfg.proactive_classes,
            self._cfg.proactive_min_priority,
        )
        if item is None:
            return

        if item.priority > 0 and now - self.last_delivered < self._cfg.proactive_cooldown_s:
            return

        iris_mode = self._iris_mode_fn() if self._iris_mode_fn is not None else IrisMode.IN_CALL

        if iris_mode is IrisMode.OUT_OF_CALL:
            self._deliver_out_of_call(item, now)
            return

        mode = self._mode_fn() if self._mode_fn is not None else self._mode

        if mode == "far":
            # Safety invariant: no TTS during live call (SPEAK_DURING_CALL=False).
            self._emit(("proactive_badge", item.message, self._store.pending_count()))
            return

        if mode in ("listen", "idle"):
            silence_ok = (
                self._cfg.proactive_speak_during_listen
                and self.silence_tracker.is_silent(_SILENCE_GAP_S)
            )
            if silence_ok:
                self._tts_fn(item.message)
                self._emit(("proactive_tts", item.message))
                self._emit(("proactive_badge", item.message, self._store.pending_count()))
                self._store.mark_delivered(item.id)
                self.last_delivered = now
                self._shown_id = item.id
                self._shown_at = now
            else:
                self._emit(("proactive_badge", item.message, self._store.pending_count()))

    def _deliver_out_of_call(self, item, now: float) -> None:
        body = item.message[:80]
        if item.priority <= 0:
            # P0 bypasses cooldown
            if self._notify_sink:
                self._notify_sink.notify("Iris", body, urgency="critical")
            self._store.mark_delivered(item.id)
            self.last_delivered = now
        elif item.priority == 1:
            if self._notify_sink:
                self._notify_sink.notify("Iris", body, urgency="normal")
            self._store.mark_delivered(item.id)
            self.last_delivered = now
        else:
            # P2+ — badge only, no desktop notify
            self._emit(("proactive_badge", body, self._store.pending_count()))
