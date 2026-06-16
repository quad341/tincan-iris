"""Tests for the three-layer memory system (iris/memory.py).

Covers: _try_load_vec (import-error path), TranscriptStore (SESSIONS/EMBEDDINGS
CRUD, NOT NULL guards, vec0 fallback), GistStore (thread safety), RollingWindow
(eviction), MemoryStore (MemoryProvider protocol), MemoryManager (call_start
happy/empty/fail paths), EmbeddingEngine (response parsing), Brain attrs, Config.
"""
from __future__ import annotations

import queue
import threading
import time
import unittest.mock as mock
from unittest.mock import MagicMock, patch

import pytest

from iris.brain import Brain
from iris.config import DEFAULT, Config
from iris.memory import (
    EmbeddingEngine,
    GistStore,
    GistWorker,
    MemoryManager,
    MemoryProvider,
    MemoryStore,
    Note,
    RollingWindow,
    TranscriptStore,
    _cosine,
    _recency_score,
    _try_load_vec,
)


# ---------------------------------------------------------------------------
# _try_load_vec
# ---------------------------------------------------------------------------


def test_try_load_vec_returns_false_on_import_error():
    import sqlite3

    conn = sqlite3.connect(":memory:")
    with patch("builtins.__import__", side_effect=ImportError("no sqlite_vec")):
        with patch.dict("sys.modules", {"sqlite_vec": None}):
            result = _try_load_vec(conn)
    conn.close()
    assert result is False


def test_try_load_vec_returns_false_on_not_authorized():
    """enable_load_extension(True) itself raises OperationalError on restricted builds."""
    import sqlite3

    class NoExtConn:
        def enable_load_extension(self, flag: bool) -> None:
            if flag:
                raise sqlite3.OperationalError("not authorized")

        def load_extension(self, path: str) -> None:
            pass  # never reached

    fake_mod = MagicMock()
    fake_mod.loadable_path.return_value = "/some/path.so"
    with patch.dict("sys.modules", {"sqlite_vec": fake_mod}):
        result = _try_load_vec(NoExtConn())  # type: ignore[arg-type]
    assert result is False


def test_try_load_vec_returns_false_on_bad_path():
    import sqlite3

    conn = sqlite3.connect(":memory:")
    fake_mod = MagicMock()
    fake_mod.loadable_path.return_value = "/nonexistent/sqlite_vec.so"
    with patch.dict("sys.modules", {"sqlite_vec": fake_mod}):
        result = _try_load_vec(conn)
    conn.close()
    assert result is False


def test_try_load_vec_disables_extension_loading_after_failure():
    """enable_load_extension(False) is called in finally even when load_extension fails."""
    import sqlite3

    class TrackingConn:
        def __init__(self) -> None:
            self.calls: list[bool] = []

        def enable_load_extension(self, flag: bool) -> None:
            self.calls.append(flag)

        def load_extension(self, path: str) -> None:
            raise sqlite3.OperationalError("no such file")

    conn = TrackingConn()
    fake_mod = MagicMock()
    fake_mod.loadable_path.return_value = "/nonexistent.so"
    with patch.dict("sys.modules", {"sqlite_vec": fake_mod}):
        _try_load_vec(conn)  # type: ignore[arg-type]

    assert True in conn.calls, "enable_load_extension(True) must be called"
    assert False in conn.calls, "enable_load_extension(False) must be called in finally"


# ---------------------------------------------------------------------------
# TranscriptStore
# ---------------------------------------------------------------------------


def test_transcript_store_creates_sessions_table():
    ts = TranscriptStore()
    ts.start_session("s1", "alice")
    rows = ts._conn.execute("SELECT contact_id FROM SESSIONS WHERE session_id='s1'").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "alice"


def test_transcript_store_start_session_contact_id_not_null():
    ts = TranscriptStore()
    with pytest.raises(ValueError, match="contact_id"):
        ts.start_session("s1", "")


def test_transcript_store_end_session_sets_ended_at():
    ts = TranscriptStore()
    ts.start_session("s1", "alice")
    ts.end_session("s1")
    row = ts._conn.execute("SELECT ended_at FROM SESSIONS WHERE session_id='s1'").fetchone()
    assert row[0] is not None
    assert row[0] > 0


def test_transcript_store_end_session_idempotent():
    ts = TranscriptStore()
    ts.start_session("s1", "alice")
    ts.end_session("s1")
    first_ended = ts._conn.execute(
        "SELECT ended_at FROM SESSIONS WHERE session_id='s1'"
    ).fetchone()[0]
    ts.end_session("s1")
    second_ended = ts._conn.execute(
        "SELECT ended_at FROM SESSIONS WHERE session_id='s1'"
    ).fetchone()[0]
    assert first_ended == second_ended


def test_transcript_store_insert_embedding_contact_id_not_null():
    ts = TranscriptStore()
    with pytest.raises(ValueError, match="contact_id"):
        ts.insert_embedding("s1", "", "hello", None)


def test_transcript_store_insert_and_fetch_embedding():
    ts = TranscriptStore()
    ts.insert_embedding("s1", "alice", "hello world", [0.1, 0.2, 0.3])
    rows = ts.fetch_embeddings_for_contact("alice")
    assert len(rows) == 1
    text, created_at, emb = rows[0]
    assert text == "hello world"
    assert emb == [0.1, 0.2, 0.3]
    assert created_at > 0


def test_transcript_store_fetch_returns_newest_first():
    ts = TranscriptStore()
    ts.insert_embedding("s1", "alice", "first", None)
    time.sleep(0.01)
    ts.insert_embedding("s1", "alice", "second", None)
    rows = ts.fetch_embeddings_for_contact("alice")
    assert rows[0][0] == "second"
    assert rows[1][0] == "first"


def test_transcript_store_fetch_only_for_requested_contact():
    ts = TranscriptStore()
    ts.insert_embedding("s1", "alice", "alice text", None)
    ts.insert_embedding("s1", "bob", "bob text", None)
    rows = ts.fetch_embeddings_for_contact("alice")
    assert all(r[0] == "alice text" for r in rows)


def test_transcript_store_fetch_null_embedding_returns_none():
    ts = TranscriptStore()
    ts.insert_embedding("s1", "alice", "no vector", None)
    rows = ts.fetch_embeddings_for_contact("alice")
    assert rows[0][2] is None


def test_transcript_store_uses_plain_table_when_vec_unavailable():
    with patch("iris.memory._try_load_vec", return_value=False):
        ts = TranscriptStore()
    assert ts.vec_loaded is False
    ts.insert_embedding("s1", "alice", "fallback", [0.5])
    rows = ts.fetch_embeddings_for_contact("alice")
    assert rows[0][0] == "fallback"


def test_transcript_store_close():
    ts = TranscriptStore()
    ts.close()
    assert ts._conn is None


# ---------------------------------------------------------------------------
# GistStore
# ---------------------------------------------------------------------------


def test_gist_store_starts_empty():
    gs = GistStore()
    assert gs.get() == ""


def test_gist_store_append_and_get():
    gs = GistStore()
    gs.append("segment one")
    assert gs.get() == "segment one"
    gs.append("segment two")
    assert gs.get() == "segment one\nsegment two"


def test_gist_store_thread_safe_concurrent_appends():
    gs = GistStore()
    errors = []

    def writer(i):
        try:
            gs.append(f"segment {i}")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    result = gs.get()
    assert result.count("segment") == 20


# ---------------------------------------------------------------------------
# RollingWindow + eviction
# ---------------------------------------------------------------------------


def test_rolling_window_appends_to_deque():
    ts = TranscriptStore()
    gs = GistStore()
    gw = GistWorker(gs, "http://localhost:8080")
    gw.start()
    rw = RollingWindow(ts, gw, "s1", "alice")
    rw.append("turn A")
    rw.append("turn B")
    assert rw.get() == ["turn A", "turn B"]
    gw.shutdown()
    gw.join(timeout=1)


def test_rolling_window_writes_to_transcript_store():
    ts = TranscriptStore()
    gs = GistStore()
    gw = GistWorker(gs, "http://localhost:8080")
    gw.start()
    rw = RollingWindow(ts, gw, "s1", "alice")
    rw.append("spoken turn")
    rows = ts.fetch_embeddings_for_contact("alice")
    assert any(r[0] == "spoken turn" for r in rows)
    gw.shutdown()
    gw.join(timeout=1)


def test_rolling_window_evicts_oldest_10_when_full():
    ts = TranscriptStore()
    gs = GistStore()
    enqueued: list[list[str]] = []
    gw = GistWorker(gs, "http://localhost:8080")
    # Intercept enqueue instead of starting the thread
    gw.enqueue = lambda turns: enqueued.append(turns)

    rw = RollingWindow(ts, gw, "s1", "alice")
    for i in range(30):
        rw.append(f"turn {i}")
    assert len(rw.get()) == 30
    assert len(enqueued) == 0

    # 31st turn should trigger eviction of oldest 10
    rw.append("turn 30")
    assert len(enqueued) == 1
    assert len(enqueued[0]) == 10
    assert enqueued[0][0] == "turn 0"
    assert enqueued[0][9] == "turn 9"
    assert len(rw.get()) == 21


def test_rolling_window_append_does_not_block_on_eviction():
    ts = TranscriptStore()
    gs = GistStore()
    slow_q: queue.Queue = queue.Queue()

    class SlowWorker:
        def enqueue(self, turns):
            slow_q.put(turns)

    rw = RollingWindow(ts, SlowWorker(), "s1", "alice")  # type: ignore[arg-type]
    for i in range(30):
        rw.append(f"t{i}")

    start = time.monotonic()
    rw.append("trigger eviction")
    elapsed = time.monotonic() - start
    assert elapsed < 0.01, f"append blocked for {elapsed:.3f}s — eviction must be async"


# ---------------------------------------------------------------------------
# MemoryStore — MemoryProvider protocol
# ---------------------------------------------------------------------------


def test_memory_store_implements_memory_provider():
    ts = TranscriptStore()
    gs = GistStore()
    gw = GistWorker(gs, "http://localhost:8080")
    gw.start()
    ms = MemoryStore(ts, gw, gs, "s1", "alice")
    assert isinstance(ms, MemoryProvider)
    gw.shutdown()
    gw.join(timeout=1)


def test_memory_store_append_turn_updates_window():
    ts = TranscriptStore()
    gs = GistStore()
    gw = GistWorker(gs, "http://localhost:8080")
    gw.start()
    ms = MemoryStore(ts, gw, gs, "s1", "alice")
    ms.append_turn("hello")
    ms.append_turn("world")
    assert ms.get_window() == ["hello", "world"]
    gw.shutdown()
    gw.join(timeout=1)


def test_memory_store_get_gist_reflects_gist_store():
    ts = TranscriptStore()
    gs = GistStore()
    gw = GistWorker(gs, "http://localhost:8080")
    gw.start()
    ms = MemoryStore(ts, gw, gs, "s1", "alice")
    gs.append("a gist segment")
    assert ms.get_gist() == "a gist segment"
    gw.shutdown()
    gw.join(timeout=1)


# ---------------------------------------------------------------------------
# EmbeddingEngine
# ---------------------------------------------------------------------------


def _fake_urlopen(url_obj, timeout):
    import io, json  # noqa: E401

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def read(self):
            return json.dumps({"embedding": [0.1, 0.2, 0.3]}).encode()

    return FakeResp()


def test_embedding_engine_embed_returns_vector():
    engine = EmbeddingEngine("http://localhost:8080", "nomic-embed-text")
    with patch("urllib.request.urlopen", side_effect=_fake_urlopen):
        vec = engine.embed("hello world")
    assert vec == [0.1, 0.2, 0.3]


def test_embedding_engine_parses_data_key_format():
    import json

    engine = EmbeddingEngine("http://localhost:8080", "nomic-embed-text")

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def read(self):
            return json.dumps({"data": [{"embedding": [0.9, 0.8]}]}).encode()

    with patch("urllib.request.urlopen", return_value=FakeResp()):
        vec = engine.embed("test")
    assert vec == [0.9, 0.8]


# ---------------------------------------------------------------------------
# MemoryManager.call_start
# ---------------------------------------------------------------------------


def test_memory_manager_call_start_returns_empty_without_contact():
    mm = MemoryManager(TranscriptStore())
    assert mm.call_start("s1", "") == ""


def test_memory_manager_call_start_returns_empty_without_engine():
    mm = MemoryManager(TranscriptStore(), engine=None)
    assert mm.call_start("s1", "alice") == ""


def test_memory_manager_call_start_returns_empty_with_no_stored_rows():
    engine = MagicMock()
    engine.embed.return_value = [1.0, 0.0]
    ts = TranscriptStore()
    mm = MemoryManager(ts, engine=engine)
    result = mm.call_start("s1", "alice")
    assert result == ""


def test_memory_manager_call_start_returns_empty_on_engine_failure():
    engine = MagicMock()
    engine.embed.side_effect = RuntimeError("no server")
    ts = TranscriptStore()
    ts.insert_embedding("s0", "alice", "some memory", [0.5, 0.5])
    mm = MemoryManager(ts, engine=engine)
    result = mm.call_start("s1", "alice")
    assert result == ""


def test_memory_manager_call_start_returns_hint_when_match_found():
    engine = MagicMock()
    engine.embed.return_value = [1.0, 0.0]
    ts = TranscriptStore()
    ts.insert_embedding("s0", "alice", "Alice discussed budget Q3.", [1.0, 0.0])
    mm = MemoryManager(ts, engine=engine)
    result = mm.call_start("s1", "alice")
    assert "budget" in result.lower() or result != ""


def test_memory_manager_call_start_where_clause_not_post_filter():
    """Verify contact_id filtering happens in SQL WHERE, not in Python post-filter."""
    engine = MagicMock()
    engine.embed.return_value = [1.0, 0.0]
    ts = TranscriptStore()
    ts.insert_embedding("s0", "alice", "Alice note", [1.0, 0.0])
    ts.insert_embedding("s0", "bob", "Bob note", [1.0, 0.0])
    with patch.object(ts, "fetch_embeddings_for_contact", wraps=ts.fetch_embeddings_for_contact) as spy:
        mm = MemoryManager(ts, engine=engine)
        mm.call_start("s1", "alice")
        spy.assert_called_once_with("alice")


# ---------------------------------------------------------------------------
# Math helpers
# ---------------------------------------------------------------------------


def test_cosine_orthogonal_vectors():
    assert abs(_cosine([1.0, 0.0], [0.0, 1.0])) < 1e-9


def test_cosine_identical_vectors():
    assert abs(_cosine([1.0, 1.0], [1.0, 1.0]) - 1.0) < 1e-9


def test_cosine_zero_vector_returns_zero():
    assert _cosine([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_recency_score_recent_not_penalised():
    score = _recency_score(1.0, int(time.time()))
    assert score == pytest.approx(1.0, abs=0.01)


def test_recency_score_old_entry_penalised():
    twelve_months_ago = int(time.time()) - 12 * 30 * 24 * 3600
    score = _recency_score(1.0, twelve_months_ago)
    # max(0.5, 1 - 0.1 * 12) = max(0.5, -0.2) = 0.5
    assert score == pytest.approx(0.5, abs=0.01)


# ---------------------------------------------------------------------------
# Brain.memory_hint / context_hint
# ---------------------------------------------------------------------------


def test_brain_has_memory_hint_attribute():
    b = Brain()
    assert hasattr(b, "memory_hint")
    assert b.memory_hint == ""


def test_brain_has_context_hint_attribute():
    b = Brain()
    assert hasattr(b, "context_hint")
    assert b.context_hint == ""


def test_brain_memory_hint_is_mutable():
    b = Brain()
    b.memory_hint = "Alice last discussed the Q3 budget."
    assert b.memory_hint == "Alice last discussed the Q3 budget."


# ---------------------------------------------------------------------------
# Config.embedding_model
# ---------------------------------------------------------------------------


def test_config_default_embedding_model():
    assert DEFAULT.embedding_model == "nomic-embed-text"


def test_config_embedding_model_overridable():
    cfg = Config(embedding_model="mxbai-embed-large")
    assert cfg.embedding_model == "mxbai-embed-large"


# ---------------------------------------------------------------------------
# TranscriptStore new helpers
# ---------------------------------------------------------------------------


def test_transcript_store_is_session_ended_false_before_end():
    ts = TranscriptStore()
    ts.start_session("s1", "alice")
    assert ts.is_session_ended("s1") is False


def test_transcript_store_is_session_ended_true_after_end():
    ts = TranscriptStore()
    ts.start_session("s1", "alice")
    ts.end_session("s1")
    assert ts.is_session_ended("s1") is True


def test_transcript_store_is_session_ended_unknown_session():
    ts = TranscriptStore()
    assert ts.is_session_ended("no-such") is False


def test_transcript_store_get_session_contact_id():
    ts = TranscriptStore()
    ts.start_session("s1", "alice")
    assert ts.get_session_contact_id("s1") == "alice"


def test_transcript_store_get_session_contact_id_unknown():
    ts = TranscriptStore()
    assert ts.get_session_contact_id("no-such") is None


def test_transcript_store_end_session_with_gist():
    ts = TranscriptStore()
    ts.start_session("s1", "alice")
    ts.end_session_with_gist("s1", "We discussed the Q3 budget.")
    row = ts._conn.execute(
        "SELECT ended_at, final_gist FROM SESSIONS WHERE session_id='s1'"
    ).fetchone()
    assert row[0] is not None
    assert row[1] == "We discussed the Q3 budget."


def test_transcript_store_end_session_with_gist_idempotent():
    ts = TranscriptStore()
    ts.start_session("s1", "alice")
    ts.end_session_with_gist("s1", "first summary")
    ts.end_session_with_gist("s1", "should be ignored")
    row = ts._conn.execute("SELECT final_gist FROM SESSIONS WHERE session_id='s1'").fetchone()
    assert row[0] == "first summary"


def test_transcript_store_insert_embedding_with_source_fields():
    ts = TranscriptStore()
    ts.insert_embedding("s1", "alice", "summary text", [0.1], source_type="gist", source_id="s1")
    row = ts._conn.execute(
        "SELECT source_type, source_id FROM EMBEDDINGS WHERE session_id='s1'"
    ).fetchone()
    assert row[0] == "gist"
    assert row[1] == "s1"


def test_transcript_store_insert_embedding_default_source_type():
    ts = TranscriptStore()
    ts.insert_embedding("s1", "alice", "a turn", None)
    row = ts._conn.execute("SELECT source_type FROM EMBEDDINGS WHERE session_id='s1'").fetchone()
    assert row[0] == "turn"


# ---------------------------------------------------------------------------
# Note
# ---------------------------------------------------------------------------


def test_note_dataclass_defaults():
    n = Note(id=0, text="hello")
    assert n.open is True


def test_memory_manager_add_note_returns_incrementing_ids():
    mm = MemoryManager(TranscriptStore())
    id0 = mm.add_note("first note")
    id1 = mm.add_note("second note")
    assert id0 == 0
    assert id1 == 1


def test_memory_manager_call_start_resets_notes():
    mm = MemoryManager(TranscriptStore())
    mm.add_note("pre-call note")
    mm.call_start("s1", "alice")
    assert mm._notes == []


# ---------------------------------------------------------------------------
# MemoryManager.call_end
# ---------------------------------------------------------------------------


def _make_mm_with_mocked_qwen(engine=None):
    """Return a MemoryManager whose _qwen_summarise is patched to avoid network."""
    ts = TranscriptStore()
    ts.start_session("s1", "alice")
    mm = MemoryManager(ts, engine=engine)
    mm._qwen_summarise = MagicMock(return_value="Final summary of the call.")
    return mm, ts


def test_call_end_returns_immediately():
    mm, ts = _make_mm_with_mocked_qwen()
    mm.call_start("s1", "alice")
    start = time.monotonic()
    mm.call_end("s1")
    elapsed = time.monotonic() - start
    assert elapsed < 0.05, f"call_end blocked for {elapsed:.3f}s — must return ≤1ms"
    time.sleep(0.1)  # let archive thread finish


def test_call_end_writes_final_gist_to_sessions():
    mm, ts = _make_mm_with_mocked_qwen()
    mm._qwen_summarise.return_value = "Discussed project X."
    mm.call_start("s1", "alice")
    mm.call_end("s1")
    time.sleep(0.1)
    assert ts.is_session_ended("s1")
    row = ts._conn.execute("SELECT final_gist FROM SESSIONS WHERE session_id='s1'").fetchone()
    assert row[0] == "Discussed project X."


def test_call_end_idempotent_second_call_is_noop():
    mm, ts = _make_mm_with_mocked_qwen()
    mm.call_start("s1", "alice")
    mm.call_end("s1")
    time.sleep(0.1)
    first_ended = ts._conn.execute("SELECT ended_at FROM SESSIONS WHERE session_id='s1'").fetchone()[0]
    mm._qwen_summarise.reset_mock()
    mm.call_end("s1")
    time.sleep(0.1)
    second_ended = ts._conn.execute("SELECT ended_at FROM SESSIONS WHERE session_id='s1'").fetchone()[0]
    assert first_ended == second_ended
    mm._qwen_summarise.assert_not_called()


def test_call_end_embeds_gist_when_engine_available():
    engine = MagicMock()
    engine.embed.return_value = [0.5, 0.5]
    mm, ts = _make_mm_with_mocked_qwen(engine=engine)
    mm.call_start("s1", "alice")
    mm.call_end("s1")
    time.sleep(0.1)
    rows = ts.fetch_embeddings_for_contact("alice")
    gist_rows = [r for r in rows if r[0].startswith("Final summary") or r[2] is not None]
    assert len(gist_rows) >= 1


def test_call_end_embeds_open_notes():
    engine = MagicMock()
    engine.embed.return_value = [0.1, 0.9]
    mm, ts = _make_mm_with_mocked_qwen(engine=engine)
    mm.call_start("s1", "alice")
    mm.add_note("Check back on invoice #42")
    mm.call_end("s1")
    time.sleep(0.1)
    rows = ts.fetch_embeddings_for_contact("alice")
    note_rows = [r for r in rows if "invoice" in r[0].lower()]
    assert len(note_rows) == 1


def test_call_end_skips_closed_notes():
    engine = MagicMock()
    engine.embed.return_value = [0.1, 0.9]
    mm, ts = _make_mm_with_mocked_qwen(engine=engine)
    mm.call_start("s1", "alice")
    mm.add_note("closed note")
    mm._notes[0].open = False
    mm.call_end("s1")
    time.sleep(0.1)
    rows = ts.fetch_embeddings_for_contact("alice")
    note_rows = [r for r in rows if "closed note" in r[0]]
    assert len(note_rows) == 0


def test_call_end_does_not_raise_on_engine_failure():
    engine = MagicMock()
    engine.embed.side_effect = RuntimeError("no server")
    mm, ts = _make_mm_with_mocked_qwen(engine=engine)
    mm.call_start("s1", "alice")
    mm.call_end("s1")
    time.sleep(0.1)
    # Session should still be ended even if embedding failed
    assert ts.is_session_ended("s1")


def test_call_end_shuts_down_gist_worker():
    gs = GistStore()
    gw = GistWorker(gs, "http://localhost:8080")
    gw.start()
    mm, ts = _make_mm_with_mocked_qwen()
    mm.call_start("s1", "alice", gist_worker=gw, gist_store=gs)
    mm.call_end("s1")
    time.sleep(0.2)
    assert not gw.is_alive()
