"""Tests for BrainHost — turn serialization, event ordering, call context (ti-s9mm.1.3).

All tests use a tmpdir sqlite db for hermetic isolation. Brain.respond_stream is mocked
to avoid Qwen HTTP calls.
"""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from iris.daemon.brain_host import BrainHost


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _chunk(text, *, lane="tier0", skill=None, final=False):
    return SimpleNamespace(text=text, lane=lane, skill=skill, final=final, denied=False)


def _mock_brain(chunks=None):
    brain = MagicMock()
    brain.call_context = ""
    if chunks is None:
        chunks = [_chunk("ok", final=True)]
    brain.respond_stream.side_effect = lambda text, **kw: iter(chunks)
    return brain


def _make_host(tmp_path, *, brain=None, broadcast=None, db_name="test.db"):
    if brain is None:
        brain = _mock_brain()
    if broadcast is None:
        broadcast = MagicMock()
    return BrainHost(brain=brain, db_path=tmp_path / db_name, broadcast=broadcast)


# ---------------------------------------------------------------------------
# 1. TurnLock busy rejection
# ---------------------------------------------------------------------------


def test_turn_lock_busy_rejection(tmp_path):
    """Second async_turn returns {ok:False, error:busy} when first turn is running."""
    lock_held = threading.Event()
    release = threading.Event()

    def _blocking_stream(text, **kw):
        lock_held.set()
        release.wait()
        yield _chunk("done", final=True)

    brain = MagicMock()
    brain.call_context = ""
    brain.respond_stream.side_effect = _blocking_stream

    host = _make_host(tmp_path, brain=brain)

    ack1 = host.async_turn("first", "operator")
    assert ack1["ok"] is True

    lock_held.wait(timeout=2.0)

    ack2 = host.async_turn("second", "operator")
    assert ack2["ok"] is False
    assert ack2.get("error") == "busy"

    release.set()


def test_turn_lock_busy_rejection_does_not_block_caller(tmp_path):
    """Busy rejection is near-instant — does not wait for the first turn to finish."""
    lock_held = threading.Event()
    release = threading.Event()

    def _blocking_stream(text, **kw):
        lock_held.set()
        release.wait()
        yield _chunk("done", final=True)

    brain = MagicMock()
    brain.call_context = ""
    brain.respond_stream.side_effect = _blocking_stream

    host = _make_host(tmp_path, brain=brain)
    host.async_turn("first", "operator")
    lock_held.wait(timeout=2.0)

    t0 = time.monotonic()
    ack = host.async_turn("second", "operator")
    elapsed = time.monotonic() - t0

    assert ack["ok"] is False
    assert elapsed < 0.5, f"Busy rejection took {elapsed:.3f}s — should be near-instant"

    release.set()


# ---------------------------------------------------------------------------
# 2. Event ordering
# ---------------------------------------------------------------------------


def test_brain_turn_started_fires_before_lock_acquired(tmp_path):
    """brain_turn_started is broadcast BEFORE TurnLock.acquire() in the same thread."""
    order: list[str] = []

    class _TrackedLock:
        def __init__(self):
            self._real = threading.Lock()

        def acquire(self, blocking=True, timeout=-1):
            order.append("lock_acquire")
            return self._real.acquire(blocking=blocking)

        def release(self):
            self._real.release()

    broadcast = lambda ev: order.append(ev.get("event", "?"))
    brain = _mock_brain()
    host = BrainHost(brain=brain, db_path=tmp_path / "test.db", broadcast=broadcast)
    host._turn_lock = _TrackedLock()

    host.async_turn("hello", "operator")

    assert "brain_turn_started" in order, "brain_turn_started was never broadcast"
    assert "lock_acquire" in order, "Lock.acquire was never called"
    assert order.index("brain_turn_started") < order.index("lock_acquire"), (
        f"brain_turn_started must precede lock_acquire; order={order}"
    )


def test_brain_reply_fires_after_all_chunks(tmp_path):
    """brain_reply is broadcast after all brain_chunk events from respond_stream."""
    events: list[dict] = []
    reply_received = threading.Event()

    def _broadcast(ev):
        events.append(ev)
        if ev.get("event") == "brain_reply":
            reply_received.set()

    brain = _mock_brain(chunks=[
        _chunk("Hello ", lane="tier0", final=False),
        _chunk("world.", lane="tier0", final=True),
    ])

    host = BrainHost(brain=brain, db_path=tmp_path / "test.db", broadcast=_broadcast)
    host.async_turn("hi", "operator")

    reply_received.wait(timeout=2.0)

    event_names = [e.get("event") for e in events]
    assert "brain_chunk" in event_names, f"No brain_chunk events; got {event_names}"
    assert "brain_reply" in event_names, f"No brain_reply event; got {event_names}"

    chunk_idxs = [i for i, n in enumerate(event_names) if n == "brain_chunk"]
    reply_idx = event_names.index("brain_reply")
    assert max(chunk_idxs) < reply_idx, (
        f"brain_reply at {reply_idx} must follow all brain_chunk events at {chunk_idxs}"
    )


def test_brain_reply_text_accumulates_chunks(tmp_path):
    """brain_reply.text is the concatenation of all chunk texts."""
    events: list[dict] = []
    reply_received = threading.Event()

    def _broadcast(ev):
        events.append(ev)
        if ev.get("event") == "brain_reply":
            reply_received.set()

    brain = _mock_brain(chunks=[
        _chunk("foo", final=False),
        _chunk("bar", final=True),
    ])

    host = BrainHost(brain=brain, db_path=tmp_path / "test.db", broadcast=_broadcast)
    host.async_turn("hi", "operator")

    reply_received.wait(timeout=2.0)

    reply = next(e for e in events if e.get("event") == "brain_reply")
    assert reply["text"] == "foobar"


# ---------------------------------------------------------------------------
# 3. call_context persistence via BRAIN_CONTEXT table
# ---------------------------------------------------------------------------


def test_set_call_context_persists_to_db(tmp_path):
    """set_call_context writes to brain_context; a fresh BrainHost reads back the values."""
    db = tmp_path / "roster.db"
    brain1 = MagicMock()
    brain1.call_context = ""
    host1 = BrainHost(brain=brain1, db_path=db, broadcast=MagicMock())
    host1.set_call_context("cid-42", "Alice", "+15550001111")

    brain2 = MagicMock()
    brain2.call_context = ""
    BrainHost(brain=brain2, db_path=db, broadcast=MagicMock())

    # _restore_context restores call_context when in_call='1'
    assert brain2.call_context == "cid-42"


def test_clear_call_context_new_instance_starts_empty(tmp_path):
    """clear_call_context marks in_call='0'; a fresh BrainHost does not restore context."""
    db = tmp_path / "roster.db"
    brain1 = MagicMock()
    brain1.call_context = ""
    host1 = BrainHost(brain=brain1, db_path=db, broadcast=MagicMock())
    host1.set_call_context("cid-42", "Alice", "+15550001111")
    host1.clear_call_context()

    brain2 = MagicMock()
    brain2.call_context = ""
    BrainHost(brain=brain2, db_path=db, broadcast=MagicMock())

    assert brain2.call_context == ""


def test_set_call_context_updates_brain_call_context(tmp_path):
    """set_call_context sets brain.call_context to the given contact_id."""
    brain = MagicMock()
    brain.call_context = ""
    host = _make_host(tmp_path, brain=brain)

    host.set_call_context("cid-X", "Bob", "+19998887777")

    assert brain.call_context == "cid-X"


def test_clear_call_context_resets_brain_call_context(tmp_path):
    """clear_call_context sets brain.call_context back to empty string."""
    brain = MagicMock()
    brain.call_context = ""
    host = _make_host(tmp_path, brain=brain)

    host.set_call_context("cid-X", "Bob", "+19998887777")
    assert brain.call_context == "cid-X"

    host.clear_call_context()
    assert brain.call_context == ""
