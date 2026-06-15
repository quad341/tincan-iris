"""Local conversation transcript store — SQLite, local-only, never sent.

Each turn is tagged ``(session_id, speaker, timestamp, text)``.  A new
``session_id`` (e.g. a UUID) should be generated at call start; reuse
the same ID for all turns in one call so queries can reconstruct a call.

Schema is created on first connect; migrations are not needed yet — the
store is private to this machine and can be blown away.

Privacy: the DB lives at ``~/.local/share/iris/transcripts.db`` by default.
It is gitignored, never committed, and never sent anywhere. Think of it
as the call's short-term memory; the long-term layer is the gist (future).
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

_DEFAULT_PATH = Path.home() / ".local" / "share" / "iris" / "transcripts.db"

_DDL = """
CREATE TABLE IF NOT EXISTS turns (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT    NOT NULL,
    speaker    TEXT    NOT NULL,
    timestamp  REAL    NOT NULL,
    text       TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS turns_session ON turns(session_id);
"""


class TranscriptStore:
    """Append-only transcript log.  Thread-safe: each call opens its own connection
    (``check_same_thread=False`` + ``WAL`` journal mode)."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else _DEFAULT_PATH

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_DDL)
        return conn

    def append(self, session_id: str, speaker: str, text: str, *,
                timestamp: float | None = None) -> int:
        """Persist a single turn. Returns the new row id."""
        ts = timestamp if timestamp is not None else time.time()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO turns (session_id, speaker, timestamp, text) VALUES (?,?,?,?)",
                (session_id, speaker, ts, text),
            )
            return cur.lastrowid

    def query(self, session_id: str) -> list[dict]:
        """All turns for a session, oldest first."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM turns WHERE session_id=? ORDER BY timestamp",
                (session_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def recent(self, limit: int = 20) -> list[dict]:
        """The most recent ``limit`` turns across all sessions, oldest-first."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM turns ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def sessions(self) -> list[str]:
        """Distinct session IDs, most-recently-active first."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT session_id FROM turns GROUP BY session_id ORDER BY MAX(timestamp) DESC"
            ).fetchall()
        return [r[0] for r in rows]
