"""Crash + bug-report diagnostics for iris/console — ti-oqlyk (FR1-FR3, ti-qz990 architecture).

Every function here is exception-safe end-to-end: it runs during already-exceptional
conditions (an unhandled exception, or an operator filing a bug after something went
wrong), so a raise from inside this module would be strictly worse than doing nothing.

Writes two on-disk artifacts, both created 0o600 (may carry call-content/contact PII):
  console.log        — appended-to by persist_crash; rotation itself lives in app.py's
                        _open_log(), not here.
  bug-<epoch>.json    — schema "iris-bug-report-v1", under iris.settings.iris_home()/bug-reports.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

from .. import settings

_BUG_REPORT_SCHEMA = "iris-bug-report-v1"
_LOG_TAIL_LINES = 200

# Module-level so hooks that fire before/after the App's lifetime (sys.excepthook can
# fire before IrisConsole() finishes constructing) can still gather state when it's
# available, and degrade gracefully when it isn't.
_active_app: Any = None


def set_active_app(app: Any) -> None:
    global _active_app
    _active_app = app


def clear_active_app() -> None:
    global _active_app
    _active_app = None


def install_exception_hooks() -> None:
    """Install sys.excepthook + threading.excepthook. Call once, before IrisConsole() is
    constructed. Covers exceptions outside Textual's own reach: pre-construction failures
    (sys.excepthook) and raw threading.Thread targets that bypass Textual's run_worker
    (threading.excepthook) — see ti-qz990 OQ2. The IrisConsole._handle_exception override
    (in app.py) covers everything Textual's message pump and run_worker DO see."""

    def _sys_hook(exc_type: type[BaseException], exc_value: BaseException | None, exc_tb: Any) -> None:
        if exc_value is not None:
            persist_crash("main", exc_value)
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    def _threading_hook(args: threading.ExceptHookArgs) -> None:
        if args.exc_value is not None:
            persist_crash("thread", args.exc_value)
        threading.__excepthook__(args)

    sys.excepthook = _sys_hook
    threading.excepthook = _threading_hook


def persist_crash(source: str, exc: BaseException) -> None:
    """Append a traceback to console.log and write a bug report. Never raises."""
    try:
        tb_text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        timestamp_iso = datetime.now().isoformat()
        _append_to_log(f"\n=== CRASH ({source}) {timestamp_iso} ===\n{tb_text}")
        write_bug_report(
            f"crash:{source}",
            crash_record={"timestamp_iso": timestamp_iso, "source": source, "traceback": tb_text},
        )
    except Exception:  # noqa: BLE001 — must never mask the original crash
        print(f"iris diagnostics: persist_crash failed for source={source!r}", file=sys.stderr)


def write_bug_report(trigger: str, *, crash_record: dict[str, Any] | None = None) -> Path | None:
    """Write a bug-report JSON snapshot. Returns the path, or None on failure — never raises."""
    try:
        ts = time.time()
        report: dict[str, Any] = {
            "schema": _BUG_REPORT_SCHEMA,
            "timestamp": int(ts),
            "timestamp_iso": datetime.now().isoformat(),
            "pid": os.getpid(),
            "trigger": trigger,
            "last_error": _gather_last_error(),
            "app_state": _gather_app_state(),
            "log_tail": _tail_lines(_log_path(), _LOG_TAIL_LINES),
        }
        if crash_record is not None:
            report["crash_record"] = crash_record

        out_dir = settings.iris_home() / "bug-reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"bug-{int(ts)}.json"
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        os.chmod(path, 0o600)
        return path
    except Exception:  # noqa: BLE001 — a failed bug report must not raise, esp. mid-crash-handling
        print("iris diagnostics: write_bug_report failed", file=sys.stderr)
        return None


def _gather_last_error() -> str:
    app = _active_app
    return getattr(app, "_last_error", "") or "" if app is not None else ""


def _gather_app_state() -> dict[str, Any]:
    app = _active_app
    if app is None:
        return {"mode": None, "in_call": None, "dnd": None, "trust_state": None, "contact_name": None}
    far_trust = getattr(getattr(app, "conductor", None), "far_trust", None)
    return {
        "mode": getattr(app, "_mode", None),
        "in_call": getattr(app, "_in_call", None),
        "dnd": getattr(app, "_dnd", None),
        "trust_state": far_trust.name if far_trust is not None else None,
        "contact_name": getattr(app, "_call_contact_name", None) or None,
    }


def _default_log_path() -> str:
    override = settings.get("IRIS_LOG_FILE")
    if override:
        return override
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, "iris", "console.log")


def _log_path() -> str:
    app = _active_app
    path = getattr(app, "_logpath", None) if app is not None else None
    return path or _default_log_path()


def _tail_lines(path: str, n: int) -> list[str]:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return [line.rstrip("\n") for line in lines[-n:]]
    except OSError:
        return []


def _append_to_log(text: str) -> None:
    app = _active_app
    logf = getattr(app, "_logf", None) if app is not None else None
    if logf is not None:
        try:
            logf.write(text)
            return
        except OSError:
            pass  # fall through to a fresh open below
    path = _log_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", buffering=1, encoding="utf-8") as f:
            f.write(text)
    except OSError:
        pass
