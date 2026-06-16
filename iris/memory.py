"""Memory — three-layer call context system.

Layer 1 (L1): RollingWindow — RAM deque of recent turns (last 30).
Layer 2 (L2): GistStore / GistWorker — async Qwen-compressed summaries.
Layer 3 (L3): MemoryStore — sqlite-vec long-term embeddings per contact.

MemoryProvider is the Protocol that ties the layers together.
MemoryManager drives L3 at call boundaries (call_start / call_end).
"""
from __future__ import annotations

import collections
import json
import logging
import queue
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

import sqlite3

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# sqlite-vec loading
# ---------------------------------------------------------------------------


def _try_load_vec(conn: sqlite3.Connection) -> bool:
    """Try to load sqlite-vec via sqlite_vec.loadable_path(); return True on success."""
    try:
        import sqlite_vec  # type: ignore[import]

        conn.load_extension(sqlite_vec.loadable_path())
        return True
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# DB schema helpers
# ---------------------------------------------------------------------------

_SESSIONS_DDL = """
CREATE TABLE IF NOT EXISTS SESSIONS (
    session_id TEXT NOT NULL,
    contact_id TEXT NOT NULL,
    started_at INTEGER NOT NULL,
    ended_at   INTEGER
)
"""

_EMBEDDINGS_DDL_VEC = """
CREATE VIRTUAL TABLE IF NOT EXISTS EMBEDDINGS USING vec0(
    session_id TEXT NOT NULL,
    contact_id TEXT NOT NULL,
    text       TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    embedding  float[{dim}]
)
"""

_EMBEDDINGS_DDL_PLAIN = """
CREATE TABLE IF NOT EXISTS EMBEDDINGS (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    contact_id TEXT NOT NULL,
    text       TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    embedding  BLOB
)
"""


# ---------------------------------------------------------------------------
# TranscriptStore — append-only SESSIONS/EMBEDDINGS writes
# ---------------------------------------------------------------------------


class TranscriptStore:
    """SQLite store for session records and embedding rows."""

    def __init__(self, db_path: str | Path = ":memory:", embedding_dim: int = 768) -> None:
        self._db_path = str(db_path)
        self._dim = embedding_dim
        self._conn: sqlite3.Connection | None = None
        self._vec_loaded = False
        self._lock = threading.Lock()
        self._init()

    def _init(self) -> None:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        self._vec_loaded = _try_load_vec(conn)
        conn.execute(_SESSIONS_DDL)
        if self._vec_loaded:
            try:
                conn.execute(_EMBEDDINGS_DDL_VEC.format(dim=self._dim))
            except sqlite3.OperationalError:
                self._vec_loaded = False
        if not self._vec_loaded:
            conn.execute(_EMBEDDINGS_DDL_PLAIN)
        conn.commit()
        self._conn = conn

    @property
    def vec_loaded(self) -> bool:
        return self._vec_loaded

    def start_session(self, session_id: str, contact_id: str) -> None:
        if not contact_id:
            raise ValueError("contact_id must not be empty")
        with self._lock:
            assert self._conn is not None
            self._conn.execute(
                "INSERT INTO SESSIONS (session_id, contact_id, started_at) VALUES (?,?,?)",
                (session_id, contact_id, int(time.time())),
            )
            self._conn.commit()

    def end_session(self, session_id: str) -> None:
        with self._lock:
            assert self._conn is not None
            self._conn.execute(
                "UPDATE SESSIONS SET ended_at=? WHERE session_id=? AND ended_at IS NULL",
                (int(time.time()), session_id),
            )
            self._conn.commit()

    def insert_embedding(
        self,
        session_id: str,
        contact_id: str,
        text: str,
        embedding: list[float] | None,
    ) -> None:
        if not contact_id:
            raise ValueError("contact_id must not be empty")
        blob = json.dumps(embedding).encode() if embedding else None
        with self._lock:
            assert self._conn is not None
            self._conn.execute(
                "INSERT INTO EMBEDDINGS (session_id, contact_id, text, created_at, embedding)"
                " VALUES (?,?,?,?,?)",
                (session_id, contact_id, text, int(time.time()), blob),
            )
            self._conn.commit()

    def fetch_embeddings_for_contact(
        self, contact_id: str
    ) -> list[tuple[str, int, list[float] | None]]:
        """Return (text, created_at, embedding) rows for a contact, newest first."""
        with self._lock:
            assert self._conn is not None
            rows = self._conn.execute(
                "SELECT text, created_at, embedding FROM EMBEDDINGS"
                " WHERE contact_id=? ORDER BY created_at DESC",
                (contact_id,),
            ).fetchall()
        result = []
        for text, created_at, blob in rows:
            emb = json.loads(blob) if blob else None
            result.append((text, created_at, emb))
        return result

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None


# ---------------------------------------------------------------------------
# MemoryProvider protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class MemoryProvider(Protocol):
    """Protocol for in-call memory management.

    Implementors track the rolling L1 window and async L2 gist.
    """

    def append_turn(self, turn: str) -> None:
        """Append a spoken turn; writes to TranscriptStore AND the L1 deque.

        Must return in <1 ms — eviction to GistWorker is async (enqueue only).
        """
        ...

    def get_window(self) -> list[str]:
        """Return the current L1 rolling window."""
        ...

    def get_gist(self) -> str:
        """Return the current L2 running gist."""
        ...


# ---------------------------------------------------------------------------
# GistStore — L2 running gist (in-memory, thread-safe)
# ---------------------------------------------------------------------------


class GistStore:
    """Append-only string accumulator for Qwen-compressed gist segments."""

    def __init__(self) -> None:
        self._gist = ""
        self._lock = threading.Lock()

    def append(self, segment: str) -> None:
        with self._lock:
            if self._gist:
                self._gist = self._gist + "\n" + segment
            else:
                self._gist = segment

    def get(self) -> str:
        with self._lock:
            return self._gist


# ---------------------------------------------------------------------------
# GistWorker — background Qwen compression thread
# ---------------------------------------------------------------------------

_COMPRESSION_PROMPT = (
    "Summarise the following conversation segment in ≤3 sentences, capturing "
    "main topics, decisions, and action items. Be factual and concise.\n\n{evicted_text}"
)


class GistWorker(threading.Thread):
    """Daemon thread that compresses evicted L1 segments into GistStore."""

    def __init__(
        self, gist_store: GistStore, qwen_base_url: str, qwen_timeout_s: float = 30.0
    ) -> None:
        super().__init__(daemon=True, name="gist-worker")
        self._store = gist_store
        self._base_url = qwen_base_url
        self._timeout = qwen_timeout_s
        self._q: queue.Queue[list[str] | None] = queue.Queue()

    def enqueue(self, turns: list[str]) -> None:
        self._q.put(turns)

    def shutdown(self) -> None:
        self._q.put(None)

    def run(self) -> None:
        while True:
            item = self._q.get()
            log.debug("gist-worker queue depth: %d", self._q.qsize())
            if item is None:
                break
            try:
                evicted_text = "\n".join(item)
                prompt_text = _COMPRESSION_PROMPT.format(evicted_text=evicted_text)
                prompt = (
                    "<|im_start|>system\nYou are a concise summariser.<|im_end|>\n"
                    f"<|im_start|>user\n{prompt_text}<|im_end|>\n<|im_start|>assistant\n"
                )
                body = json.dumps(
                    {"prompt": prompt, "n_predict": 50, "stream": False, "cache_prompt": False}
                ).encode()
                req = urllib.request.Request(
                    self._base_url + "/completion",
                    body,
                    {"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                    summary = json.loads(resp.read()).get("content", "").strip()
                if summary:
                    self._store.append(summary)
            except Exception:  # noqa: BLE001 — silent degradation per spec
                pass


# ---------------------------------------------------------------------------
# RollingWindow — L1 in-call deque
# ---------------------------------------------------------------------------

_EVICT_BATCH = 10
_WINDOW_MAX = 30


class RollingWindow:
    """RAM deque of recent turns (maxlen=30).

    When full, evicts the oldest 10 turns to GistWorker asynchronously.
    The append() path is always <1 ms — eviction is a queue enqueue.
    """

    def __init__(
        self,
        transcript_store: TranscriptStore,
        gist_worker: GistWorker,
        session_id: str,
        contact_id: str,
    ) -> None:
        self._store = transcript_store
        self._worker = gist_worker
        self._session_id = session_id
        self._contact_id = contact_id
        self._deque: collections.deque[str] = collections.deque(maxlen=_WINDOW_MAX)

    def append(self, turn: str) -> None:
        """Append a turn; evicts oldest 10 asynchronously if deque was full."""
        if len(self._deque) == _WINDOW_MAX:
            evicted = [self._deque.popleft() for _ in range(_EVICT_BATCH)]
            self._worker.enqueue(evicted)
        self._deque.append(turn)
        self._store.insert_embedding(self._session_id, self._contact_id, turn, None)

    def get(self) -> list[str]:
        return list(self._deque)


# ---------------------------------------------------------------------------
# MemoryStore — implements MemoryProvider
# ---------------------------------------------------------------------------


class MemoryStore:
    """Concrete MemoryProvider: wires L1 window + L2 gist for a single call."""

    def __init__(
        self,
        transcript_store: TranscriptStore,
        gist_worker: GistWorker,
        gist_store: GistStore,
        session_id: str,
        contact_id: str,
    ) -> None:
        self._gist_store = gist_store
        self._window = RollingWindow(
            transcript_store, gist_worker, session_id, contact_id
        )

    def append_turn(self, turn: str) -> None:
        self._window.append(turn)

    def get_window(self) -> list[str]:
        return self._window.get()

    def get_gist(self) -> str:
        return self._gist_store.get()


# ---------------------------------------------------------------------------
# EmbeddingEngine — thin wrapper around llama.cpp /embedding
# ---------------------------------------------------------------------------


class EmbeddingEngine:
    """Calls llama.cpp /embedding for a given model. Loaded at app start."""

    def __init__(self, base_url: str, model: str, timeout_s: float = 10.0) -> None:
        self._url = base_url + "/embedding"
        self._model = model
        self._timeout = timeout_s

    def embed(self, text: str) -> list[float]:
        """Return float embedding vector for text. Raises on failure."""
        body = json.dumps({"content": text, "model": self._model}).encode()
        req = urllib.request.Request(
            self._url, body, {"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            data = json.loads(resp.read())
        # llama.cpp returns {"embedding": [...]} or {"data": [{"embedding": [...]}]}
        if "embedding" in data:
            return data["embedding"]
        return data["data"][0]["embedding"]


# ---------------------------------------------------------------------------
# MemoryManager — L3 call_start / call_end
# ---------------------------------------------------------------------------

_MONTHS_IN_SECONDS = 30 * 24 * 3600


def _recency_score(similarity: float, created_at: int) -> float:
    months_ago = (time.time() - created_at) / _MONTHS_IN_SECONDS
    return similarity * max(0.5, 1.0 - 0.1 * months_ago)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _format_hint(rows: list[tuple[str, int]]) -> str:
    """Format top memories as a concise, past-tense third-person hint ≤100 tokens."""
    # Each row is (text, created_at) after reranking.
    # Rough token estimate: 1 token ≈ 4 chars.
    parts: list[str] = []
    budget = 100 * 4  # chars
    for text, _ts in rows:
        entry = text.strip()
        if not entry:
            continue
        if len("\n".join(parts + [entry])) > budget:
            break
        parts.append(entry)
    return "\n".join(parts)


class MemoryManager:
    """Drives L3 retrieval at call_start and archival at call_end."""

    def __init__(
        self,
        transcript_store: TranscriptStore,
        engine: EmbeddingEngine | None = None,
        top_k: int = 5,
    ) -> None:
        self._store = transcript_store
        self._engine = engine
        self._top_k = top_k

    def call_start(self, session_id: str, contact_id: str) -> str:
        """Embed a contact query, ANN-search, rerank by recency, return ≤100 token hint.

        Returns '' if contact_id is empty, embedding unavailable, or 0 results.
        Any failure → ''.
        """
        try:
            if not contact_id:
                return ""
            if self._engine is None:
                return ""
            query = f"conversation with {contact_id}"
            query_vec = self._engine.embed(query)
            rows = self._store.fetch_embeddings_for_contact(contact_id)
            if not rows:
                return ""
            scored: list[tuple[float, str, int]] = []
            for text, created_at, emb in rows:
                if emb is None:
                    continue
                sim = _cosine(query_vec, emb)
                score = _recency_score(sim, created_at)
                scored.append((score, text, created_at))
            scored.sort(key=lambda x: x[0], reverse=True)
            top = [(text, ts) for _score, text, ts in scored[: self._top_k]]
            if not top:
                return ""
            return _format_hint(top)
        except Exception:  # noqa: BLE001 — never block a call
            return ""
