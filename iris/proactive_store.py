"""Proactive notification queue — SQLite CRUD layer (ti-ccc.17.2.2).

Stores ProactiveItem rows in the shared transcript DB (same WAL file as
TranscriptStore and CallListStore).  expires_at is set at enqueue time to
``created_at + 86400`` (24h TTL); it is not reset on delivery or dismissal.

Priority convention: lower number = higher urgency (0=critical, 4=backlog).
next_pending() returns items with priority <= min_priority so callers can
say "show me everything at P2 or more important" with min_priority=2.
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass

from .transcript import _DEFAULT_PATH as _TRANSCRIPT_DB

_DDL = """
CREATE TABLE IF NOT EXISTS proactive_queue (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger_class TEXT    NOT NULL,
    priority      INTEGER NOT NULL DEFAULT 2,
    message       TEXT    NOT NULL,
    source_skill  TEXT    NOT NULL DEFAULT '',
    source_id     TEXT,
    created_at    REAL    NOT NULL,
    expires_at    REAL    NOT NULL,
    delivered_at  REAL,
    dismissed     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS proactive_pending
    ON proactive_queue(trigger_class, priority, created_at)
    WHERE delivered_at IS NULL AND dismissed = 0;
"""

_TTL_SECONDS = 86400.0


@dataclass
class ProactiveItem:
    id: int
    trigger_class: str
    priority: int
    message: str
    source_skill: str
    source_id: str | None
    created_at: float
    expires_at: float
    delivered_at: float | None
    dismissed: bool


class ProactiveStore:
    """CRUD for the proactive notification queue.

    Uses the same on-disk SQLite file as ``TranscriptStore`` so a single
    database holds the full call record.
    """

    def __init__(self, path=None) -> None:
        from pathlib import Path
        self.path = Path(path) if path else _TRANSCRIPT_DB

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_DDL)
        return conn

    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> ProactiveItem:
        return ProactiveItem(
            id=row["id"],
            trigger_class=row["trigger_class"],
            priority=row["priority"],
            message=row["message"],
            source_skill=row["source_skill"],
            source_id=row["source_id"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            delivered_at=row["delivered_at"],
            dismissed=bool(row["dismissed"]),
        )

    def enqueue(
        self,
        proto: ProactiveItem | None = None,
        *,
        trigger_class: str | None = None,
        priority: int = 2,
        message: str | None = None,
        source_skill: str = "",
        source_id: str | None = None,
    ) -> ProactiveItem:
        """Insert a new item; returns the stored ProactiveItem with id and timestamps.

        Accepts either a ProactiveItem proto (positional) or keyword arguments.
        When a proto is supplied, its fields take precedence over any kwargs.
        """
        if proto is not None:
            trigger_class = proto.trigger_class
            priority = proto.priority
            message = proto.message
            source_skill = proto.source_skill
            source_id = proto.source_id
        if trigger_class is None or message is None:
            raise ValueError("trigger_class and message are required")
        now = time.time()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO proactive_queue "
                "(trigger_class, priority, message, source_skill, source_id, "
                " created_at, expires_at, delivered_at, dismissed) "
                "VALUES (?,?,?,?,?,?,?,NULL,0)",
                (trigger_class, priority, message, source_skill, source_id,
                 now, now + _TTL_SECONDS),
            )
            return ProactiveItem(
                id=cur.lastrowid,
                trigger_class=trigger_class,
                priority=priority,
                message=message,
                source_skill=source_skill,
                source_id=source_id,
                created_at=now,
                expires_at=now + _TTL_SECONDS,
                delivered_at=None,
                dismissed=False,
            )

    def next_pending(
        self,
        trigger_classes: tuple[str, ...] | list[str],
        min_priority: int = 4,
    ) -> ProactiveItem | None:
        """Return the highest-priority, oldest pending item matching the filters.

        Items pass if priority <= min_priority (lower number = higher urgency).
        Filters out delivered, dismissed, and expired items.
        """
        if not trigger_classes:
            return None
        placeholders = ",".join("?" * len(trigger_classes))
        now = time.time()
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT * FROM proactive_queue "
                f"WHERE trigger_class IN ({placeholders}) "
                f"  AND priority <= ? "
                f"  AND delivered_at IS NULL "
                f"  AND dismissed = 0 "
                f"  AND expires_at > ? "
                f"ORDER BY priority ASC, created_at ASC "
                f"LIMIT 1",
                (*trigger_classes, min_priority, now),
            ).fetchone()
        return self._row_to_item(row) if row else None

    def mark_delivered(self, item_id: int) -> bool:
        with self._connect() as conn:
            n = conn.execute(
                "UPDATE proactive_queue SET delivered_at=? WHERE id=?",
                (time.time(), item_id),
            ).rowcount
        return n > 0

    def dismiss(self, item_id: int) -> bool:
        with self._connect() as conn:
            n = conn.execute(
                "UPDATE proactive_queue SET dismissed=1 WHERE id=?",
                (item_id,),
            ).rowcount
        return n > 0

    def cycle_next(self, after_id: int | None = None) -> ProactiveItem | None:
        """Return the next pending item for [n] cycling.

        cycle_next(None)     → first pending item.
        cycle_next(after_id) → first pending item with id > after_id,
                                wrapping to the first if none exists after N.
        Returns None if the queue has no pending items.
        """
        now = time.time()
        _where = "delivered_at IS NULL AND dismissed = 0 AND expires_at > ?"
        with self._connect() as conn:
            if after_id is not None:
                row = conn.execute(
                    f"SELECT * FROM proactive_queue "
                    f"WHERE id > ? AND {_where} "
                    f"ORDER BY id ASC LIMIT 1",
                    (after_id, now),
                ).fetchone()
                if row is None:
                    row = conn.execute(
                        f"SELECT * FROM proactive_queue "
                        f"WHERE {_where} "
                        f"ORDER BY id ASC LIMIT 1",
                        (now,),
                    ).fetchone()
            else:
                row = conn.execute(
                    f"SELECT * FROM proactive_queue "
                    f"WHERE {_where} "
                    f"ORDER BY id ASC LIMIT 1",
                    (now,),
                ).fetchone()
        return self._row_to_item(row) if row else None

    def pending_count(self) -> int:
        """Count undelivered, undismissed, unexpired items."""
        now = time.time()
        with self._connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM proactive_queue "
                "WHERE delivered_at IS NULL AND dismissed = 0 AND expires_at > ?",
                (now,),
            ).fetchone()[0]

    def prune(self) -> int:
        """Delete expired items and fully-consumed (dismissed+delivered) items.

        Returns count deleted.
        """
        now = time.time()
        with self._connect() as conn:
            n = conn.execute(
                "DELETE FROM proactive_queue "
                "WHERE expires_at <= ? "
                "   OR (dismissed = 1 AND delivered_at IS NOT NULL)",
                (now,),
            ).rowcount
        return n
