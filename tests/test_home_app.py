"""Tests for HomeApp Textual dashboard widget logic (ti-6qsb.1).

These tests FAIL until the builder implements iris/console/home.py.
Skipped when textual is not installed (it's an optional extra).
"""
from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# MessagesPanel — unread badge count
# ---------------------------------------------------------------------------

def test_messages_panel_badge_count_reflects_unread():
    from iris.console.home import HomeApp

    async def scenario():
        store = MagicMock()
        store.unread.return_value = [MagicMock(), MagicMock()]  # 2 unread
        app = HomeApp(message_store=store)
        async with app.run_test() as pilot:
            from iris.console.home import MessagesPanel
            panel = app.query_one(MessagesPanel)
            badge = panel.unread_count
            assert badge == 2
            await pilot.press("q")

    asyncio.run(scenario())


def test_messages_panel_badge_zero_when_all_read():
    from iris.console.home import HomeApp

    async def scenario():
        store = MagicMock()
        store.unread.return_value = []
        app = HomeApp(message_store=store)
        async with app.run_test() as pilot:
            from iris.console.home import MessagesPanel
            panel = app.query_one(MessagesPanel)
            assert panel.unread_count == 0
            await pilot.press("q")

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# [n] cycles notification focus
# ---------------------------------------------------------------------------

def test_n_key_cycles_notification_focus():
    from iris.console.home import HomeApp, NotificationsPanel

    async def scenario():
        app = HomeApp()
        async with app.run_test() as pilot:
            panel = app.query_one(NotificationsPanel)
            initial_focus = panel.focused_index
            await pilot.press("n")
            after_focus = panel.focused_index
            # After pressing n, focus index should have advanced
            assert after_focus != initial_focus or panel.item_count <= 1
            await pilot.press("q")

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# [d] dismisses focused notification
# ---------------------------------------------------------------------------

def test_d_key_dismisses_focused_notification():
    from iris.console.home import HomeApp, NotificationsPanel

    async def scenario():
        store = MagicMock()
        store.next_pending.return_value = MagicMock(id=42, priority=1,
                                                    message="test")
        app = HomeApp(proactive_store=store)
        async with app.run_test() as pilot:
            panel = app.query_one(NotificationsPanel)
            panel._focused_id = 42
            await pilot.press("d")
            store.dismiss.assert_called_once_with(42)
            await pilot.press("q")

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# [m] calls mark_all_read
# ---------------------------------------------------------------------------

def test_m_key_calls_mark_all_read():
    from iris.console.home import HomeApp

    async def scenario():
        store = MagicMock()
        store.unread.return_value = []
        app = HomeApp(message_store=store)
        async with app.run_test() as pilot:
            await pilot.press("m")
            store.mark_all_read.assert_called_once()
            await pilot.press("q")

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Brain-unavailable banner on mount
# ---------------------------------------------------------------------------

def test_brain_unavailable_banner_shown_when_brain_unreachable():
    from iris.console.home import HomeApp

    async def scenario():
        brain = MagicMock()
        brain.is_reachable.return_value = False
        app = HomeApp(brain=brain)
        async with app.run_test() as pilot:
            # Banner text should contain "unavailable" or similar
            text = app.screen.query("ResponsePanel").first().renderable
            assert "unavailable" in str(text).lower() or \
                   any("unavailable" in str(w.renderable).lower()
                       for w in app.screen.walk_children())
            await pilot.press("q")

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# InputBar submits to Brain and clears
# ---------------------------------------------------------------------------

def test_input_bar_submits_to_brain_and_clears():
    from iris.console.home import HomeApp

    async def scenario():
        brain = MagicMock()
        brain.is_reachable.return_value = True
        brain.respond = MagicMock(return_value=MagicMock(text="hello"))
        app = HomeApp(brain=brain)
        async with app.run_test() as pilot:
            await pilot.click("#input-bar")
            for ch in "show me my messages":
                await pilot.press("space" if ch == " " else ch)
            await pilot.press("enter")
            # Input should clear after submit
            from textual.widgets import Input
            inp = app.query_one(Input)
            assert inp.value == ""
            await pilot.press("q")

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# [c] pushes and pops ScopeManifestModal
# ---------------------------------------------------------------------------

def test_c_key_pushes_scope_manifest_modal():
    from iris.console.home import HomeApp, ScopeManifestModal

    async def scenario():
        app = HomeApp()
        async with app.run_test() as pilot:
            await pilot.press("c")
            # Modal should now be on the screen stack
            assert isinstance(app.screen, ScopeManifestModal)
            await pilot.press("escape")
            # After escape, modal is gone (Textual may not restore HomeApp as top screen)
            assert not isinstance(app.screen, ScopeManifestModal)
            await pilot.press("q")

    asyncio.run(scenario())


def test_c_key_pressed_twice_pops_scope_modal():
    from iris.console.home import HomeApp, ScopeManifestModal

    async def scenario():
        app = HomeApp()
        async with app.run_test() as pilot:
            await pilot.press("c")  # open
            assert isinstance(app.screen, ScopeManifestModal)
            await pilot.press("c")  # close
            assert not isinstance(app.screen, ScopeManifestModal)
            await pilot.press("q")

    asyncio.run(scenario())
