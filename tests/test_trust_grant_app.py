"""Textual integration tests for the [g] grant keybinding and status bar.

ti-qt1i.1.5 (Textual half) — written BEFORE builder implementation (TDD red phase).
Skipped when textual is not installed; fails until ti-qt1i.1.3 implements the
[g] keybinding, action_grant(), and the updated _refresh_status().
"""
from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

from textual.widgets import Static

from iris.console.app import IrisConsole
from iris.trust import TrustMode


def _status_text(app: IrisConsole) -> str:
    # Textual 8 dropped Static.renderable; the content accessor is `.content`.
    return str(app.query_one("#status", Static).content)


# ---------------------------------------------------------------------------
# [g] when unarmed — blocked, not silent
# ---------------------------------------------------------------------------

def test_g_key_when_unarmed_no_trust_change():
    """[g] press when unarmed must not change trust state."""
    async def scenario():
        app = IrisConsole()
        async with app.run_test() as pilot:
            assert app.conductor._armed is False
            assert app.conductor.trust_state is TrustMode.NONE
            await pilot.press("g")
            assert app.conductor.trust_state is TrustMode.NONE
            assert app.conductor.op_trust is TrustMode.DEMO
            await pilot.press("q")

    asyncio.run(scenario())


def test_g_key_when_unarmed_logs_error():
    """[g] press when unarmed must write an error — iris-arm instruction, not silence."""
    async def scenario():
        app = IrisConsole()
        logged: list[str] = []
        _orig = app._w
        app._w = lambda msg: logged.append(msg) or _orig(msg)

        async with app.run_test() as pilot:
            await pilot.press("g")
            combined = " ".join(logged).lower()
            assert "arm" in combined or "unarmed" in combined
            await pilot.press("q")

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# [g] three-press cycle when armed
# ---------------------------------------------------------------------------

def test_g_key_three_press_cycle():
    """arm + [g] ×3 produces LOCAL → BOTH → NONE trust transitions."""
    async def scenario():
        app = IrisConsole()
        async with app.run_test() as pilot:
            app.conductor.arm()

            await pilot.press("g")
            assert app.conductor.trust_state is TrustMode.LOCAL
            assert app.conductor.op_trust is TrustMode.FULL
            assert app.conductor.far_trust is TrustMode.DEMO

            await pilot.press("g")
            assert app.conductor.trust_state is TrustMode.BOTH
            assert app.conductor.op_trust is TrustMode.FULL
            assert app.conductor.far_trust is TrustMode.FULL

            await pilot.press("g")
            assert app.conductor.trust_state is TrustMode.NONE
            assert app.conductor.op_trust is TrustMode.DEMO
            assert app.conductor.far_trust is TrustMode.DEMO

            await pilot.press("q")

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Status bar reflects UNARMED / ARMED / LOCAL / BOTH
# ---------------------------------------------------------------------------

def test_status_bar_shows_unarmed_by_default():
    """'⚠ UNARMED' appears in status bar when the console is not armed."""
    async def scenario():
        app = IrisConsole()
        async with app.run_test() as pilot:
            assert "UNARMED" in _status_text(app)
            await pilot.press("q")

    asyncio.run(scenario())


def test_status_bar_shows_armed_after_arm():
    """'ARMED' appears (and 'UNARMED' does not) after conductor.arm()."""
    async def scenario():
        app = IrisConsole()
        async with app.run_test() as pilot:
            app.conductor.arm()
            app._refresh_status()
            await pilot.pause()
            text = _status_text(app)
            assert "ARMED" in text
            assert "UNARMED" not in text
            await pilot.press("q")

    asyncio.run(scenario())


def test_status_bar_shows_local_after_first_g():
    """'🔓 LOCAL' badge appears after first [g] press when armed."""
    async def scenario():
        app = IrisConsole()
        async with app.run_test() as pilot:
            app.conductor.arm()
            await pilot.press("g")
            await pilot.pause()
            assert "LOCAL" in _status_text(app)
            await pilot.press("q")

    asyncio.run(scenario())


def test_status_bar_shows_far_remote_after_second_g():
    """'🔓 FAR-REMOTE' badge appears after second [g] press (BOTH state)."""
    async def scenario():
        app = IrisConsole()
        async with app.run_test() as pilot:
            app.conductor.arm()
            await pilot.press("g")  # → LOCAL
            await pilot.press("g")  # → BOTH
            await pilot.pause()
            assert "FAR-REMOTE" in _status_text(app)
            await pilot.press("q")

    asyncio.run(scenario())


def test_status_bar_clears_trust_badges_after_revoke():
    """After third [g] press (→ NONE), trust badges disappear from status bar."""
    async def scenario():
        app = IrisConsole()
        async with app.run_test() as pilot:
            app.conductor.arm()
            await pilot.press("g")  # → LOCAL
            await pilot.press("g")  # → BOTH
            await pilot.press("g")  # → NONE (revoke)
            await pilot.pause()
            text = _status_text(app)
            assert "LOCAL" not in text
            assert "FAR-REMOTE" not in text
            await pilot.press("q")

    asyncio.run(scenario())
