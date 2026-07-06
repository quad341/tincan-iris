"""Degradation notifications — edge-triggered desktop notify on baseline
transitions (ti-pugo3.2).

Hooks BaselineHeartbeat's `on_transition` callback (ti-pugo3.1) to decide when
a BaselineStatus change is worth telling the operator about. This module only
decides notify-worthiness; delivery is DesktopNotifySink, wired in via
`init()` at daemon startup, matching how __main__.py already threads that
same sink into HandlingEngine.

Edge-triggered only (NFR-2): steady state is silent. State is in-memory only
and does not survive a daemon restart — a restart is treated as an assumed-
green baseline, so a still-broken system is correctly re-announced on the
next tick rather than silently suppressed forever (accepted trade-off, see
architecture doc).
"""
from __future__ import annotations

import time

from ..doctor import DoctorStatus
from ..notify_sink import DesktopNotifySink
from .heartbeat import BaselineStatus

_RED_REMIND_INTERVAL_S: float = 86400.0  # FR-2.2: at most once per 24h while red

_notify_sink: DesktopNotifySink | None = None
_last_level: str | None = None  # None until the first tick ever runs
_last_red_notify_ts: float | None = None


def init(notify_sink: DesktopNotifySink) -> None:
    """Wire the desktop notification sink. Call once at daemon startup."""
    global _notify_sink
    _notify_sink = notify_sink


def on_baseline_transition(new: BaselineStatus, previous: BaselineStatus | None) -> None:  # noqa: ARG001
    """BaselineHeartbeat's on_transition callback — decides notify-worthiness.

    `previous` (the heartbeat's own cache) is intentionally unused: tracking
    module-level `_last_level` instead means this asks "what did *this
    notifier* last tell the operator", which is what makes the assumed-green-
    on-restart behavior fall out naturally instead of needing a restart
    special case.
    """
    global _last_level, _last_red_notify_ts
    prev_level = _last_level
    _last_level = new.level

    if prev_level in (None, "green") and new.level != "green":
        _notify_degraded(new)
        if new.level == "red":
            _last_red_notify_ts = time.time()
        return

    if prev_level is not None and prev_level != "green" and new.level == "green":
        _notify_recovered()
        _last_red_notify_ts = None
        return

    if new.level == "red" and (
        _last_red_notify_ts is None or time.time() - _last_red_notify_ts >= _RED_REMIND_INTERVAL_S
    ):
        _notify_degraded(new, is_reminder=True)
        _last_red_notify_ts = time.time()


def _notify_degraded(status: BaselineStatus, *, is_reminder: bool = False) -> None:
    failing = [c for c in status.checks if c.required and c.status != DoctorStatus.OK]
    title = "Iris: still degraded (daily reminder)" if is_reminder else f"Iris baseline: {status.level}"
    body = "; ".join(
        f"{c.name}: {c.detail or c.status.value}" + (f" — {c.fix}" if c.fix else "")
        for c in failing
    )
    urgency = "critical" if status.level == "red" else "normal"
    _notify_sink.notify(title, body, urgency=urgency)


def _notify_recovered() -> None:
    _notify_sink.notify(
        "Iris baseline: back to green", "All baseline checks passing again.", urgency="normal"
    )
