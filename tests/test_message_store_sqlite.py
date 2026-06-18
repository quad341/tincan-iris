"""Tests for SQLite-backed MessageStore persistence (ti-6qsb.4).

These tests FAIL until the builder implements the SQLite backend.
The existing in-memory API tests remain in test_message_store.py.
"""
from __future__ import annotations

import sqlite3
import time

import pytest

from iris.message_store import MessageStore


@pytest.fixture
def store(tmp_path):
    return MessageStore(path=tmp_path / "iris.db")


# ---------------------------------------------------------------------------
# add() + unread() round-trip
# ---------------------------------------------------------------------------

def test_add_unread_round_trip(store):
    store.add("Alice", "Call me back.", caller_number="+15555550101")
    msgs = store.unread()
    assert len(msgs) == 1
    assert msgs[0].caller_name == "Alice"
    assert msgs[0].transcript == "Call me back."
    assert msgs[0].caller_number == "+15555550101"


def test_unread_excludes_read_messages(store):
    m1 = store.add("Alice", "first")
    store.add("Bob", "second")
    store.mark_read(m1.id)
    unread = store.unread()
    assert len(unread) == 1
    assert unread[0].caller_name == "Bob"


# ---------------------------------------------------------------------------
# mark_read() sets read=1 and read_at
# ---------------------------------------------------------------------------

def test_mark_read_sets_read_flag(store):
    msg = store.add("Bob", "Hi there.")
    store.mark_read(msg.id)
    all_msgs = store.all()
    assert all_msgs[0].read is True


def test_mark_read_sets_read_at(store):
    before = time.time()
    msg = store.add("Bob", "Hi.")
    store.mark_read(msg.id)
    after = time.time()
    all_msgs = store.all()
    assert all_msgs[0].read_at is not None
    assert before <= all_msgs[0].read_at <= after


# ---------------------------------------------------------------------------
# mark_all_read()
# ---------------------------------------------------------------------------

def test_mark_all_read_clears_unread_queue(store):
    store.add("Alice", "msg1")
    store.add("Bob", "msg2")
    store.add("Carol", "msg3")
    store.mark_all_read()
    assert store.unread() == []


def test_mark_all_read_sets_read_on_all(store):
    store.add("Alice", "msg1")
    store.add("Bob", "msg2")
    store.mark_all_read()
    assert all(m.read for m in store.all())


# ---------------------------------------------------------------------------
# delete()
# ---------------------------------------------------------------------------

def test_delete_removes_message(store):
    msg = store.add("Alice", "text")
    store.delete(msg.id)
    assert store.all() == []


def test_delete_only_removes_target_message(store):
    m1 = store.add("Alice", "keep")
    m2 = store.add("Bob", "delete me")
    store.delete(m2.id)
    remaining = store.all()
    assert len(remaining) == 1
    assert remaining[0].id == m1.id


# ---------------------------------------------------------------------------
# Persistence across re-instantiation
# ---------------------------------------------------------------------------

def test_messages_survive_store_restart(tmp_path):
    path = tmp_path / "iris.db"
    s1 = MessageStore(path=path)
    s1.add("Alice", "Call me back.")
    s1.add("Bob", "Ring ring.")
    del s1
    s2 = MessageStore(path=path)
    msgs = s2.unread()
    assert len(msgs) == 2
    names = {m.caller_name for m in msgs}
    assert names == {"Alice", "Bob"}


def test_mark_read_survives_restart(tmp_path):
    path = tmp_path / "iris.db"
    s1 = MessageStore(path=path)
    msg = s1.add("Alice", "text")
    s1.mark_read(msg.id)
    del s1
    s2 = MessageStore(path=path)
    assert s2.all()[0].read is True


# ---------------------------------------------------------------------------
# unread() ordering — newest-first
# ---------------------------------------------------------------------------

def test_unread_returns_newest_first(store):
    store.add("Alice", "first", timestamp=1000.0)
    store.add("Bob", "second", timestamp=2000.0)
    store.add("Carol", "third", timestamp=3000.0)
    msgs = store.unread()
    assert msgs[0].caller_name == "Carol"
    assert msgs[1].caller_name == "Bob"
    assert msgs[2].caller_name == "Alice"


# ---------------------------------------------------------------------------
# all() cap at 500
# ---------------------------------------------------------------------------

def test_all_returns_at_most_500_rows(store):
    for i in range(520):
        store.add("Caller", f"Message {i}")
    assert len(store.all()) <= 500


# ---------------------------------------------------------------------------
# WAL mode
# ---------------------------------------------------------------------------

def test_wal_mode_enabled(tmp_path):
    path = tmp_path / "iris.db"
    s = MessageStore(path=path)
    s.add("test", "msg")
    conn = sqlite3.connect(str(path))
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    conn.close()
    assert mode == "wal"
