"""Tests for TranscriptStore — all use tmp_path, no home-dir writes."""
from __future__ import annotations

import time

import pytest

from iris.transcript import TranscriptStore


@pytest.fixture
def store(tmp_path):
    return TranscriptStore(tmp_path / "transcripts.db")


def test_append_returns_rowid(store):
    rowid = store.append("s1", "operator", "hello")
    assert isinstance(rowid, int) and rowid >= 1


def test_query_returns_session_turns(store):
    store.append("s1", "operator", "hello")
    store.append("s1", "iris", "hi there")
    turns = store.query("s1")
    assert len(turns) == 2
    assert turns[0]["speaker"] == "operator"
    assert turns[0]["text"] == "hello"
    assert turns[1]["speaker"] == "iris"


def test_query_isolates_sessions(store):
    store.append("s1", "operator", "call one")
    store.append("s2", "far", "call two")
    assert len(store.query("s1")) == 1
    assert store.query("s1")[0]["text"] == "call one"
    assert len(store.query("s2")) == 1


def test_query_ordered_by_timestamp(store):
    t0 = time.time()
    store.append("s1", "operator", "first", timestamp=t0)
    store.append("s1", "far", "second", timestamp=t0 + 1)
    turns = store.query("s1")
    assert turns[0]["text"] == "first"
    assert turns[1]["text"] == "second"


def test_query_empty_session(store):
    assert store.query("nosuchsession") == []


def test_recent_returns_newest_first_then_reversed(store):
    t0 = time.time()
    store.append("s1", "operator", "a", timestamp=t0)
    store.append("s1", "iris", "b", timestamp=t0 + 1)
    store.append("s1", "far", "c", timestamp=t0 + 2)
    recent = store.recent(limit=2)
    # recent() returns oldest-first within the limit window
    assert recent[0]["text"] == "b"
    assert recent[1]["text"] == "c"


def test_recent_limit(store):
    for i in range(5):
        store.append("s1", "operator", f"turn {i}")
    assert len(store.recent(limit=3)) == 3


def test_sessions_lists_distinct_ids(store):
    store.append("alpha", "operator", "x")
    store.append("beta", "far", "y")
    store.append("alpha", "iris", "z")
    sessions = store.sessions()
    assert set(sessions) == {"alpha", "beta"}


def test_sessions_most_recent_active_first(store):
    t0 = time.time()
    store.append("older", "operator", "x", timestamp=t0)
    store.append("newer", "operator", "y", timestamp=t0 + 10)
    assert store.sessions()[0] == "newer"


def test_persists_across_instances(tmp_path):
    path = tmp_path / "t.db"
    s1 = TranscriptStore(path)
    s1.append("s", "operator", "persisted")
    s2 = TranscriptStore(path)
    assert len(s2.query("s")) == 1
    assert s2.query("s")[0]["text"] == "persisted"


def test_turn_fields(store):
    store.append("s1", "iris", "good morning")
    turn = store.query("s1")[0]
    assert {"id", "session_id", "speaker", "timestamp", "text"} <= set(turn)
    assert turn["session_id"] == "s1"
    assert turn["speaker"] == "iris"
    assert isinstance(turn["timestamp"], float)
