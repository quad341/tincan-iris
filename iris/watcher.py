"""ProactiveWatcher — calendar nudge poll + D-Bus event sourcing stub."""
from __future__ import annotations

import hashlib
import logging
import sqlite3
import threading
import time
from pathlib import Path

_logger = logging.getLogger(__name__)

_NUDGE_DDL = """
CREATE TABLE IF NOT EXISTS NUDGE_CACHE (
    event_id TEXT PRIMARY KEY,
    notified_at REAL NOT NULL,
    title_hidden TEXT NOT NULL,
    starts_at REAL NOT NULL
);
"""
_PRUNE_CUTOFF_S = 48 * 3600


class ProactiveWatcher:
    """Poll the calendar and enqueue P1 nudges for imminent events.

    Deduplication is backed by a SQLite NUDGE_CACHE table (default :memory:,
    pass db_path for persistence across restarts).
    """

    def __init__(
        self,
        *,
        store,
        calendar,
        cfg,
        db_path: Path | None = None,
    ) -> None:
        self._store = store
        self._calendar = calendar
        self._cfg = cfg
        self._stop = threading.Event()
        self._cal_thread: threading.Thread | None = None

        db = str(db_path) if db_path else ":memory:"
        if db_path:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(db, check_same_thread=False)
        self._db.executescript(_NUDGE_DDL)
        self._db.commit()

    def _setup_dbus(self) -> None:
        """Attempt D-Bus subscription. Raises RuntimeError if unavailable."""
        try:
            import dbus  # type: ignore  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(f"D-Bus not available: {exc}") from exc

    def _round_down_5(self, minutes: float) -> int:
        return (int(minutes) // 5) * 5

    def _poll_once(self) -> None:
        now = time.time()
        nudge_window_s = self._cfg.calendar_nudge_min * 60

        # Prune stale cache rows (>48h old)
        cutoff = now - _PRUNE_CUTOFF_S
        self._db.execute("DELETE FROM NUDGE_CACHE WHERE notified_at < ?", (cutoff,))
        self._db.commit()

        events = self._calendar.list_events()
        for ev in events:
            starts_in_s = ev.starts_at - now
            if starts_in_s < 0 or starts_in_s > nudge_window_s:
                continue

            title = getattr(ev, "title", "Meeting")
            title_hidden = hashlib.sha256(title.encode()).hexdigest()[:16]
            nudge_key = ev.event_id or hashlib.sha256(
                f"{title}{ev.starts_at}".encode()
            ).hexdigest()[:16]

            row = self._db.execute(
                "SELECT 1 FROM NUDGE_CACHE WHERE event_id = ?", (nudge_key,)
            ).fetchone()
            if row:
                continue

            minutes_until = round(starts_in_s) / 60.0
            rounded = self._round_down_5(minutes_until)
            if rounded == 0:
                rounded = max(1, int(minutes_until))
            msg = f"{title} starts in {rounded} min"

            self._store.enqueue(
                trigger_class="calendar_nudge",
                priority=1,
                message=msg,
                source_skill="calendar",
                source_id=ev.event_id,
            )

            self._db.execute(
                "INSERT OR REPLACE INTO NUDGE_CACHE (event_id, notified_at, title_hidden, starts_at)"
                " VALUES (?, ?, ?, ?)",
                (nudge_key, now, title_hidden, ev.starts_at),
            )
            self._db.commit()

    def _cal_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._poll_once()
            except Exception:
                _logger.exception("watcher poll error")
            self._stop.wait(self._cfg.calendar_poll_interval_s)

    def start(self) -> None:
        if self._cal_thread is not None and self._cal_thread.is_alive():
            return

        try:
            self._setup_dbus()
        except Exception:
            _logger.warning("D-Bus unavailable; calendar poll only")

        self._stop.clear()
        self._cal_thread = threading.Thread(
            target=self._cal_loop,
            daemon=True,
            name="iris-calendar-watcher",
        )
        self._cal_thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._cal_thread:
            self._cal_thread.join(timeout=1.0)
