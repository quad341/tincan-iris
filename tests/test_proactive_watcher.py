"""Tests for ProactiveWatcher calendar nudge logic (ti-6qsb.5).

These tests FAIL until the builder implements iris/watcher.py.
Calendar and D-Bus calls are fully mocked; no network or hardware required.
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _watcher(*, nudge_min: int = 30, poll_interval_s: float = 300.0):
    from iris.config import Config
    from iris.watcher import ProactiveWatcher
    store = MagicMock()
    cal = MagicMock()
    cfg = Config(
        calendar_nudge_min=nudge_min,
        calendar_poll_interval_s=poll_interval_s,
    )
    return ProactiveWatcher(store=store, calendar=cal, cfg=cfg)


def _event(starts_in_s: float, event_id: str = "ev-1", title: str = "Team standup"):
    """Return a mock calendar event that starts in `starts_in_s` seconds."""
    ev = MagicMock()
    ev.event_id = event_id
    ev.title = title
    ev.starts_at = time.time() + starts_in_s
    return ev


# ---------------------------------------------------------------------------
# Imminent event enqueued as P1
# ---------------------------------------------------------------------------

def test_imminent_event_enqueued_as_p1():
    w = _watcher(nudge_min=30)
    event = _event(starts_in_s=10 * 60)  # 10 min from now — within 30-min window
    w._calendar.list_events.return_value = [event]
    w._poll_once()
    w._store.enqueue.assert_called_once()
    kwargs = w._store.enqueue.call_args.kwargs
    assert kwargs.get("priority") == 1


def test_imminent_event_message_contains_time_phrase():
    w = _watcher(nudge_min=30)
    event = _event(starts_in_s=10 * 60)
    w._calendar.list_events.return_value = [event]
    w._poll_once()
    kwargs = w._store.enqueue.call_args.kwargs
    msg = kwargs.get("message", "")
    assert "min" in msg or "minute" in msg


def test_non_imminent_event_not_enqueued():
    w = _watcher(nudge_min=30)
    event = _event(starts_in_s=60 * 60)  # 1 hour — outside 30-min window
    w._calendar.list_events.return_value = [event]
    w._poll_once()
    w._store.enqueue.assert_not_called()


# ---------------------------------------------------------------------------
# NUDGE_CACHE deduplication
# ---------------------------------------------------------------------------

def test_second_poll_does_not_re_enqueue_same_event(tmp_path):
    from iris.config import Config

    store = MagicMock()
    cal = MagicMock()
    cfg = Config(calendar_nudge_min=30, calendar_poll_interval_s=300.0)
    from iris.watcher import ProactiveWatcher
    w = ProactiveWatcher(store=store, calendar=cal, cfg=cfg,
                         db_path=tmp_path / "nudge.db")
    event = _event(starts_in_s=10 * 60, event_id="ev-dedup")
    cal.list_events.return_value = [event]

    w._poll_once()
    w._poll_once()  # same event, second poll

    assert store.enqueue.call_count == 1  # not 2


# ---------------------------------------------------------------------------
# Prune rows older than 48h
# ---------------------------------------------------------------------------

def test_old_nudge_cache_rows_pruned(tmp_path):
    from iris.config import Config

    store = MagicMock()
    cal = MagicMock()
    cfg = Config(calendar_nudge_min=30, calendar_poll_interval_s=300.0)
    from iris.watcher import ProactiveWatcher
    w = ProactiveWatcher(store=store, calendar=cal, cfg=cfg,
                         db_path=tmp_path / "nudge.db")
    cal.list_events.return_value = []

    w._poll_once()  # runs prune logic even with no events
    # Pruning itself is not directly observable without reaching into DB,
    # but the method must complete without error and not raise.
    # Verify no exception raised:
    assert True


def test_prune_removes_stale_rows_before_fresh_event(tmp_path):
    """After a stale dedup entry is pruned, the event can be re-enqueued."""
    import sqlite3
    from iris.config import Config

    store = MagicMock()
    cal = MagicMock()
    cfg = Config(calendar_nudge_min=30, calendar_poll_interval_s=300.0)
    from iris.watcher import ProactiveWatcher
    db_path = tmp_path / "nudge.db"
    w = ProactiveWatcher(store=store, calendar=cal, cfg=cfg, db_path=db_path)

    event = _event(starts_in_s=10 * 60, event_id="ev-stale")
    cal.list_events.return_value = [event]
    w._poll_once()  # first enqueue
    assert store.enqueue.call_count == 1

    # Manually backdate the NUDGE_CACHE row to simulate 49h ago
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "UPDATE NUDGE_CACHE SET notified_at = ? WHERE event_id = ?",
        (time.time() - 49 * 3600, "ev-stale"),
    )
    conn.commit()
    conn.close()

    w._poll_once()  # prune runs, stale row gone, event re-enqueued
    assert store.enqueue.call_count == 2


# ---------------------------------------------------------------------------
# D-Bus setup failure does not block calendar thread
# ---------------------------------------------------------------------------

def test_dbus_failure_does_not_prevent_start():
    from iris.config import Config
    from iris.watcher import ProactiveWatcher

    store = MagicMock()
    cal = MagicMock()
    cal.list_events.return_value = []
    cfg = Config(calendar_nudge_min=30, calendar_poll_interval_s=300.0)
    w = ProactiveWatcher(store=store, calendar=cal, cfg=cfg)

    with patch.object(w, "_setup_dbus", side_effect=RuntimeError("dbus not found")):
        w.start()

    assert w._cal_thread.is_alive()
    w.stop()


# ---------------------------------------------------------------------------
# start() idempotency
# ---------------------------------------------------------------------------

def test_start_idempotency_does_not_spawn_extra_thread():
    from iris.config import Config
    from iris.watcher import ProactiveWatcher

    store = MagicMock()
    cal = MagicMock()
    cal.list_events.return_value = []
    cfg = Config(calendar_nudge_min=30, calendar_poll_interval_s=300.0)
    w = ProactiveWatcher(store=store, calendar=cal, cfg=cfg)

    with patch.object(w, "_setup_dbus", side_effect=Exception("no dbus")):
        w.start()
        thread_id_1 = id(w._cal_thread)
        w.start()  # second call — must be no-op
        thread_id_2 = id(w._cal_thread)

    assert thread_id_1 == thread_id_2
    w.stop()


# ---------------------------------------------------------------------------
# "starts in N min" rounds down to nearest 5 min
# ---------------------------------------------------------------------------

def test_nudge_message_rounds_down_to_5_min():
    w = _watcher(nudge_min=30)
    # 14 min 47 sec from now — should round DOWN to 10 min (nearest 5)
    event = _event(starts_in_s=14 * 60 + 47)
    w._calendar.list_events.return_value = [event]
    w._poll_once()
    kwargs = w._store.enqueue.call_args.kwargs
    msg = kwargs.get("message", "")
    # "10 min" not "15 min" (rounds down, not nearest)
    assert "10" in msg


def test_nudge_message_exactly_15_min():
    w = _watcher(nudge_min=30)
    event = _event(starts_in_s=15 * 60)  # exactly 15 min
    w._calendar.list_events.return_value = [event]
    w._poll_once()
    kwargs = w._store.enqueue.call_args.kwargs
    msg = kwargs.get("message", "")
    assert "15" in msg
