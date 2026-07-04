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


# --- ti-fyf2t: 3-way concurrent finish serialization (delay after check, before persist) ---


def test_finish_lock_serializes_a_delayed_middle_finisher_against_a_later_one(posture, tmp_db, monkeypatch):
    """ti-51vep Finding 1's seq check alone only guards a finish that is
    delayed BEFORE its own check runs. If the delay instead lands AFTER the
    check passes but BEFORE persist()/broadcast(), a third, newer finish
    could previously run its own entire check+persist+broadcast in that
    window and get silently overwritten when the delayed finisher's now-stale
    write lands last. _finish_lock (ti-fyf2t) closes this by holding the
    check+persist+broadcast sequence as one atomic unit per finisher, so a
    later finisher can't even start its own check until the delayed one is
    completely done. Proven here via actual completion order, not
    wall-clock timing -- if _finish_lock were absent, "late" (no delay of its
    own) would complete before "middle" is released, and its fresh write
    would then get clobbered by middle's stale one.
    """
    broadcasts = []
    posture.subscribe(broadcasts.append)

    completion_order = []
    order_lock = threading.Lock()
    arm_delay = threading.Event()
    middle_checked = threading.Event()
    release_middle = threading.Event()
    late_attempting = threading.Event()

    real_persist = PostureManager._persist

    def patched_persist(self, state):
        if arm_delay.is_set():
            arm_delay.clear()
            middle_checked.set()
            assert release_middle.wait(timeout=2), "test did not release the middle finisher in time"
        real_persist(self, state)

    monkeypatch.setattr(PostureManager, "_persist", patched_persist)

    posture.set_dnd("early")  # completes a full cycle before the race begins
    with order_lock:
        completion_order.append("early")

    def middle_finisher():
        snapshot = posture._clear_dnd_state()
        posture._finish_dnd_change(snapshot)
        with order_lock:
            completion_order.append("middle")

    arm_delay.set()
    t_middle = threading.Thread(target=middle_finisher)
    t_middle.start()
    assert middle_checked.wait(timeout=2), "middle finisher did not reach persist in time"
    # middle now holds _finish_lock, blocked just before its persist() call.

    def late_finisher():
        snapshot = posture._set_dnd_state("late", expires=42.0)
        late_attempting.set()
        posture._finish_dnd_change(snapshot)  # must block on _finish_lock until middle is done
        with order_lock:
            completion_order.append("late")

    t_late = threading.Thread(target=late_finisher)
    t_late.start()
    assert late_attempting.wait(timeout=2), "late finisher did not start in time"

    release_middle.set()
    t_middle.join(timeout=3)
    t_late.join(timeout=3)
    assert not t_middle.is_alive() and not t_late.is_alive()

    # Proof of serialization: late's ENTIRE finish (check+persist+broadcast)
    # only completed after middle's did, even though late had no delay of its
    # own -- only possible because _finish_lock made it wait for middle first.
    assert completion_order == ["early", "middle", "late"]

    assert posture.effective()["dnd"] is True  # late's value, not middle's stale False
    with sqlite3.connect(str(tmp_db)) as conn:
        row = conn.execute("SELECT dnd, dnd_expires FROM posture WHERE id=1").fetchone()
    assert bool(row[0]) is True  # persisted DB row matches late, not middle
    assert row[1] == 42.0
    assert broadcasts[-1]["dnd"] is True
    assert broadcasts[-1]["dnd_expires"] == 42.0


def test_set_dnd_state_does_not_block_on_an_in_flight_finish(posture, monkeypatch):
    """_finish_lock must serialize finishes against each other WITHOUT adding
    any blocking to the mutate path -- DaemonAPI writes the client's ack
    between the mutate call and the finish call, so _set_dnd_state /
    _clear_dnd_state must keep returning immediately even while another
    thread is mid-_finish_dnd_change (holding _finish_lock)."""
    finish_holding = threading.Event()
    release_finish = threading.Event()

    real_persist = PostureManager._persist

    def blocking_persist(self, state):
        finish_holding.set()
        assert release_finish.wait(timeout=2), "test did not release the held finish in time"
        real_persist(self, state)

    monkeypatch.setattr(PostureManager, "_persist", blocking_persist)

    def held_finisher():
        snapshot = posture._set_dnd_state("holder")
        posture._finish_dnd_change(snapshot)

    t_hold = threading.Thread(target=held_finisher)
    t_hold.start()
    assert finish_holding.wait(timeout=2), "finisher did not reach persist in time"
    # _finish_lock is now held for the duration of release_finish.

    mutate_done = threading.Event()

    def mutator():
        posture._set_dnd_state("concurrent-mutator")
        mutate_done.set()

    t_mutate = threading.Thread(target=mutator)
    t_mutate.start()
    assert mutate_done.wait(timeout=2), "_set_dnd_state blocked while a finish was in flight"
    t_mutate.join(timeout=3)

    release_finish.set()
    t_hold.join(timeout=3)
    assert not t_hold.is_alive()
