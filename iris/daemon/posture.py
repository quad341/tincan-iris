"""PostureManager — DND state machine + busy auto-detect stub (ADR-0006).

The posture singleton (id=1 row in the posture table) is the single source of
truth for DND and busy states.  All mutations are written atomically and
broadcast to registered listeners as posture_changed events.

Security invariant: dnd_source is internal metadata and MUST NOT appear in any
outbound event payload, effective() return value, or any caller-facing text.

Busy is a v1 stub — always False.  set_busy() / clear_busy() exist but are no-ops.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

_log = logging.getLogger(__name__)

_DEFAULT_PATH = Path.home() / ".local" / "share" / "iris" / "roster.db"

_POLL_INTERVAL_S: float = 60.0


@dataclass
class PostureState:
    dnd: bool
    busy: bool
    dnd_expires: float | None  # internal; drives UI "until HH:MM" display


class PostureManager:
    """Thread-safe DND state machine backed by the posture table.

    Callers register with subscribe() to receive posture_changed events:
        {"type": "posture_changed", "dnd": bool, "busy": bool, "dnd_expires": float|None}

    The posture table must already exist (created by roster migration v2).
    Call _ensure_row() at daemon first-start to insert id=1 if absent.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path else _DEFAULT_PATH
        self._lock = threading.Lock()
        self._listeners: list[Callable[[dict], None]] = []
        self._ensure_row()

    def _connect(self) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_row(self) -> None:
        """Ensure the posture singleton row exists.

        The posture table is created by roster migration v2.  If called before any
        RosterStore method has triggered the migration (e.g. in tests), we create
        the table here so PostureManager is self-sufficient.
        """
        now = time.time()
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS posture (
                    id          INTEGER PRIMARY KEY CHECK (id = 1),
                    dnd         INTEGER NOT NULL DEFAULT 0,
                    dnd_source  TEXT    NOT NULL DEFAULT 'manual',
                    dnd_expires REAL,
                    busy        INTEGER NOT NULL DEFAULT 0,
                    busy_source TEXT    NOT NULL DEFAULT 'sco',
                    updated_at  REAL    NOT NULL DEFAULT 0
                )
            """)
            conn.execute(
                "INSERT OR IGNORE INTO posture"
                " (id, dnd, dnd_source, dnd_expires, busy, busy_source, updated_at)"
                " VALUES (1, 0, 'manual', NULL, 0, 'sco', ?)",
                (now,),
            )

    def subscribe(self, listener: Callable[[dict], None]) -> None:
        """Register a listener for posture_changed events (idempotent)."""
        with self._lock:
            if listener not in self._listeners:
                self._listeners.append(listener)

    def unsubscribe(self, listener: Callable[[dict], None]) -> None:
        with self._lock:
            self._listeners = [l for l in self._listeners if l is not listener]

    def _broadcast(self, state: PostureState) -> None:
        event = {
            "type": "posture_changed",
            "dnd": state.dnd,
            "busy": state.busy,
            "dnd_expires": state.dnd_expires,
            # dnd_source INTENTIONALLY omitted — security invariant
        }
        for listener in list(self._listeners):
            try:
                listener(event)
            except Exception:
                _log.exception("PostureManager: listener raised")

    def _read_state(self, conn: sqlite3.Connection) -> PostureState:
        row = conn.execute(
            "SELECT dnd, dnd_expires FROM posture WHERE id=1"
        ).fetchone()
        if row is None:
            return PostureState(dnd=False, busy=False, dnd_expires=None)
        return PostureState(
            dnd=bool(row["dnd"]),
            busy=False,  # v1 stub
            dnd_expires=row["dnd_expires"],
        )

    def effective(self) -> dict:
        """Return {dnd: bool, busy: bool}.  dnd_source NEVER included."""
        with self._connect() as conn:
            state = self._read_state(conn)
        return {"dnd": state.dnd, "busy": False}

    def set_dnd(self, source: str, expires: float | None = None) -> None:
        """Enable DND.  source is internal only; never forwarded to listeners."""
        now = time.time()
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE posture"
                    " SET dnd=1, dnd_source=?, dnd_expires=?, updated_at=?"
                    " WHERE id=1",
                    (source, expires, now),
                )
            state = PostureState(dnd=True, busy=False, dnd_expires=expires)
        self._broadcast(state)

    def clear_dnd(self) -> None:
        """Disable DND unconditionally."""
        now = time.time()
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE posture"
                    " SET dnd=0, dnd_source='manual', dnd_expires=NULL, updated_at=?"
                    " WHERE id=1",
                    (now,),
                )
            state = PostureState(dnd=False, busy=False, dnd_expires=None)
        self._broadcast(state)

    def toggle_dnd(self, source: str) -> None:
        """Flip DND state (on→off, off→on indefinitely)."""
        if self.effective()["dnd"]:
            self.clear_dnd()
        else:
            self.set_dnd(source)

    # --- busy stubs (v1: desktop detection not implemented) ---

    def set_busy(self, source: str = "sco") -> None:
        """v1 stub — no-op; busy detection not implemented."""

    def clear_busy(self) -> None:
        """v1 stub — no-op."""


class PostureWatcher:
    """Daemon thread that auto-clears DND when the expiry time passes.

    Polls every 60s.  Max latency on auto-expiry: 60s.
    """

    def __init__(self, manager: PostureManager) -> None:
        self._manager = manager
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="posture-watcher", daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.wait(_POLL_INTERVAL_S):
            self._check_expiry()

    def _check_expiry(self) -> None:
        now = time.time()
        with self._manager._connect() as conn:
            row = conn.execute(
                "SELECT dnd, dnd_expires FROM posture WHERE id=1"
            ).fetchone()
        if row and row["dnd"] and row["dnd_expires"] is not None:
            if now > row["dnd_expires"]:
                _log.info("PostureWatcher: timed DND expired — auto-clearing")
                self._manager.clear_dnd()
