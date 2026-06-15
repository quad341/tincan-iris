"""CallList data layer — SQLite models for live-call scratchpad lists.

Tables are created in the same database as the transcript store (ti-ccc.12)
so the call session ties everything together with a single ``session_id``.

Schema:

    call_lists        — one per call, active or complete
    list_items        — items on a list (ordered by position)
    lookup_results    — enrichment data attached to an item (e.g. price check)

Retention: rows older than ``retention_days`` (default 90) are deleted by
``CallListStore.prune()``. The caller is responsible for scheduling pruning.
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .transcript import _DEFAULT_PATH as _TRANSCRIPT_DB

_DDL = """
CREATE TABLE IF NOT EXISTS call_lists (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT    NOT NULL,
    title      TEXT    NOT NULL DEFAULT 'Shopping list',
    status     TEXT    NOT NULL DEFAULT 'active'  CHECK(status IN ('active','complete')),
    created_at REAL    NOT NULL,
    updated_at REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS call_lists_session ON call_lists(session_id);

CREATE TABLE IF NOT EXISTS list_items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    list_id    INTEGER NOT NULL REFERENCES call_lists(id) ON DELETE CASCADE,
    text       TEXT    NOT NULL,
    checked    INTEGER NOT NULL DEFAULT 0,
    position   INTEGER NOT NULL DEFAULT 0,
    created_at REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS list_items_list ON list_items(list_id, position);

CREATE TABLE IF NOT EXISTS lookup_results (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    list_item_id INTEGER NOT NULL REFERENCES list_items(id) ON DELETE CASCADE,
    source       TEXT    NOT NULL,
    text         TEXT    NOT NULL,
    timestamp    REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS lookup_results_item ON lookup_results(list_item_id);
"""

_DEFAULT_RETENTION_DAYS = 90


@dataclass
class CallList:
    id: int
    session_id: str
    title: str
    status: Literal["active", "complete"]
    created_at: float
    updated_at: float


@dataclass
class ListItem:
    id: int
    list_id: int
    text: str
    checked: bool
    position: int
    created_at: float


@dataclass
class LookupResult:
    id: int
    list_item_id: int
    source: str
    text: str
    timestamp: float


class CallListStore:
    """CRUD for call lists, items, and lookup results.

    Uses the same on-disk SQLite file as ``TranscriptStore`` so a single
    database holds the full call record.
    """

    def __init__(self, path: str | Path | None = None,
                 retention_days: int = _DEFAULT_RETENTION_DAYS) -> None:
        self.path = Path(path) if path else _TRANSCRIPT_DB
        self.retention_days = retention_days

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(_DDL)
        return conn

    # --- CallList CRUD ---

    def create_list(self, session_id: str, title: str = "Shopping list") -> CallList:
        now = time.time()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO call_lists (session_id, title, status, created_at, updated_at) "
                "VALUES (?,?,?,?,?)",
                (session_id, title, "active", now, now),
            )
            return CallList(cur.lastrowid, session_id, title, "active", now, now)

    def get_list(self, list_id: int) -> CallList | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM call_lists WHERE id=?", (list_id,)).fetchone()
        if row is None:
            return None
        return CallList(**{k: row[k] for k in ("id", "session_id", "title", "created_at", "updated_at")},
                        status=row["status"])

    def active_list(self, session_id: str) -> CallList | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM call_lists WHERE session_id=? AND status='active' "
                "ORDER BY created_at DESC LIMIT 1",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return CallList(**{k: row[k] for k in ("id", "session_id", "title", "created_at", "updated_at")},
                        status=row["status"])

    def complete_list(self, list_id: int) -> bool:
        now = time.time()
        with self._connect() as conn:
            n = conn.execute(
                "UPDATE call_lists SET status='complete', updated_at=? WHERE id=?",
                (now, list_id),
            ).rowcount
        return n > 0

    # --- ListItem CRUD ---

    def add_item(self, list_id: int, text: str) -> ListItem:
        now = time.time()
        with self._connect() as conn:
            pos = (conn.execute(
                "SELECT COALESCE(MAX(position),0)+1 FROM list_items WHERE list_id=?", (list_id,)
            ).fetchone()[0])
            cur = conn.execute(
                "INSERT INTO list_items (list_id, text, checked, position, created_at) VALUES (?,?,0,?,?)",
                (list_id, text.strip(), pos, now),
            )
            conn.execute("UPDATE call_lists SET updated_at=? WHERE id=?", (now, list_id))
            return ListItem(cur.lastrowid, list_id, text.strip(), False, pos, now)

    def get_items(self, list_id: int) -> list[ListItem]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM list_items WHERE list_id=? ORDER BY position", (list_id,)
            ).fetchall()
        return [ListItem(r["id"], r["list_id"], r["text"], bool(r["checked"]),
                         r["position"], r["created_at"]) for r in rows]

    def check_item(self, item_id: int, *, checked: bool = True) -> bool:
        with self._connect() as conn:
            n = conn.execute(
                "UPDATE list_items SET checked=? WHERE id=?", (int(checked), item_id)
            ).rowcount
        return n > 0

    def remove_item(self, item_id: int) -> bool:
        with self._connect() as conn:
            n = conn.execute("DELETE FROM list_items WHERE id=?", (item_id,)).rowcount
        return n > 0

    # --- LookupResult CRUD ---

    def add_lookup(self, list_item_id: int, source: str, text: str) -> LookupResult:
        now = time.time()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO lookup_results (list_item_id, source, text, timestamp) VALUES (?,?,?,?)",
                (list_item_id, source, text, now),
            )
            return LookupResult(cur.lastrowid, list_item_id, source, text, now)

    def get_lookups(self, list_item_id: int) -> list[LookupResult]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM lookup_results WHERE list_item_id=? ORDER BY timestamp",
                (list_item_id,),
            ).fetchall()
        return [LookupResult(r["id"], r["list_item_id"], r["source"], r["text"], r["timestamp"])
                for r in rows]

    # --- retention ---

    def prune(self) -> int:
        """Delete lists (and cascading items/lookups) older than retention_days.

        Returns the number of lists deleted.
        """
        cutoff = time.time() - self.retention_days * 86400
        with self._connect() as conn:
            n = conn.execute(
                "DELETE FROM call_lists WHERE created_at < ?", (cutoff,)
            ).rowcount
        return n
