"""BrainHost — daemon-side Brain lifetime manager (ti-s9mm.1).

Owns the Brain singleton, serializes turns via TurnLock, manages call context,
and persists it to the BRAIN_CONTEXT table in roster.db.

Turn serialization: Lock.acquire(blocking=False) — busy ack, not queue.
Broadcast ordering: brain_turn_started BEFORE TurnLock attempt (<100ms spinner).
All events (brain_reply, brain_chunk) go to ALL connected clients.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Callable

_log = logging.getLogger(__name__)

_CREATE_BRAIN_CONTEXT = """
CREATE TABLE IF NOT EXISTS brain_context (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL DEFAULT '',
    updated_at REAL NOT NULL
)
"""

_CONTEXT_KEYS = ("contact_id", "contact_name", "contact_number", "in_call")


class BrainHost:
    """Owns the Brain singleton inside the iris daemon.

    :param brain:     Brain instance (created once at daemon startup).
    :param db_path:   Path to roster.db — used for BRAIN_CONTEXT persistence.
    :param broadcast: Callable[[dict], None] — push event to all clients.
    """

    def __init__(
        self,
        brain: object,
        db_path: Path | str,
        broadcast: Callable[[dict], None],
    ) -> None:
        self._brain = brain
        self._db_path = Path(db_path)
        self._broadcast = broadcast
        self._turn_lock = threading.Lock()
        self._ctx: dict[str, str] = {
            "contact_id": "",
            "contact_name": "",
            "contact_number": "",
            "in_call": "0",
        }
        self._ensure_table()
        self._restore_context()

    # --- turn execution ---

    def async_turn(self, text: str, speaker: str) -> dict:
        """Run one brain turn in a daemon thread; return ack immediately.

        brain_turn_started is broadcast BEFORE the lock attempt so the console
        gets sub-100ms spinner feedback. If the lock is held, return busy ack
        without blocking the caller.
        """
        self._broadcast({"event": "brain_turn_started", "text": text, "speaker": speaker})

        if not self._turn_lock.acquire(blocking=False):
            return {"ack": "turn", "ok": False, "error": "busy"}

        def _run() -> None:
            try:
                chunks = []
                try:
                    for chunk in self._brain.respond_stream(text, speaker=speaker):  # type: ignore[attr-defined]
                        chunks.append(chunk)
                        self._broadcast({
                            "event": "brain_chunk",
                            "text":  chunk.text,
                            "lane":  chunk.lane,
                            "skill": chunk.skill,
                            "final": chunk.final,
                        })
                    reply_text = "".join(c.text for c in chunks)
                    final_chunk = chunks[-1] if chunks else None
                    self._broadcast({
                        "event": "brain_reply",
                        "text":  reply_text,
                        "lane":  final_chunk.lane if final_chunk else "",
                        "skill": final_chunk.skill if final_chunk else None,
                        "re_ask": False,
                    })
                except Exception as exc:  # noqa: BLE001
                    _log.exception("BrainHost: brain.respond_stream() failed")
                    self._broadcast({
                        "event": "error",
                        "message": f"Brain error: {exc}",
                    })
            finally:
                self._turn_lock.release()

        try:
            t = threading.Thread(target=_run, name="brain-turn", daemon=True)
            t.start()
        except BaseException:
            self._turn_lock.release()
            raise
        return {"ack": "turn", "ok": True}

    # --- call context ---

    def call_context_snapshot(self) -> dict:
        """Return current call context as a plain dict (in_call as bool)."""
        return {
            "contact_id":     self._ctx["contact_id"],
            "contact_name":   self._ctx["contact_name"],
            "contact_number": self._ctx["contact_number"],
            "in_call":        self._ctx["in_call"] == "1",
        }

    def set_call_context(
        self,
        contact_id: str,
        contact_name: str,
        contact_number: str,
    ) -> None:
        """Set in-call context on the Brain and persist to BRAIN_CONTEXT."""
        self._brain.call_context = contact_id  # type: ignore[attr-defined]
        values = {
            "contact_id":     contact_id,
            "contact_name":   contact_name,
            "contact_number": contact_number,
            "in_call":        "1",
        }
        self._ctx.update(values)
        self._write_context(values)

    def clear_call_context(self) -> None:
        """Clear in-call context on the Brain and persist to BRAIN_CONTEXT."""
        self._brain.call_context = ""  # type: ignore[attr-defined]
        values = {
            "contact_id":     "",
            "contact_name":   "",
            "contact_number": "",
            "in_call":        "0",
        }
        self._ctx.update(values)
        self._write_context(values)

    # --- DB helpers ---

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_table(self) -> None:
        with self._connect() as conn:
            conn.execute(_CREATE_BRAIN_CONTEXT)
            conn.commit()

    def _write_context(self, values: dict[str, str]) -> None:
        now = time.time()
        with self._connect() as conn:
            for key, value in values.items():
                conn.execute(
                    "INSERT INTO brain_context (key, value, updated_at) VALUES (?, ?, ?)"
                    " ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                    (key, value, now),
                )
            conn.commit()

    def _restore_context(self) -> None:
        """Read BRAIN_CONTEXT table and restore brain.call_context if in_call='1'."""
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT key, value FROM brain_context WHERE key IN ({})".format(
                        ",".join("?" * len(_CONTEXT_KEYS))
                    ),
                    _CONTEXT_KEYS,
                ).fetchall()
        except sqlite3.OperationalError:
            return

        ctx = {row["key"]: row["value"] for row in rows}
        self._ctx.update({k: ctx.get(k, v) for k, v in self._ctx.items()})
        if ctx.get("in_call") == "1":
            self._brain.call_context = ctx.get("contact_id", "")  # type: ignore[attr-defined]
            _log.info(
                "BrainHost: restored call context — contact_id=%r",
                self._brain.call_context,  # type: ignore[attr-defined]
            )
