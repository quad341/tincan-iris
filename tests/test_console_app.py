"""Smoke test for the Textual console — verifies the app mounts and a key wires
through to the Conductor. Skipped when textual isn't installed (it's an optional
extra; the pipeline logic itself is covered in test_conductor). Uses asyncio.run
so no pytest-async plugin is needed."""
from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

from iris.console.app import IrisConsole  # noqa: E402
from iris.console.conductor import State  # noqa: E402


def test_console_mounts_and_mute_key_toggles():
    async def scenario():
        app = IrisConsole()
        async with app.run_test() as pilot:
            assert app.conductor.muted is False
            await pilot.press("m")          # mute key -> conductor.toggle_mute
            assert app.conductor.muted is True
            await pilot.press("a")          # approve respondent commands -> flag
            assert app._approved is True
            await pilot.press("f")          # hear respondent (no STT in CI: safe no-op)
            await pilot.press("c")          # dump commands (must not error)
            await pilot.press("q")          # quit

    asyncio.run(scenario())


# --- _on_heard speaking gate (ti-lfp) -----------------------------------------

def test_on_heard_gate_suppresses_when_speaking():
    async def scenario():
        app = IrisConsole()
        async with app.run_test() as pilot:
            # Drain any startup events posted before we start checking.
            while not app.events.empty():
                app.events.get_nowait()

            app.conductor.state = State.SPEAKING
            assert app.conductor.speaking is True
            app._on_heard("hello", "operator")
            # No await between call and assertion — no timer ticks in between.
            assert app.events.empty()

            app.conductor.state = State.IDLE
            assert app.conductor.speaking is False
            app._on_heard("hello", "operator")
            assert app.events.get_nowait() == ("heard", "hello", "operator")

            await pilot.press("q")

    asyncio.run(scenario())


def test_on_heard_gate_suppresses_when_thinking():
    async def scenario():
        app = IrisConsole()
        async with app.run_test() as pilot:
            while not app.events.empty():
                app.events.get_nowait()

            app.conductor.state = State.THINKING
            assert app.conductor.speaking is True
            app._on_heard("what time is it", "operator")
            assert app.events.empty()

            await pilot.press("q")

    asyncio.run(scenario())
