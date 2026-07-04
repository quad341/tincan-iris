"""SQLite WAL-backed persistence for the Call Card — ti-rnlqo.3.1.

enrichment_done values: 0=pending/skipped, 1=success, 2=failed (INTEGER, not bool).
Amendment applied (2026-06-30): mark_enrichment_done(session_id, status=1),
upsert_enriched_action_item, get_call_card.enrichment_done is int.

disclosure_state values: 'pending' (default) / 'disclosed' / 'skipped'.
Amendment applied (2026-07-03, ti-ir12t): tri-state disclosure tracking, so an
audit can distinguish "operator declined" from "call ended before they responded".
disclosure_ack (bool) is kept for compatibility with existing callers/tests and
stays in sync with disclosure_state via mark_disclosure_ack/mark_disclosure_skipped.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from iris.capture.schemas import ActionItem, CapturedFact

_DEFAULT_DB = Path.home() / ".local" / "share" / "iris" / "call_cards.db"

_DDL = """
CREATE TABLE IF NOT EXISTS call_cards (
    session_id        TEXT PRIMARY KEY,
    caller_number     TEXT,
    contact_id        TEXT,
    context_notes     TEXT,
    disclosure_ack    INTEGER DEFAULT 0,
    disclosure_ack_ts REAL,
    disclosure_state  TEXT DEFAULT 'pending',
    enrichment_done   INTEGER DEFAULT 0,
    started_at        REAL,
    ended_at          REAL,
    created_at        REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS captured_facts (
    id                  TEXT PRIMARY KEY,
    session_id          TEXT NOT NULL REFERENCES call_cards(session_id),
    fact_type           TEXT,
    raw_text            TEXT,
    normalized_value    TEXT,
    critical            INTEGER,
    confidence          REAL,
    confirmed           INTEGER,
    transcript_turn_id  INTEGER,
    transcript_offset_s REAL,
    speaker             TEXT,
    source_layer        INTEGER DEFAULT 1,
    created_at          REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS action_items (
    id                  TEXT PRIMARY KEY,
    session_id          TEXT NOT NULL REFERENCES call_cards(session_id),
    description         TEXT,
    trigger             TEXT,
    owner               TEXT,
    due_date            TEXT,
    confidence          REAL,
    confirmed           INTEGER,
    transcript_turn_id  INTEGER,
    transcript_offset_s REAL,
    speaker             TEXT,
    source_layer        INTEGER DEFAULT 1,
    created_at          REAL NOT NULL
);
"""


class CallCardStore:
    """SQLite WAL store for call-card data (facts, action items, metadata).

    Thread-safe via threading.Lock + check_same_thread=False.
    Lifetime: typically one daemon process; one instance per iris session.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        path = Path(db_path) if db_path is not None else _DEFAULT_DB
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(_DDL)
            self._migrate_disclosure_state()
            self._conn.commit()

    def _migrate_disclosure_state(self) -> None:
        # call_cards predates disclosure_state; back-fill it for DBs created before
        # this column existed so disclosure_ack and disclosure_state never disagree.
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(call_cards)").fetchall()}
        if "disclosure_state" not in cols:
            self._conn.execute(
                "ALTER TABLE call_cards ADD COLUMN disclosure_state TEXT DEFAULT 'pending'"
            )
            self._conn.execute(
                "UPDATE call_cards SET disclosure_state='disclosed' WHERE disclosure_ack=1"
            )

    # ── Session lifecycle ─────────────────────────────────────────

    def load_or_create(
        self,
        session_id: str,
        caller_number: str,
        contact_id: str | None = None,
        context_notes: str | None = None,
    ) -> None:
        """Idempotent: creates a call_card row if one doesn't exist for session_id."""
        now = time.time()
        with self._lock:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO call_cards
                    (session_id, caller_number, contact_id, context_notes, started_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, caller_number, contact_id, context_notes, now, now),
            )
            self._conn.commit()

    def mark_ended(self, session_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE call_cards SET ended_at=? WHERE session_id=?",
                (time.time(), session_id),
            )
            self._conn.commit()

    def mark_disclosure_ack(self, session_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE call_cards SET disclosure_ack=?, disclosure_ack_ts=?, disclosure_state=? WHERE session_id=?",
                (1, time.time(), "disclosed", session_id),
            )
            self._conn.commit()

    def mark_disclosure_skipped(self, session_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE call_cards SET disclosure_ack_ts=?, disclosure_state=? WHERE session_id=?",
                (time.time(), "skipped", session_id),
            )
            self._conn.commit()

    def mark_enrichment_done(self, session_id: str, status: int = 1) -> None:
        """status: 1=success, 2=failed (0=pending is the default)."""
        with self._lock:
            self._conn.execute(
                "UPDATE call_cards SET enrichment_done=? WHERE session_id=?",
                (status, session_id),
            )
            self._conn.commit()

    # ── Facts ─────────────────────────────────────────────────────

    def add_fact(self, fact: CapturedFact) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO captured_facts
                    (id, session_id, fact_type, raw_text, normalized_value, critical,
                     confidence, confirmed, transcript_turn_id, transcript_offset_s,
                     speaker, source_layer, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fact.id, fact.session_id, fact.fact_type.value, fact.raw_text,
                    fact.normalized_value, int(fact.critical), fact.confidence,
                    None if fact.confirmed is None else int(fact.confirmed),
                    fact.transcript_turn_id, fact.transcript_offset_s,
                    fact.speaker, fact.source_layer, fact.created_at,
                ),
            )
            self._conn.commit()

    def confirm_fact(
        self, fact_id: str, confirmed: bool, normalized_value: str | None = None
    ) -> None:
        with self._lock:
            if normalized_value is not None:
                self._conn.execute(
                    "UPDATE captured_facts SET confirmed=?, normalized_value=? WHERE id=?",
                    (int(confirmed), normalized_value, fact_id),
                )
            else:
                self._conn.execute(
                    "UPDATE captured_facts SET confirmed=? WHERE id=?",
                    (int(confirmed), fact_id),
                )
            self._conn.commit()

    # ── Action items ──────────────────────────────────────────────

    def add_action_item(self, item: ActionItem) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO action_items
                    (id, session_id, description, trigger, owner, due_date, confidence,
                     confirmed, transcript_turn_id, transcript_offset_s, speaker,
                     source_layer, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.id, item.session_id, item.description, item.trigger,
                    item.owner, item.due_date, item.confidence,
                    None if item.confirmed is None else int(item.confirmed),
                    item.transcript_turn_id, item.transcript_offset_s,
                    item.speaker, item.source_layer, item.created_at,
                ),
            )
            self._conn.commit()

    def confirm_action_item(
        self,
        item_id: str,
        confirmed: bool,
        description: str | None = None,
        due_date: str | None = None,
    ) -> None:
        with self._lock:
            updates: list[Any] = [int(confirmed)]
            clauses: list[str] = ["confirmed=?"]
            if description is not None:
                clauses.append("description=?")
                updates.append(description)
            if due_date is not None:
                clauses.append("due_date=?")
                updates.append(due_date)
            updates.append(item_id)
            self._conn.execute(
                f"UPDATE action_items SET {', '.join(clauses)} WHERE id=?",
                updates,
            )
            self._conn.commit()

    def upsert_enriched_action_item(
        self,
        session_id: str,
        turn_id: int,
        description: str,
        owner: str,
        due_date: str | None,
        confidence: float,
    ) -> None:
        """Update the L1 action item for (session_id, turn_id); insert with source_layer=3 if absent."""
        now = time.time()
        with self._lock:
            cur = self._conn.execute(
                """
                UPDATE action_items
                SET description=?, owner=?, due_date=?, confidence=?
                WHERE session_id=? AND transcript_turn_id=? AND source_layer=1
                """,
                (description, owner, due_date, confidence, session_id, turn_id),
            )
            if cur.rowcount == 0:
                from uuid import uuid4
                self._conn.execute(
                    """
                    INSERT INTO action_items
                        (id, session_id, description, trigger, owner, due_date,
                         confidence, transcript_turn_id, transcript_offset_s,
                         speaker, source_layer, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (uuid4().hex, session_id, description, "", owner, due_date,
                     confidence, turn_id, 0.0, "", 3, now),
                )
            self._conn.commit()

    # ── Read ──────────────────────────────────────────────────────

    def get_call_card(self, session_id: str) -> dict:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM call_cards WHERE session_id=?", (session_id,)
            ).fetchone()
            if row is None:
                return {}
            facts = [
                dict(r)
                for r in self._conn.execute(
                    "SELECT * FROM captured_facts WHERE session_id=? ORDER BY transcript_turn_id, created_at",
                    (session_id,),
                ).fetchall()
            ]
            items = [
                dict(r)
                for r in self._conn.execute(
                    "SELECT * FROM action_items WHERE session_id=? ORDER BY transcript_turn_id, created_at",
                    (session_id,),
                ).fetchall()
            ]
            return {
                "session_id": session_id,
                "facts": facts,
                "action_items": items,
                "disclosure_ack": bool(row["disclosure_ack"]),
                "disclosure_state": row["disclosure_state"],
                "enrichment_done": int(row["enrichment_done"]),
            }
