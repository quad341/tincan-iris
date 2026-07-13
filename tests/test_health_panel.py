"""Regression tests for baseline health console surfacing (ti-pugo3.3.3).

Covers both sibling builder beads under ti-pugo3.3:
  - ti-pugo3.3.2: console health pill (5 states) + HealthScreen detail panel
    (table rendering incl. 5+-row collapsing, conditional FIXES section)
  - the console-side half of ti-pugo3.3.1: live "baseline" broadcast handling

Also strengthens the check_action() "quit" gate regression coverage that
already exists (assertion-free) for ContactsScreen in test_contacts_panel.py,
extending it to HealthScreen per this bead's DESIGN.

Per this rig's convention, the validator authors these tests; the console
pill/panel implementation itself is already complete and unmodified here.
"""
from __future__ import annotations

import asyncio
import time

import pytest

pytest.importorskip("textual")

from textual.widgets import Static

from iris.console.app import IrisConsole
from iris.console.health_screen import (
    HealthScreen,
    _OK_COLLAPSE_THRESHOLD,
    _collapse_rows,
    _format_freshness,
    _format_row,
    _level_text,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _check(
    name: str,
    status: str = "ok",
    *,
    required: bool = True,
    detail: str = "",
    fix: str = "",
) -> dict:
    """A single wire-shape check dict, matching DaemonAPI._status_payload's
    per-check shape (iris/daemon/api.py)."""
    return {"name": name, "status": status, "required": required, "detail": detail, "fix": fix}


def _baseline(level: str = "green", checks: list[dict] | None = None, checked_at: float = 1000.0) -> dict:
    """A full baseline wire payload, matching DaemonAPI._status_payload's shape."""
    checks = [] if checks is None else checks
    failing = [c["name"] for c in checks if c["required"] and c["status"] != "ok"]
    return {"level": level, "checked_at": checked_at, "failing": failing, "checks": checks}


# ---------------------------------------------------------------------------
# Pure-function tests: _level_text / _format_freshness
# ---------------------------------------------------------------------------


def test_level_text_green_is_all_ok():
    assert _level_text("green", 0) == "all required checks ok"


def test_level_text_yellow_singular():
    assert _level_text("yellow", 1) == "1 required check degraded"


def test_level_text_yellow_plural():
    assert _level_text("yellow", 2) == "2 required checks degraded"


def test_level_text_red_singular():
    assert _level_text("red", 1) == "1 required check failing"


def test_level_text_red_plural():
    assert _level_text("red", 3) == "3 required checks failing"


def test_level_text_unrecognized_level_falls_back_to_unknown():
    assert _level_text("bogus", 0) == "status unknown"


def test_format_freshness_unknown_when_checked_at_is_none():
    assert _format_freshness(None) == "as of — (unknown)"


def test_format_freshness_formats_a_real_timestamp():
    text = _format_freshness(time.time())
    assert text.startswith("as of ")
    assert text.endswith("ago)")


# ---------------------------------------------------------------------------
# Pure-function tests: _format_row
# ---------------------------------------------------------------------------


def test_format_row_required_ok_check_not_dimmed():
    row = _format_row(_check("iris-whisper", "ok", required=True, detail="running"))
    assert row == ("✓ iris-whisper", "ok", "yes", "running")


def test_format_row_required_down_check_uses_down_glyph():
    row = _format_row(_check("iris-kokoro", "down", required=True, detail="not running"))
    assert row == ("✗ iris-kokoro", "down", "yes", "not running")


def test_format_row_optional_check_is_dimmed():
    row = _format_row(_check("nice-to-have", "down", required=False, detail="meh"))
    assert row == (
        "[dim]✗ nice-to-have[/]",
        "[dim]down[/]",
        "[dim]no[/]",
        "[dim]meh[/]",
    )


def test_format_row_degraded_and_absent_and_unknown_glyphs():
    assert _format_row(_check("a", "degraded"))[0] == "! a"
    assert _format_row(_check("b", "absent"))[0] == "– b"
    assert _format_row(_check("c", "unknown"))[0] == "? c"


# ---------------------------------------------------------------------------
# Pure-function tests: _collapse_rows (5+-row collapsing, ti-pugo3.3 DESIGN)
# ---------------------------------------------------------------------------


def test_collapse_rows_below_threshold_shows_all_individually():
    checks = [_check(f"svc-{i}") for i in range(3)]
    rows = _collapse_rows(checks)
    assert len(rows) == 3
    assert all(row[0].startswith("✓ svc-") for row in rows)


def test_collapse_rows_at_exact_threshold_does_not_collapse():
    checks = [_check(f"svc-{i}") for i in range(_OK_COLLAPSE_THRESHOLD)]
    rows = _collapse_rows(checks)
    assert len(rows) == _OK_COLLAPSE_THRESHOLD
    assert not any("more checks" in row[0] for row in rows)


def test_collapse_rows_above_threshold_collapses_with_summary_row():
    checks = [_check(f"svc-{i}") for i in range(_OK_COLLAPSE_THRESHOLD + 2)]
    rows = _collapse_rows(checks)
    assert len(rows) == _OK_COLLAPSE_THRESHOLD + 1
    assert rows[-1] == ("[dim]… 2 more checks, all ok …[/]", "", "", "")


def test_collapse_rows_non_ok_check_breaks_the_run_and_is_never_collapsed():
    checks = (
        [_check(f"ok-{i}") for i in range(_OK_COLLAPSE_THRESHOLD + 3)]
        + [_check("broken", "down")]
        + [_check(f"ok-after-{i}") for i in range(2)]
    )
    rows = _collapse_rows(checks)
    # The leading run of (threshold+3) ok checks collapses to threshold rows
    # plus one summary row for the 3 hidden ones.
    assert rows[_OK_COLLAPSE_THRESHOLD] == ("[dim]… 3 more checks, all ok …[/]", "", "", "")
    # The broken check always shows individually — never folded into a
    # collapse row even though it sits right after one.
    assert rows[_OK_COLLAPSE_THRESHOLD + 1][0] == "✗ broken"
    # The short trailing run (below threshold) shows individually too.
    assert len(rows) == _OK_COLLAPSE_THRESHOLD + 1 + 1 + 2


# ---------------------------------------------------------------------------
# HealthScreen instance-method tests: _summary_text / _fixes_text
# (constructed directly, no Pilot/mount needed — neither method touches
# self.app or queries the DOM)
# ---------------------------------------------------------------------------


def test_summary_text_direct_mode_no_baseline():
    screen = HealthScreen(None, direct_mode=True)
    assert "direct mode" in screen._summary_text()


def test_summary_text_proxy_mode_no_baseline_yet():
    screen = HealthScreen(None, direct_mode=False)
    assert screen._summary_text() == "No baseline health data yet from this daemon."


def test_summary_text_with_baseline_shows_level_and_freshness():
    screen = HealthScreen(_baseline("red", [_check("x", "down")], checked_at=1000.0), direct_mode=False)
    text = screen._summary_text()
    assert "🔴" in text
    assert "1 required check failing" in text
    assert "as of " in text


def test_fixes_text_absent_when_no_baseline():
    screen = HealthScreen(None, direct_mode=True)
    assert screen._fixes_text() == ""


def test_fixes_text_absent_when_all_required_checks_ok():
    screen = HealthScreen(_baseline("green", [_check("a", "ok")]), direct_mode=False)
    assert screen._fixes_text() == ""


def test_fixes_text_ignores_broken_optional_checks():
    baseline = _baseline("green", [_check("optional", "down", required=False)])
    screen = HealthScreen(baseline, direct_mode=False)
    assert screen._fixes_text() == ""


def test_fixes_text_present_with_fix_line():
    checks = [_check("iris-kokoro", "down", required=True, fix="systemctl --user start iris-kokoro")]
    screen = HealthScreen(_baseline("red", checks), direct_mode=False)
    text = screen._fixes_text()
    assert "FIXES" in text
    assert "iris-kokoro  →  systemctl --user start iris-kokoro" in text


def test_fixes_text_no_fix_available_fallback():
    checks = [_check("mystery-thing", "down", required=True, fix="")]
    screen = HealthScreen(_baseline("red", checks), direct_mode=False)
    text = screen._fixes_text()
    assert "mystery-thing  →  (no fix available — see docs)" in text


# ---------------------------------------------------------------------------
# IrisConsole pill state tests (ti-pugo3.3.2 DESIGN: healthy / degraded /
# failing / pending / omitted-in-direct-mode)
# ---------------------------------------------------------------------------


def test_health_pill_pending_before_first_heartbeat():
    app = IrisConsole()
    app._baseline = None
    assert app._health_pill() == "[dim]⚪ health…[/]"


def test_health_pill_healthy_green():
    app = IrisConsole()
    app._baseline = _baseline("green", [])
    assert app._health_pill() == "[#56d364]🟢 health ✓[/]"


def test_health_pill_degraded_yellow_shows_failing_count():
    app = IrisConsole()
    app._baseline = _baseline("yellow", [_check("a", "degraded"), _check("b", "degraded")])
    assert app._health_pill() == "[#d29922]🟡 health !(2)[/]"


def test_health_pill_failing_red_shows_failing_count():
    app = IrisConsole()
    app._baseline = _baseline("red", [_check("a", "down")])
    assert app._health_pill() == "[#f38ba8]🔴 health ✗(1)[/]"


def test_health_pill_unrecognized_level_falls_back_to_pending_glyph():
    app = IrisConsole()
    app._baseline = _baseline("bogus", [])
    assert app._health_pill() == "[dim]⚪ health…[/]"


def test_refresh_status_includes_health_pill_in_proxy_mode():
    async def scenario():
        app = IrisConsole()
        async with app.run_test(size=(120, 40)) as pilot:
            app._mode = "proxy"
            app._baseline = _baseline("green", [])
            app._refresh_status()
            await pilot.pause()
            plain = app.query_one("#status", Static).render().plain
            assert "health ✓" in plain

    asyncio.run(scenario())


def test_refresh_status_omits_health_pill_in_direct_mode():
    """Regression guard: even with baseline data present, direct mode must not
    show the pill (it's daemon-only data — ti-pugo3.3 DESIGN's 5th state).
    The gate lives in _refresh_status(), not in _health_pill() itself."""
    async def scenario():
        app = IrisConsole()
        async with app.run_test(size=(120, 40)) as pilot:
            app._mode = "direct"
            app._baseline = _baseline("green", [])  # present, but must still be hidden
            app._refresh_status()
            await pilot.pause()
            plain = app.query_one("#status", Static).render().plain
            assert "health" not in plain

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# check_action() gate regression test (ti-pugo3.3 DESIGN): "q" must close
# HealthScreen, not fall through to app-quit — the same bug pattern already
# guarded for ContactsScreen (see test_contacts_panel.py's test_q_closes_screen,
# which runs the sequence but asserts nothing; this is the stronger version
# DESIGN calls for).
# ---------------------------------------------------------------------------


def test_h_opens_health_screen_and_q_closes_it_without_quitting_app():
    async def scenario():
        app = IrisConsole()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("H")
            await pilot.pause()
            assert isinstance(app.screen, HealthScreen)

            await pilot.press("q")
            await pilot.pause()
            assert not isinstance(app.screen, HealthScreen)
            assert app.is_running  # app survived the close instead of quitting

            # Round-trip a second time to prove the app is still fully responsive,
            # not just mid-teardown when the assertions above happened to run.
            await pilot.press("H")
            await pilot.pause()
            assert isinstance(app.screen, HealthScreen)

            await pilot.press("q")
            await pilot.pause()
            assert not isinstance(app.screen, HealthScreen)

            await pilot.press("q")

    asyncio.run(scenario())
