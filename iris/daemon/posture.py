"""PostureManager — DND state machine + busy auto-detect stub (ADR-0006).

The posture singleton (id=1 row in the posture table) is the durable storage for DND
state across daemon restarts.  In-process state is the authoritative fast path:
set_dnd / clear_dnd update both memory and DB atomically.  effective() returns
in-memory state without hitting the DB.

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
class _State:
    dnd: bool = False
    dnd_source: str = "manual"
    dnd_expires: float | None = None
    busy: bool = False  # v1 stub


class PostureManager:
    """Thread-safe DND state machine.

    In-memory _state is the hot path; DB persistence is write-through.
    Callers register with subscribe() to receive posture_changed events:
        {"type": "posture_changed", "dnd": bool, "busy": bool, "dnd_expires": float|None}

    The posture table must already exist (created by roster migration v2).
    Call _ensure_row() at daemon first-start to insert id=1 if absent.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path else _DEFAULT_PATH
        self._lock = threading.Lock()
        self._state = _State()
        self._listeners: list[Callable[[dict], None]] = []
        self._ensure_row()
        self._load_state()

    def _db_connect(self) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_row(self) -> None:
        """Ensure posture table + singleton row exist (idempotent)."""
        now = time.time()
        with self._db_connect() as conn:
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

    def _load_state(self) -> None:
        """Restore in-memory state from DB (called once at init)."""
        with self._db_connect() as conn:
            row = conn.execute(
                "SELECT dnd, dnd_source, dnd_expires FROM posture WHERE id=1"
            ).fetchone()
        if row:
            with self._lock:
                self._state = _State(
                    dnd=bool(row["dnd"]),
                    dnd_source=row["dnd_source"] or "manual",
                    dnd_expires=row["dnd_expires"],
                    busy=False,
                )

    def _persist(self, state: _State) -> None:
        """Write state to DB (best-effort; loss on crash is acceptable)."""
        now = time.time()
        try:
            with self._db_connect() as conn:
                conn.execute(
                    "UPDATE posture"
                    " SET dnd=?, dnd_source=?, dnd_expires=?, updated_at=?"
                    " WHERE id=1",
                    (int(state.dnd), state.dnd_source, state.dnd_expires, now),
                )
        except Exception:
            _log.exception("PostureManager: DB persist failed (state held in memory)")

    def subscribe(self, listener: Callable[[dict], None]) -> None:
        """Register a listener for posture_changed events (idempotent)."""
        with self._lock:
            if listener not in self._listeners:
                self._listeners.append(listener)

    def unsubscribe(self, listener: Callable[[dict], None]) -> None:
        with self._lock:
            self._listeners = [cb for cb in self._listeners if cb is not listener]

    def _broadcast(self, state: _State) -> None:
        event = {
            "type":        "posture_changed",
            "dnd":         state.dnd,
            "busy":        state.busy,
            "dnd_expires": state.dnd_expires,
            # dnd_source INTENTIONALLY omitted — security invariant
        }
        for listener in list(self._listeners):
            try:
                listener(event)
            except Exception:
                _log.exception("PostureManager: listener raised")

    def effective(self) -> dict:
        """Return {dnd: bool, busy: bool}.  dnd_source NEVER included.

        Uses in-memory state — no DB access.
        """
        with self._lock:
            return {"dnd": self._state.dnd, "busy": False}

    def set_dnd(self, source: str, expires: float | None = None) -> None:
        """Enable DND.  source is internal only; never forwarded to listeners."""
        with self._lock:
            self._state = _State(
                dnd=True, dnd_source=source, dnd_expires=expires, busy=False
            )
            snapshot = _State(**vars(self._state))
        self._persist(snapshot)
        self._broadcast(snapshot)

    def clear_dnd(self) -> None:
        """Disable DND unconditionally."""
        with self._lock:
            self._state = _State(
                dnd=False, dnd_source="manual", dnd_expires=None, busy=False
            )
            snapshot = _State(**vars(self._state))
        self._persist(snapshot)
        self._broadcast(snapshot)

    def toggle_dnd(self, source: str) -> None:
        """Flip DND state (on→off, off→on indefinitely)."""
        if self.effective()["dnd"]:
            self.clear_dnd()
        else:
            self.set_dnd(source)

    def dnd_expires(self) -> float | None:
        """Return current DND expiry timestamp (or None for indefinite)."""
        with self._lock:
            return self._state.dnd_expires

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
        eff = self._manager.effective()
        expires = self._manager.dnd_expires()
        if eff["dnd"] and expires is not None and now > expires:
            _log.info("PostureWatcher: timed DND expired — auto-clearing")
            self._manager.clear_dnd()
