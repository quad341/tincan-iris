"""Live-render smoke for the console side panels (regression for the [V]/[L] crash).

These MOUNT the panels in a real Textual app and render them. The earlier stubbed
unit tests missed two things that only surface on render:
  - ListPanel._render() collided with Textual's internal Widget._render() → crash
    the moment [L] made it visible.
  - An empty CallCardPanel rendered as nothing, so [V] "showed nothing".
"""
from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult
from textual.containers import Horizontal

from iris.console.app import ListPanel
from iris.console.call_card import CallCardPanel, FactCard


class _Harness(App):
    def compose(self) -> ComposeResult:
        with Horizontal():
            yield ListPanel()
            yield CallCardPanel(id="call-card-panel")


def test_call_card_panel_renders_with_placeholder_then_card():
    async def body():
        app = _Harness()
        async with app.run_test(size=(120, 40)) as pilot:
            panel = app.query_one(CallCardPanel)
            panel.add_class("visible-panel")
            await pilot.pause()
            # Empty panel shows a visible placeholder (not "nothing").
            assert app.query_one("#cc-empty").display
            # A fact arrives -> a card mounts, placeholder hides.
            panel.handle_event({
                "event": "call_card_fact", "session_id": "s1",
                "fact": {"session_id": "s1", "fact_type": "amount", "raw_text": "$5",
                         "normalized_value": "$5.00", "critical": False, "confidence": 0.9},
            })
            await pilot.pause()
            assert len(app.query(FactCard)) == 1
            assert not app.query_one("#cc-empty").display

    asyncio.run(body())


def test_list_panel_renders_visible_without_crash():
    async def body():
        app = _Harness()
        async with app.run_test(size=(120, 40)) as pilot:
            lp = app.query_one(ListPanel)
            lp.add_item("a call-list item")   # goes through _refresh (was _render)
            lp.add_class("visible-panel")
            await pilot.pause()               # renders — would AttributeError if _render collided

    asyncio.run(body())
