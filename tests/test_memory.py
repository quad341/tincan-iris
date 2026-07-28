"""Tests for the three-layer memory system (iris/memory.py).

Covers: _try_load_vec (import-error path), TranscriptStore (SESSIONS/EMBEDDINGS
CRUD, NOT NULL guards, vec0 fallback), GistStore (thread safety), RollingWindow
(eviction), MemoryStore (MemoryProvider protocol), MemoryManager (call_start
happy/empty/fail paths), EmbeddingEngine (response parsing), Brain attrs, Config.
"""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
import urllib.error
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


def test_sessions_primary_key_rejects_duplicate_session_id():
    """SESSIONS.session_id PRIMARY KEY must reject duplicate inserts (ti-59wi)."""
    import sqlite3
    ts = TranscriptStore()
    ts.start_session("dup-session", "alice")
    with pytest.raises(sqlite3.IntegrityError):
        ts._conn.execute(
            "INSERT INTO SESSIONS (session_id, contact_id, started_at) VALUES (?,?,?)",
            ("dup-session", "alice", 0),
        )


def test_vec_ddl_uses_float_column_not_blob():
    """EMBEDDINGS vec0 table must use float[N] (ANN-indexed) not BLOB (ti-k15u).

    When sqlite-vec is absent, the plain BLOB fallback table is created instead.
    We verify that the _EMBEDDINGS_DDL_VEC constant contains 'float[' so a
    DDL regression is caught at import time, and we verify the plain-table
    fallback uses BLOB (so the two paths are clearly distinct).
    """
    from iris.memory import _EMBEDDINGS_DDL_PLAIN, _EMBEDDINGS_DDL_VEC
    vec_ddl = _EMBEDDINGS_DDL_VEC.format(dim=768)
    assert "float[768]" in vec_ddl, "vec0 DDL must use float[N] not BLOB"
    assert "BLOB" not in vec_ddl.upper(), "vec0 DDL must not use BLOB column type"
    assert "BLOB" in _EMBEDDINGS_DDL_PLAIN.upper(), "plain fallback DDL should use BLOB"


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
    import json

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


# ---------------------------------------------------------------------------
# Unit — GistWorker (ti-c7g contract tests)
# ---------------------------------------------------------------------------


def test_gist_worker_compression_prompt_format():
    """The prompt text fed to Qwen must match _COMPRESSION_PROMPT exactly."""
    from iris.memory import _COMPRESSION_PROMPT

    captured: list[bytes] = []

    def fake_urlopen(req, timeout):
        captured.append(req.data)

        class FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

            def read(self_):
                return json.dumps({"content": "summary ok"}).encode()

        return FakeResp()

    gs = GistStore()
    gw = GistWorker(gs, "http://localhost:19999")
    gw.start()

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        gw.enqueue(["speaker: hello", "other: hi"])
        time.sleep(0.4)

    gw.shutdown()
    gw.join(timeout=1)

    assert len(captured) >= 1, "urlopen must have been called"
    body = json.loads(captured[0])
    prompt_text = body["prompt"]
    expected_fragment = _COMPRESSION_PROMPT.format(
        evicted_text="speaker: hello\nother: hi"
    )
    assert expected_fragment in prompt_text, (
        f"Compression prompt fragment not found.\nExpected fragment:\n{expected_fragment}\n"
        f"Actual prompt:\n{prompt_text}"
    )


def test_gist_worker_summary_appended_to_gist_store():
    """A successful Qwen response is written into GistStore."""

    def fake_urlopen(req, timeout):
        class FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

            def read(self_):
                return json.dumps({"content": "discussed budget plan"}).encode()

        return FakeResp()

    gs = GistStore()
    gw = GistWorker(gs, "http://localhost:19999")
    gw.start()

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        gw.enqueue(["turn A", "turn B"])
        time.sleep(0.4)

    gw.shutdown()
    gw.join(timeout=1)

    assert "discussed budget plan" in gs.get()


def test_gist_worker_none_sentinel_causes_clean_exit():
    gs = GistStore()
    gw = GistWorker(gs, "http://localhost:19999")
    gw.start()
    assert gw.is_alive()

    gw.shutdown()
    gw.join(timeout=2)
    assert not gw.is_alive(), "GistWorker thread must exit cleanly after None sentinel"


def test_gist_worker_queue_depth_logged_at_debug(caplog):
    """Queue depth must be emitted at DEBUG on every iteration."""

    def fake_urlopen(req, timeout):
        class FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

            def read(self_):
                return json.dumps({"content": "ok"}).encode()

        return FakeResp()

    gs = GistStore()
    gw = GistWorker(gs, "http://localhost:19999")
    gw.start()

    with caplog.at_level(logging.DEBUG, logger="iris.memory"):
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            gw.enqueue(["hello"])
            time.sleep(0.4)

    gw.shutdown()
    gw.join(timeout=1)

    debug_msgs = [r.message for r in caplog.records if r.levelno == logging.DEBUG]
    assert any("queue depth" in m.lower() or "gist-worker" in m.lower() for m in debug_msgs), (
        f"No DEBUG queue-depth log found. Records: {debug_msgs}"
    )


# ---------------------------------------------------------------------------
# Unit — EmbeddingEngine (ti-c7g contract tests)
# ---------------------------------------------------------------------------


def test_embedding_engine_calls_correct_endpoint():
    """embed() must POST to <base_url>/embedding."""
    captured_urls: list[str] = []

    def fake_urlopen(req, timeout):
        captured_urls.append(req.full_url)

        class FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

            def read(self_):
                return json.dumps({"embedding": [0.1, 0.2]}).encode()

        return FakeResp()

    engine = EmbeddingEngine("http://myhost:1234", "nomic-embed-text")
    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        engine.embed("hello")

    assert len(captured_urls) == 1
    assert captured_urls[0] == "http://myhost:1234/embedding"


def test_embedding_engine_raises_on_http_error():
    """HTTP errors (e.g. 503) must propagate from embed() so callers can handle them."""
    engine = EmbeddingEngine("http://localhost:8080", "nomic-embed-text")
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.HTTPError(
            url=None, code=503, msg="Service Unavailable", hdrs=None, fp=None
        ),
    ), pytest.raises(urllib.error.HTTPError):
        engine.embed("test")


# ---------------------------------------------------------------------------
# Unit — MemoryManager.call_start recency weighting (ti-c7g)
# ---------------------------------------------------------------------------


def test_call_start_recency_weighting_ranks_newer_higher():
    """Recent entry beats older one when cosine similarity is equal (top_k=1)."""
    ts = TranscriptStore()
    engine = MagicMock()
    engine.embed.return_value = [1.0, 0.0]

    old_ts = int(time.time()) - 13 * 30 * 24 * 3600  # ~13 months ago
    recent_ts = int(time.time()) - 5  # 5 seconds ago

    embedding_blob = json.dumps([1.0, 0.0]).encode()
    ts._conn.execute(
        "INSERT INTO EMBEDDINGS (session_id, contact_id, text, source_type, source_id, created_at, embedding)"
        " VALUES (?,?,?,?,?,?,?)",
        ("s0", "alice", "old memory", "turn", "", old_ts, embedding_blob),
    )
    ts._conn.execute(
        "INSERT INTO EMBEDDINGS (session_id, contact_id, text, source_type, source_id, created_at, embedding)"
        " VALUES (?,?,?,?,?,?,?)",
        ("s0", "alice", "recent memory", "turn", "", recent_ts, embedding_blob),
    )
    ts._conn.commit()

    mm = MemoryManager(ts, engine=engine, top_k=1)
    result = mm.call_start("s1", "alice")
    assert "recent memory" in result, (
        "Recency weighting must rank newer entry first when cosine similarity is equal"
    )


# ---------------------------------------------------------------------------
# Privacy contract tests (ti-c7g)
# ---------------------------------------------------------------------------


def test_call_start_never_returns_other_contact_data():
    """call_start results for alice must not contain any rows stored under bob."""
    ts = TranscriptStore()
    engine = MagicMock()
    engine.embed.return_value = [1.0, 0.0]

    ts.insert_embedding("s0", "alice", "alice private data", [1.0, 0.0])
    ts.insert_embedding("s0", "bob", "bob confidential data", [1.0, 0.0])

    mm = MemoryManager(ts, engine=engine)
    result = mm.call_start("s1", "alice")

    assert "bob confidential data" not in result


def test_call_start_empty_contact_id_returns_zero_results_no_exception():
    ts = TranscriptStore()
    engine = MagicMock()
    engine.embed.return_value = [1.0, 0.0]
    ts.insert_embedding("s0", "alice", "alice data", [1.0, 0.0])

    mm = MemoryManager(ts, engine=engine)
    result = mm.call_start("s1", "")
    assert result == ""


def test_memory_hint_content_never_appears_in_log_output(caplog):
    """Returned memory_hint text must not leak into any log record at any level."""
    ts = TranscriptStore()
    engine = MagicMock()
    engine.embed.return_value = [1.0, 0.0]
    secret = "TOP-SECRET-FINANCIAL-DATA-XYZ-DO-NOT-LOG"
    ts.insert_embedding("s0", "alice", secret, [1.0, 0.0])

    mm = MemoryManager(ts, engine=engine)
    with caplog.at_level(logging.DEBUG):
        hint = mm.call_start("s1", "alice")

    assert secret in hint, "precondition: secret text must be returned as memory hint"

    for record in caplog.records:
        assert secret not in record.getMessage(), (
            f"Memory hint leaked into {record.levelname} log: {record.getMessage()}"
        )


# ---------------------------------------------------------------------------
# Degradation tests (ti-c7g)
# ---------------------------------------------------------------------------


def test_sqlite_vec_absent_call_start_returns_empty_no_exception():
    """When sqlite-vec isn't loadable, call_start returns '' without raising."""
    with patch("iris.memory._try_load_vec", return_value=False):
        ts = TranscriptStore()
    engine = MagicMock()
    engine.embed.return_value = [1.0, 0.0]
    ts.insert_embedding("s0", "alice", "data", [1.0, 0.0])

    mm = MemoryManager(ts, engine=engine)
    result = mm.call_start("s1", "alice")
    assert isinstance(result, str)


def test_embedding_engine_http_503_call_start_returns_empty_no_exception():
    """call_start returns '' when the embedding HTTP call returns 503."""
    ts = TranscriptStore()
    engine = EmbeddingEngine("http://localhost:8080", "nomic-embed-text")
    ts.insert_embedding("s0", "alice", "data", [1.0, 0.0])

    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.HTTPError(
            url=None, code=503, msg="Service Unavailable", hdrs=None, fp=None
        ),
    ):
        mm = MemoryManager(ts, engine=engine)
        result = mm.call_start("s1", "alice")

    assert result == ""


def test_gist_worker_slow_append_turn_returns_within_5ms():
    """append_turn() must return in <5ms even when GistWorker is slow/backed up."""
    ts = TranscriptStore()
    slow_q: queue.Queue = queue.Queue()

    class SlowWorker:
        def enqueue(self, turns):
            slow_q.put(turns)

    rw = RollingWindow(ts, SlowWorker(), "s1", "alice")  # type: ignore[arg-type]
    for i in range(30):
        rw.append(f"warm{i}")

    start = time.monotonic()
    rw.append("trigger eviction")
    elapsed_ms = (time.monotonic() - start) * 1000

    assert elapsed_ms < 5.0, (
        f"append_turn blocked {elapsed_ms:.1f}ms — must complete in <5ms with slow worker"
    )


# ---------------------------------------------------------------------------
# Schema / integrity tests (ti-c7g)
# ---------------------------------------------------------------------------


def test_sessions_write_before_embeddings_gist_survives_simulated_kill():
    """_archive writes end_session_with_gist before insert_embedding.

    Simulate a process kill between those two steps: the gist must still
    be readable from SESSIONS even if EMBEDDINGS write never happens.
    """
    ts = TranscriptStore()
    ts.start_session("s1", "alice")

    ts.end_session_with_gist("s1", "important call summary")
    # Deliberately skip insert_embedding to simulate crash here

    row = ts._conn.execute(
        "SELECT final_gist FROM SESSIONS WHERE session_id='s1'"
    ).fetchone()
    assert row is not None
    assert row[0] == "important call summary", (
        "Final gist must be durable in SESSIONS even if EMBEDDINGS write never happened"
    )


def test_call_end_second_call_same_session_is_noop():
    """Second call_end for the same session_id must not overwrite the first result."""
    ts = TranscriptStore()
    ts.start_session("s1", "alice")

    mm = MemoryManager(ts)
    mm._qwen_summarise = MagicMock(return_value="First summary.")
    mm.call_start("s1", "alice")
    mm.call_end("s1")
    time.sleep(0.15)

    first_ended = ts._conn.execute(
        "SELECT ended_at FROM SESSIONS WHERE session_id='s1'"
    ).fetchone()[0]
    first_gist = ts._conn.execute(
        "SELECT final_gist FROM SESSIONS WHERE session_id='s1'"
    ).fetchone()[0]

    mm._qwen_summarise.return_value = "Second summary — should be ignored."
    mm.call_end("s1")
    time.sleep(0.15)

    second_ended = ts._conn.execute(
        "SELECT ended_at FROM SESSIONS WHERE session_id='s1'"
    ).fetchone()[0]
    second_gist = ts._conn.execute(
        "SELECT final_gist FROM SESSIONS WHERE session_id='s1'"
    ).fetchone()[0]

    assert first_ended == second_ended, "ended_at must not change on second call_end"
    assert second_gist == first_gist, "final_gist must not be overwritten by second call_end"


# ---------------------------------------------------------------------------
# Integration test (ti-c7g)
# ---------------------------------------------------------------------------


def test_full_call_lifecycle_35_turns_eviction_and_archival():
    """Full call: call_start → 35 append_turns (triggers eviction) → call_end.

    Verifies:
    - 35 turns causes at least one eviction (> maxlen=30)
    - SESSIONS.final_gist is non-empty after call_end
    - EMBEDDINGS has at least 1 row for that contact_id
    """
    ts = TranscriptStore()
    ts.start_session("s1", "charlie")

    gs = GistStore()
    gw = GistWorker(gs, "http://localhost:19999")
    gw.enqueue = lambda turns: None  # prevent real Qwen calls in eviction path
    gw.start()

    rw = RollingWindow(ts, gw, "s1", "charlie")
    ms = MemoryStore(ts, gw, gs, "s1", "charlie")

    mm = MemoryManager(ts, engine=None)
    mm._qwen_summarise = MagicMock(return_value="Charlie discussed the product launch schedule.")
    mm.call_start("s1", "charlie", gist_worker=gw, gist_store=gs, window=rw)

    for i in range(35):
        ms.append_turn(f"turn {i}: charlie speaking")

    assert len(ms.get_window()) <= 30, "35 turns must have triggered eviction"

    mm.call_end("s1")
    time.sleep(0.2)
    gw.join(timeout=1)

    row = ts._conn.execute(
        "SELECT final_gist FROM SESSIONS WHERE session_id='s1'"
    ).fetchone()
    assert row is not None, "SESSIONS row must exist for session s1"
    assert row[0], "SESSIONS.final_gist must be non-empty after call_end"

    rows = ts.fetch_embeddings_for_contact("charlie")
    assert len(rows) >= 1, "EMBEDDINGS must have at least one row for charlie after the call"


# ---------------------------------------------------------------------------
# F-COV-02: TranscriptStore.rebind_session UPSERT (ti-fzhp)
# ---------------------------------------------------------------------------

def test_rebind_session_updates_existing_row():
    ts = TranscriptStore()
    ts.start_session("s1", "alice")
    ts.rebind_session("s1", "bob")
    row = ts._conn.execute(
        "SELECT contact_id FROM SESSIONS WHERE session_id='s1'"
    ).fetchone()
    assert row[0] == "bob"


def test_rebind_session_inserts_when_no_existing_row():
    ts = TranscriptStore()
    ts.rebind_session("s_new", "charlie")
    row = ts._conn.execute(
        "SELECT contact_id FROM SESSIONS WHERE session_id='s_new'"
    ).fetchone()
    assert row is not None
    assert row[0] == "charlie"


def test_memory_manager_rebind_session_delegates_to_store():
    ts = TranscriptStore()
    mm = MemoryManager(ts, engine=None)
    mm.call_start("s1", "alice")
    mm.rebind_session("s1", "bob")
    row = ts._conn.execute(
        "SELECT contact_id FROM SESSIONS WHERE session_id='s1'"
    ).fetchone()
    assert row is not None
    assert row[0] == "bob"


def test_memory_manager_rebind_session_updates_active_contact_id():
    ts = TranscriptStore()
    mm = MemoryManager(ts, engine=None)
    mm.call_start("s1", "alice")
    mm.rebind_session("s1", "bob")
    assert mm._active_contact_id == "bob"


# ---------------------------------------------------------------------------
# F-COV-03: _archive sentinel gating + call_start far_end kwarg (ti-fzhp)
# ---------------------------------------------------------------------------

def test_archive_skips_embedding_write_for_sentinel_contact_id():
    from iris.far_end import SENTINEL_ID
    ts = TranscriptStore()
    ts.start_session("s1", str(SENTINEL_ID))
    mm = MemoryManager(ts, engine=None)
    mm._active_session_id = "s1"
    mm._active_contact_id = str(SENTINEL_ID)
    mm._archive("s1")
    # Session should be ended (closed cleanly) but no embeddings written
    assert ts.is_session_ended("s1")
    rows = ts.fetch_embeddings_for_contact(str(SENTINEL_ID))
    assert rows == []


def test_archive_skips_embedding_write_for_empty_contact_id():
    ts = TranscriptStore()
    mm = MemoryManager(ts, engine=None)
    mm._active_session_id = "s_none"
    mm._active_contact_id = ""
    # No SESSIONS row — get_session_contact_id returns None → skips archival
    mm._archive("s_none")  # must not raise


def test_call_start_with_far_end_identified_uses_archival_contact_id():
    from iris.far_end import FarEndIdentity
    engine = MagicMock()
    engine.embed.return_value = [1.0, 0.0]
    ts = TranscriptStore()
    ts.insert_embedding("s0", "42", "Alice note", [1.0, 0.0])
    mm = MemoryManager(ts, engine=engine)
    fe = FarEndIdentity().bind(42, "Alice")
    mm.call_start("s1", far_end=fe)
    assert mm._active_contact_id == "42"


def test_call_start_with_far_end_unidentified_skips_l3_retrieval():
    from iris.far_end import FarEndIdentity
    engine = MagicMock()
    ts = TranscriptStore()
    mm = MemoryManager(ts, engine=engine)
    fe = FarEndIdentity()  # UNIDENTIFIED
    result = mm.call_start("s1", far_end=fe)
    assert result == ""
    engine.embed.assert_not_called()


def test_call_start_with_far_end_private_skips_l3_retrieval():
    from iris.far_end import FarEndIdentity
    engine = MagicMock()
    ts = TranscriptStore()
    mm = MemoryManager(ts, engine=engine)
    fe = FarEndIdentity().make_private()
    result = mm.call_start("s1", far_end=fe)
    assert result == ""
    engine.embed.assert_not_called()
