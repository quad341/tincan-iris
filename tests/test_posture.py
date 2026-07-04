"""Tests for iris.daemon.posture.PostureManager (ti-51vep Finding 1).

DaemonAPI._handle_dnd mutates state, writes the client's ack, THEN calls
_finish_dnd_change — so a slow ack write can delay a finish call well past a
second, concurrent mutation (another client thread, or PostureWatcher's
auto-expiry, sharing the same PostureManager instance). Without a freshness
check, that delayed finish persists/broadcasts its now-stale snapshot last,
silently overwriting the newer value even though effective() already reflects
it correctly. These tests use threading.Event to deterministically reproduce
that ordering (no sleep-based timing), rather than relying on load/luck.
"""
from __future__ import annotations

import sqlite3
import threading

import pytest

from iris.daemon.posture import PostureManager, PostureWatcher


@pytest.fixture
def tmp_db(tmp_path):
    return tmp_path / "test.db"


@pytest.fixture
def posture(tmp_db):
    return PostureManager(path=tmp_db)


def _persisted_dnd(tmp_db) -> bool:
    with sqlite3.connect(str(tmp_db)) as conn:
        row = conn.execute("SELECT dnd FROM posture WHERE id=1").fetchone()
    return bool(row[0])


# --- baseline: mutate/finish still works with no concurrency -----------------


def test_set_dnd_state_then_finish_persists_and_broadcasts(posture, tmp_db):
    broadcasts = []
    posture.subscribe(broadcasts.append)

    snapshot = posture._set_dnd_state("manual")
    assert posture.effective()["dnd"] is True  # mutate is visible before finish
    posture._finish_dnd_change(snapshot)

    assert _persisted_dnd(tmp_db) is True
    assert len(broadcasts) == 1
    assert broadcasts[0]["dnd"] is True


def test_clear_dnd_state_then_finish_persists_and_broadcasts(posture, tmp_db):
    posture.set_dnd("manual")
    broadcasts = []
    posture.subscribe(broadcasts.append)

    snapshot = posture._clear_dnd_state()
    posture._finish_dnd_change(snapshot)

    assert _persisted_dnd(tmp_db) is False
    assert len(broadcasts) == 1
    assert broadcasts[0]["dnd"] is False


# --- ti-51vep Finding 1: concurrent finish, last mutation must win -----------


def test_delayed_finish_does_not_overwrite_a_newer_mutation(posture, tmp_db):
    """Reproduces the reviewer's repro: thread A mutates first (DND on) but its
    finish is delayed past thread B's complete, concurrent mutate+finish cycle
    (DND off). The final persisted/broadcast state must match B (the last
    mutation), not A (the last finish to actually run).
    """
    broadcasts = []
    posture.subscribe(broadcasts.append)

    a_mutated = threading.Event()
    b_done = threading.Event()

    def slow_a():
        snapshot = posture._set_dnd_state("thread-a")
        a_mutated.set()
        assert b_done.wait(timeout=2), "thread B did not finish in time"
        posture._finish_dnd_change(snapshot)  # stale by the time this runs

    def fast_b():
        assert a_mutated.wait(timeout=2), "thread A did not mutate in time"
        snapshot = posture._clear_dnd_state()
        posture._finish_dnd_change(snapshot)
        b_done.set()

    t_a = threading.Thread(target=slow_a)
    t_b = threading.Thread(target=fast_b)
    t_a.start()
    t_b.start()
    t_a.join(timeout=3)
    t_b.join(timeout=3)
    assert not t_a.is_alive() and not t_b.is_alive()

    assert posture.effective()["dnd"] is False
    assert _persisted_dnd(tmp_db) is False  # not True (A's stale finish)

    # A's finish must no-op entirely -- only B's broadcast should have fired.
    assert len(broadcasts) == 1
    assert broadcasts[0]["dnd"] is False


def test_delayed_finish_still_wins_when_nothing_supersedes_it(posture, tmp_db):
    """A finish that is merely slow -- but genuinely is the latest mutation --
    must still persist/broadcast normally (the freshness check isn't a blanket
    delay penalty, only a check against an actually-newer mutation)."""
    snapshot = posture._set_dnd_state("manual")
    # No concurrent mutation happens here; finish arrives "late" but unopposed.
    posture._finish_dnd_change(snapshot)

    assert _persisted_dnd(tmp_db) is True


def test_posture_watcher_auto_expiry_supersedes_a_slower_concurrent_finish(posture, tmp_db):
    """Same race, but with the actual PostureWatcher class as the concurrent
    actor (not just a second hypothetical client thread) -- this is the
    specific scenario ti-51vep's finding calls out: PostureWatcher runs as a
    background thread sharing the SAME PostureManager instance as DaemonAPI.
    """
    watcher = PostureWatcher(posture)

    a_mutated = threading.Event()
    watcher_done = threading.Event()

    def slow_client():
        snapshot = posture._set_dnd_state("manual", expires=1.0)
        a_mutated.set()
        assert watcher_done.wait(timeout=2), "watcher did not auto-clear in time"
        posture._finish_dnd_change(snapshot)  # stale: watcher already cleared DND

    def watcher_auto_clear():
        assert a_mutated.wait(timeout=2), "client did not mutate in time"
        watcher._check_expiry()  # expires=1.0 is always in the past -> clears
        watcher_done.set()

    t_client = threading.Thread(target=slow_client)
    t_watcher = threading.Thread(target=watcher_auto_clear)
    t_client.start()
    t_watcher.start()
    t_client.join(timeout=3)
    t_watcher.join(timeout=3)
    assert not t_client.is_alive() and not t_watcher.is_alive()

    assert posture.effective()["dnd"] is False
    assert _persisted_dnd(tmp_db) is False
