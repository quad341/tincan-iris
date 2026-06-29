"""Tests for ProactiveDelivery, SilenceTracker, ContextInferenceTrigger (ti-ccc.17.2.4).

Follows the pattern of tests/test_brain.py and test_conductor.py:
all external deps (store, tts_fn, emit) are mocked. SilenceTracker is
tested with the real implementation.

Critical safety invariant: tts_fn must NEVER be called when mode='far'.
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock


from iris.config import Config
from iris.proactive_delivery import (
    ContextInferenceTrigger,
    ProactiveDelivery,
    SilenceTracker,
)
from iris.proactive_store import ProactiveItem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _item(**kwargs) -> ProactiveItem:
    defaults = dict(
        id=1,
        trigger_class="context_inference",
        priority=2,
        message="Price found: milk is $3.49",
        source_skill="list_lookup",
        source_id="lr-1",
        created_at=time.time(),
        expires_at=time.time() + 86400.0,
        delivered_at=None,
        dismissed=False,
    )
    defaults.update(kwargs)
    return ProactiveItem(**defaults)


def _delivery(
    *,
    mode: str = "listen",
    has_item: bool = True,
    cfg: Config | None = None,
    cooldown_s: float = 0.0,
) -> tuple[ProactiveDelivery, MagicMock, MagicMock, list]:
    """Return (delivery, store_mock, tts_fn_mock, emitted_events)."""
    store = MagicMock()
    store.next_pending.return_value = _item() if has_item else None
    tts_fn = MagicMock()
    events: list = []
    _cfg = cfg or Config(
        proactive_enabled=True,
        proactive_classes=("context_inference",),
        proactive_cooldown_s=cooldown_s,
    )
    silence = SilenceTracker()
    d = ProactiveDelivery(store=store, tts_fn=tts_fn, emit=events.append,
                          cfg=_cfg, silence_tracker=silence)
    d._mode = mode
    return d, store, tts_fn, events


# ---------------------------------------------------------------------------
# SilenceTracker
# ---------------------------------------------------------------------------

def test_silence_tracker_fresh_is_silent():
    # No touch yet — treat as silent (no prior speech)
    st = SilenceTracker()
    assert st.is_silent(threshold_s=0.0) is True


def test_silence_tracker_touch_then_not_silent():
    st = SilenceTracker()
    st.touch()
    assert st.is_silent(threshold_s=0.5) is False


def test_silence_tracker_after_gap_is_silent():
    st = SilenceTracker()
    st.touch()
    time.sleep(0.22)
    assert st.is_silent(threshold_s=0.2) is True


# ---------------------------------------------------------------------------
# tick() — proactive_enabled=False: no-op
# ---------------------------------------------------------------------------

def test_tick_disabled_does_nothing():
    cfg = Config(
        proactive_enabled=False,
        proactive_classes=("context_inference",),
    )
    store = MagicMock()
    tts_fn = MagicMock()
    events: list = []
    d = ProactiveDelivery(store=store, tts_fn=tts_fn, emit=events.append,
                          cfg=cfg, silence_tracker=SilenceTracker())
    d._mode = "listen"
    d.tick()
    store.next_pending.assert_not_called()
    tts_fn.assert_not_called()
    assert events == []


# ---------------------------------------------------------------------------
# tick() — empty queue: no-op
# ---------------------------------------------------------------------------

def test_tick_empty_queue_no_op():
    d, store, tts_fn, events = _delivery(has_item=False)
    d.tick()
    tts_fn.assert_not_called()


# ---------------------------------------------------------------------------
# tick() — far mode: badge emitted, tts_fn NEVER called (safety invariant)
# ---------------------------------------------------------------------------

def test_tick_far_mode_tts_never_called():
    """Critical safety invariant: far mode must NEVER invoke tts_fn."""
    d, store, tts_fn, events = _delivery(mode="far")
    d.tick()
    tts_fn.assert_not_called()


def test_tick_far_mode_emits_badge():
    d, store, tts_fn, events = _delivery(mode="far")
    d.tick()
    badge_events = [e for e in events if e[0] == "proactive_badge"]
    assert len(badge_events) >= 1


def test_tick_far_mode_does_not_mark_delivered():
    d, store, tts_fn, events = _delivery(mode="far")
    d.tick()
    store.mark_delivered.assert_not_called()


# ---------------------------------------------------------------------------
# tick() — listen mode, silence met: deliver
# ---------------------------------------------------------------------------

def test_tick_listen_silence_met_calls_tts():
    d, store, tts_fn, events = _delivery(mode="listen")
    # silence_tracker fresh (no touch) → is_silent satisfied
    d.tick()
    tts_fn.assert_called_once()


def test_tick_listen_silence_met_marks_delivered():
    d, store, tts_fn, events = _delivery(mode="listen")
    item = _item(id=42)
    store.next_pending.return_value = item
    d.tick()
    store.mark_delivered.assert_called_once_with(42)


def test_tick_listen_silence_met_tts_receives_message():
    d, store, tts_fn, events = _delivery(mode="listen")
    item = _item(message="Price is $3.49")
    store.next_pending.return_value = item
    d.tick()
    args, _ = tts_fn.call_args
    assert "3.49" in args[0]


# ---------------------------------------------------------------------------
# tick() — listen mode, silence NOT met: badge only, no TTS
# ---------------------------------------------------------------------------

def test_tick_listen_silence_not_met_no_tts():
    d, store, tts_fn, events = _delivery(mode="listen")
    d.silence_tracker.touch()  # just spoke — not silent yet
    d.tick()
    tts_fn.assert_not_called()


def test_tick_listen_silence_not_met_emits_badge():
    d, store, tts_fn, events = _delivery(mode="listen")
    d.silence_tracker.touch()
    d.tick()
    badge_events = [e for e in events if e[0] == "proactive_badge"]
    assert len(badge_events) >= 1


# ---------------------------------------------------------------------------
# tick() — idle mode: deliver same as listen (PM decision Q3)
# ---------------------------------------------------------------------------

def test_tick_idle_silence_met_calls_tts():
    d, store, tts_fn, events = _delivery(mode="idle")
    d.tick()
    tts_fn.assert_called_once()


def test_tick_idle_marks_delivered():
    d, store, tts_fn, events = _delivery(mode="idle")
    item = _item(id=7)
    store.next_pending.return_value = item
    d.tick()
    store.mark_delivered.assert_called_once_with(7)


# ---------------------------------------------------------------------------
# tick() — cooldown: suppress delivery within window
# ---------------------------------------------------------------------------

def test_tick_cooldown_suppresses_tts():
    d, store, tts_fn, events = _delivery(mode="listen", cooldown_s=60.0)
    d.tick()  # first tick: delivers
    tts_fn.reset_mock()
    d.tick()  # second tick: still within cooldown window
    tts_fn.assert_not_called()


# ---------------------------------------------------------------------------
# ContextInferenceTrigger
# ---------------------------------------------------------------------------

def test_context_inference_trigger_lookup_done_enqueues(tmp_path):
    store = MagicMock()
    trigger = ContextInferenceTrigger(store=store)
    trigger.on_lookup_done(
        skill="list_lookup",
        source_id="lr-1",
        message="Milk is $3.49",
    )
    store.enqueue.assert_called_once()
    kwargs = store.enqueue.call_args.kwargs
    assert kwargs.get("trigger_class") == "context_inference"
    assert "3.49" in kwargs.get("message", "")


def test_context_inference_trigger_lookup_failed_does_not_enqueue():
    store = MagicMock()
    trigger = ContextInferenceTrigger(store=store)
    trigger.on_lookup_failed(skill="list_lookup", source_id="lr-1")
    store.enqueue.assert_not_called()
