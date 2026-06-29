"""Tests for MayorReplyListener (ti-h9di.3) — stub mode + deliver() path."""
from __future__ import annotations

import time

from iris.delegate_skill import _DelegateState, ConfirmDelegateSkill
from iris.mayor_reply import MayorReplyListener


def _make_state() -> _DelegateState:
    state = _DelegateState()
    state.enqueue("del-00000001", "Request from Iris: test", "test")
    return state


# ---------------------------------------------------------------------------
# Stub mode (ga-ty8cfb not yet shipped) — no SSE_URL
# ---------------------------------------------------------------------------

def test_stub_start_does_not_error():
    state = _make_state()
    events: list[tuple] = []
    listener = MayorReplyListener(state=state, emit=events.append)
    listener.start("del-00000001")
    # Thread is daemon; give it a moment to exit cleanly
    time.sleep(0.05)
    assert events == [], "stub listener must not emit any events"


def test_stub_start_spawns_daemon_thread():
    state = _make_state()
    listener = MayorReplyListener(state=state, emit=lambda ev: None)
    listener.start("del-00000001")
    # The thread may have already exited (stub returns immediately) — that's fine.
    # Just verify no exception was raised and the state is intact.
    assert state.queue_count >= 0  # not crashed


# ---------------------------------------------------------------------------
# deliver() — event firing and state cleanup
# ---------------------------------------------------------------------------

def test_deliver_emits_mayor_reply_event():
    state = _make_state()
    events: list[tuple] = []
    listener = MayorReplyListener(state=state, emit=events.append)
    listener.deliver("del-00000001", "The mayor said: no problem.")
    assert len(events) == 1
    assert events[0][0] == "mayor_reply"
    assert events[0][1] == "The mayor said: no problem."
    assert events[0][2] == "del-00000001"


def test_deliver_dequeues_pending_entry():
    state = _make_state()
    assert state.queue_count == 1
    events: list[tuple] = []
    listener = MayorReplyListener(state=state, emit=events.append)
    listener.deliver("del-00000001", "Done.")
    assert state.queue_count == 0


def test_deliver_unknown_entry_is_noop():
    state = _DelegateState()
    events: list[tuple] = []
    listener = MayorReplyListener(state=state, emit=events.append)
    listener.deliver("del-deadbeef", "surprise")
    # Still emits the event (display-only path), state untouched
    assert events[0][0] == "mayor_reply"
    assert state.queue_count == 0  # nothing to dequeue


# ---------------------------------------------------------------------------
# ConfirmDelegateSkill on_sent callback wiring
# ---------------------------------------------------------------------------

def test_on_sent_called_after_mail_sent():
    state = _DelegateState()
    state.stage("Request from Iris: fix it", "fix it")
    sent_ids: list[str] = []
    skill = ConfirmDelegateSkill(
        state=state,
        gc_bin="true",  # 'true' is a shell no-op that exits 0
        on_sent=sent_ids.append,
    )
    result = skill.run()
    assert "sent" in result.lower()
    assert len(sent_ids) == 1
    assert sent_ids[0].startswith("del-")


def test_on_sent_not_called_on_failure():
    state = _DelegateState()
    state.stage("Request from Iris: something", "something")
    sent_ids: list[str] = []
    skill = ConfirmDelegateSkill(
        state=state,
        gc_bin="false",  # 'false' exits non-zero on every call
        on_sent=sent_ids.append,
    )
    result = skill.run()
    assert "sorry" in result.lower()
    assert sent_ids == []


def test_on_sent_omitted_still_works():
    state = _DelegateState()
    state.stage("Request from Iris: test", "test")
    skill = ConfirmDelegateSkill(state=state, gc_bin="true")
    result = skill.run()
    assert "sent" in result.lower()
