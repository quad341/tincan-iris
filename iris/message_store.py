"""SQLite-backed message store for voice messages captured by TakeMessageFlow.

When called without a path, uses an in-memory database (fresh each instantiation,
consistent with the prior in-memory implementation). Pass an explicit path for
persistent storage across daemon restarts.
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

_IRIS_DB = Path.home() / ".local" / "share" / "iris" / "iris.db"

_DDL = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS voice_messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    caller_name  TEXT    NOT NULL DEFAULT '',
    caller_number TEXT   NOT NULL DEFAULT '',
    contact_name TEXT    NOT NULL DEFAULT '',
    transcript   TEXT    NOT NULL DEFAULT '',
    timestamp    REAL    NOT NULL,
    read         INTEGER NOT NULL DEFAULT 0,
    read_at      REAL
);
CREATE INDEX IF NOT EXISTS idx_vm_read_ts ON voice_messages (read, timestamp DESC);
"""

_MAX_ALL = 500


@dataclass
class VoiceMessage:
    id: int
    caller_name: str
    caller_number: str
    contact_name: str
    transcript: str
    timestamp: float
    read: bool = False
    read_at: float | None = None


def _row_to_msg(row: tuple) -> VoiceMessage:
    id_, caller_name, caller_number, contact_name, transcript, timestamp, read, read_at = row
    return VoiceMessage(
        id=id_,
        caller_name=caller_name,
        caller_number=caller_number,
        contact_name=contact_name,
        transcript=transcript,
        timestamp=timestamp,
        read=bool(read),
        read_at=read_at,
    )


class MessageStore:
    """SQLite-backed store for VoiceMessage objects.

    Without a path, uses an in-memory database (each instance starts empty).
    Pass path=_IRIS_DB (or another path) for cross-restart persistence.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        db_path = str(path) if path else ":memory:"
        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.executescript(_DDL)
        self._db.commit()
        # Cache objects returned by add() for backward-compat mutation via mark_read
        self._obj_cache: dict[int, VoiceMessage] = {}

    def add(
        self,
        caller_name: str,
        transcript: str,
        *,
        caller_number: str = "",
        contact_name: str = "",
        timestamp: float | None = None,
    ) -> VoiceMessage:
        ts = timestamp if timestamp is not None else time.time()
        cur = self._db.execute(
            "INSERT INTO voice_messages (caller_name, caller_number, contact_name, transcript, timestamp)"
            " VALUES (?, ?, ?, ?, ?)",
            (caller_name, caller_number, contact_name, transcript, ts),
        )
        self._db.commit()
        msg = VoiceMessage(
            id=cur.lastrowid,
            caller_name=caller_name,
            caller_number=caller_number,
            contact_name=contact_name,
            transcript=transcript,
            timestamp=ts,
        )
        self._obj_cache[msg.id] = msg
        return msg

    def unread(self) -> list[VoiceMessage]:
        """Return unread messages, newest first."""
        rows = self._db.execute(
            "SELECT id, caller_name, caller_number, contact_name, transcript, timestamp, read, read_at"
            " FROM voice_messages WHERE read=0 ORDER BY timestamp DESC"
        ).fetchall()
        return [_row_to_msg(r) for r in rows]

    def all(self) -> list[VoiceMessage]:
        """Return all messages newest first, capped at 500."""
        rows = self._db.execute(
            "SELECT id, caller_name, caller_number, contact_name, transcript, timestamp, read, read_at"
            " FROM voice_messages ORDER BY timestamp DESC LIMIT ?",
            (_MAX_ALL,),
        ).fetchall()
        return [_row_to_msg(r) for r in rows]

    def mark_read(self, message_id: int) -> bool:
        now = time.time()
        cur = self._db.execute(
            "UPDATE voice_messages SET read=1, read_at=? WHERE id=? AND read=0",
            (now, message_id),
        )
        self._db.commit()
        if cur.rowcount > 0:
            if message_id in self._obj_cache:
                self._obj_cache[message_id].read = True
                self._obj_cache[message_id].read_at = now
            return True
        return False

    def mark_all_read(self) -> None:
        now = time.time()
        self._db.execute(
            "UPDATE voice_messages SET read=1, read_at=? WHERE read=0", (now,)
        )
        self._db.commit()
        for msg in self._obj_cache.values():
            if not msg.read:
                msg.read = True
                msg.read_at = now

    def delete(self, message_id: int) -> bool:
        cur = self._db.execute("DELETE FROM voice_messages WHERE id=?", (message_id,))
        self._db.commit()
        self._obj_cache.pop(message_id, None)
        return cur.rowcount > 0

    def clear(self) -> None:
        """Remove all messages."""
        self._db.execute("DELETE FROM voice_messages")
        self._db.commit()
        self._obj_cache.clear()
