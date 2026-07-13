"""Baseline health panel for the Iris operator console — ti-pugo3.3.2.

On-demand detail view pushed via [H]: the full checks table + fix hints
behind the status-strip health pill (ti-pugo3.1 BaselineHeartbeat via
ti-pugo3.3.1's daemon broadcast). Read-only — the console only ever renders
what the daemon already computed, no checks run here.
"""
from __future__ import annotations

import time
from datetime import datetime

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, RichLog, Static

from iris.console._markup import escape_for_content

# Mirrors iris/doctor.py's _SYMBOL glyph vocabulary exactly (operators already
# know these from `iris doctor`'s own CLI output) — kept as a small local
# string-keyed copy since the wire payload gives plain status strings, not
# doctor.py's DoctorStatus enum.
_STATUS_GLYPH = {
    "ok": "✓",
    "degraded": "!",
    "down": "✗",
    "absent": "–",
    "unknown": "?",
}

_LEVEL_GLYPH = {"green": "🟢", "yellow": "🟡", "red": "🔴"}


def _level_text(level: str, n: int) -> str:
    """Mirrors the wireframe's summary line, e.g. "1 required check failing"."""
    if level == "green":
        return "all required checks ok"
    plural = "" if n == 1 else "s"
    if level == "yellow":
        return f"{n} required check{plural} degraded"
    if level == "red":
        return f"{n} required check{plural} failing"
    return "status unknown"

# Consecutive all-OK checks beyond this many collapse into one summary row —
# a forward-looking safeguard for when the check set grows (today's set is
# small enough this rarely fires).
_OK_COLLAPSE_THRESHOLD = 5


class HealthScreen(Screen):
    """Full-width baseline health detail panel — pushed via [H].

    Parameters
    ----------
    baseline:
        Last-known baseline payload (``{"level", "checked_at", "failing",
        "checks"}``), or ``None`` if nothing has arrived yet.
    direct_mode:
        True when the console has no daemon connection — baseline health is
        daemon-only data, so there is nothing to check in this mode.
    """

    TITLE = "Iris — Baseline Health"

    CSS = """
    HealthScreen {
        background: #0f1624;
        color: #cce0ff;
    }
    #health-body {
        height: 1fr;
        padding: 1 2;
    }
    #health-summary {
        height: auto;
        padding-bottom: 1;
    }
    #health-table {
        height: auto;
        max-height: 20;
        background: #1c2333;
        color: #cce0ff;
    }
    DataTable > .datatable--header { background: #2a3a5e; color: #ffffff; }
    #health-fixes {
        height: auto;
        padding-top: 1;
    }
    """

    # priority=True (matches HelpScreen/ContactsScreen): IrisConsole's own "q"
    # is ALSO priority=True (bound to "quit"), and Textual checks priority
    # bindings App-first — without IrisConsole.check_action's "quit" gate
    # (see app.py), pressing "q" here would quit the whole app instead of
    # closing this screen.
    BINDINGS = [
        Binding("q", "app.pop_screen", "close", priority=True),
        Binding("escape", "app.pop_screen", "close", priority=True),
    ]

    def __init__(self, baseline: dict | None, direct_mode: bool) -> None:
        super().__init__()
        self._baseline = baseline
        self._direct_mode = direct_mode

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with VerticalScroll(id="health-body"):
            yield Static(self._summary_text(), id="health-summary")
            if self._baseline is not None:
                yield DataTable(id="health-table")
                fixes = self._fixes_text()
                if fixes:
                    yield Static(fixes, id="health-fixes")
        yield Footer()

    def on_mount(self) -> None:
        if self._baseline is not None:
            table = self.query_one("#health-table", DataTable)
            table.add_columns("NAME", "STATUS", "REQ", "DETAIL")
            table.cursor_type = "none"
            for row in _collapse_rows(self._baseline.get("checks", [])):
                table.add_row(*row)
        self.query_one("#health-body", VerticalScroll).focus()

    def on_unmount(self) -> None:
        self.app.query_one("#log", RichLog).focus()

    def _summary_text(self) -> str:
        if self._baseline is None:
            if self._direct_mode:
                return (
                    "Baseline health monitoring runs in the daemon — you're "
                    "in direct mode, so there's nothing to check right now."
                )
            return "No baseline health data yet from this daemon."
        level = self._baseline.get("level", "unknown")
        glyph = _LEVEL_GLYPH.get(level, "⚪")
        text = _level_text(level, len(self._baseline.get("failing", [])))
        freshness = _format_freshness(self._baseline.get("checked_at"))
        return f"{glyph}  {text}   ·   {freshness}"

    def _fixes_text(self) -> str:
        checks = self._baseline.get("checks", []) if self._baseline else []
        broken = [c for c in checks if c.get("required") and c.get("status") != "ok"]
        if not broken:
            return ""
        lines = ["[#f38ba8]FIXES[/]", ""]
        for c in broken:
            name = escape_for_content(c.get("name", ""))
            fix = escape_for_content(c.get("fix") or "(no fix available — see docs)")
            lines.append(f"{name}  →  {fix}")
        return "\n".join(lines)


def _format_freshness(checked_at: float | None) -> str:
    if checked_at is None:
        return "as of — (unknown)"
    checked = datetime.fromtimestamp(checked_at)
    age_s = max(0, int(time.time() - checked_at))
    return f"as of {checked:%H:%M:%S} ({age_s}s ago)"


def _collapse_rows(checks: list[dict]) -> list[tuple[str, str, str, str]]:
    rows: list[tuple[str, str, str, str]] = []
    run: list[dict] = []

    def flush() -> None:
        if len(run) > _OK_COLLAPSE_THRESHOLD:
            rows.extend(_format_row(c) for c in run[:_OK_COLLAPSE_THRESHOLD])
            hidden = len(run) - _OK_COLLAPSE_THRESHOLD
            rows.append((f"[dim]… {hidden} more checks, all ok …[/]", "", "", ""))
        else:
            rows.extend(_format_row(c) for c in run)
        run.clear()

    for check in checks:
        if check.get("status") == "ok":
            run.append(check)
        else:
            flush()
            rows.append(_format_row(check))
    flush()
    return rows


def _format_row(check: dict) -> tuple[str, str, str, str]:
    status = check.get("status", "unknown")
    glyph = _STATUS_GLYPH.get(status, "?")
    required = bool(check.get("required", False))
    name = escape_for_content(check.get("name", ""))
    detail = escape_for_content(check.get("detail", ""))
    cells = (
        f"{glyph} {name}",
        status,
        "yes" if required else "no",
        detail,
    )
    if not required:
        return tuple(f"[dim]{cell}[/]" for cell in cells)
    return cells
