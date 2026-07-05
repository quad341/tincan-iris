"""SQLite-backed persistence for Call Card AFTER writeback data — ti-hb2dx.

Connects to the same SQLite file as RosterStore (roster.db) so contact_id is a
real, enforced foreign key. Owns its own idempotent DDL (CREATE TABLE IF NOT
EXISTS, run on every connect), independent of RosterStore's own
_schema_version/migration chain — never touches iris/roster.py beyond
importing its DB path constant.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Literal

from iris.roster import _DEFAULT_PATH as _ROSTER_DB

_DDL = """
CREATE TABLE IF NOT EXISTS call_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id      INTEGER NOT NULL REFERENCES contacts(id),
    session_id      TEXT NOT NULL UNIQUE,
    started_at      REAL,
    ended_at        REAL,
    agent_name      TEXT NOT NULL DEFAULT '',
    disclosed_at    REAL,
    outcome_summary TEXT NOT NULL DEFAULT '',
    objective       TEXT,
    created_at      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS call_log_by_contact ON call_log(contact_id);

CREATE TABLE IF NOT EXISTS commitment (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id      INTEGER NOT NULL REFERENCES contacts(id),
    call_log_id     INTEGER NOT NULL REFERENCES call_log(id),
    direction       TEXT NOT NULL CHECK (direction IN ('they_promised', 'i_promised')),
    description     TEXT NOT NULL,
    amount          TEXT,
    due_date        TEXT,
    status          TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','honored','broken','cancelled')),
    source_turn_id  INTEGER,
    source_offset_s REAL,
    captured_at     REAL NOT NULL,
    resolved_at     REAL
);
CREATE INDEX IF NOT EXISTS commitment_by_contact_status ON commitment(contact_id, status);

CREATE TABLE IF NOT EXISTS contact_fact (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id         INTEGER NOT NULL REFERENCES contacts(id),
    fact_type          TEXT NOT NULL,
    normalized_value   TEXT NOT NULL,
    label              TEXT NOT NULL DEFAULT '',
    first_seen_session TEXT,
    last_confirmed_at  REAL NOT NULL,
    UNIQUE (contact_id, fact_type, normalized_value)
);
CREATE INDEX IF NOT EXISTS contact_fact_by_contact ON contact_fact(contact_id);
"""


class AfterStore:
    """SQLite WAL store for post-call writeback (call_log, commitment, contact_fact).

    Thread-safe via threading.Lock + check_same_thread=False, same convention
    as CallCardStore. Lifetime: one instance owned by CallCardHost for the
    daemon process.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        path = Path(db_path) if db_path is not None else _ROSTER_DB
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(_DDL)
            self._conn.commit()

    def insert_call_log(
        self,
        contact_id: int,
        session_id: str,
        started_at: float | None,
        ended_at: float | None,
        agent_name: str,
        disclosed_at: float | None,
        outcome_summary: str,
    ) -> int:
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO call_log
                    (contact_id, session_id, started_at, ended_at, agent_name,
                     disclosed_at, outcome_summary, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (contact_id, session_id, started_at, ended_at, agent_name,
                 disclosed_at, outcome_summary, time.time()),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def insert_commitment(
        self,
        contact_id: int,
        call_log_id: int,
        direction: Literal["they_promised", "i_promised"],
        description: str,
        amount: str | None,
        due_date: str | None,
        source_turn_id: int | None,
        source_offset_s: float | None,
    ) -> int:
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO commitment
                    (contact_id, call_log_id, direction, description, amount, due_date,
                     source_turn_id, source_offset_s, captured_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (contact_id, call_log_id, direction, description, amount, due_date,
                 source_turn_id, source_offset_s, time.time()),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def upsert_contact_fact(
        self,
        contact_id: int,
        fact_type: str,
        normalized_value: str,
        label: str,
        session_id: str,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO contact_fact
                    (contact_id, fact_type, normalized_value, label, first_seen_session, last_confirmed_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(contact_id, fact_type, normalized_value)
                DO UPDATE SET last_confirmed_at=excluded.last_confirmed_at
                """,
                (contact_id, fact_type, normalized_value, label, session_id, time.time()),
            )
            self._conn.commit()

    def resolve_commitment(
        self, commitment_id: int, status: Literal["honored", "broken", "cancelled"]
    ) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE commitment SET status=?, resolved_at=? WHERE id=?",
                (status, time.time(), commitment_id),
            )
            self._conn.commit()

    def get_contact_facts(self, contact_id: int) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM contact_fact WHERE contact_id=? ORDER BY last_confirmed_at DESC",
                (contact_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_open_commitments(self, contact_id: int) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM commitment WHERE contact_id=? AND status='open' ORDER BY captured_at",
                (contact_id,),
            ).fetchall()
            return [dict(r) for r in rows]
