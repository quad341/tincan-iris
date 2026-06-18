"""Textual pilot tests for ContactsScreen — ti-9szl / ti-wig8.

Skipped when textual isn't installed (optional console extra).
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import pytest

pytest.importorskip("textual")

from textual.app import App  # noqa: E402
from textual.widgets import Button, DataTable  # noqa: E402

from iris.console.contacts import ContactEditor, ContactsScreen  # noqa: E402
from iris.roster import Contact, ImportResult  # noqa: E402


# ---------------------------------------------------------------------------
# Roster stub
# ---------------------------------------------------------------------------

@dataclass
class _StubRoster:
    def __post_init__(self) -> None:
        self._contacts: list[Contact] = []
        self._next = 1

    def _new(self, display_name, phone_e164, handling_rule="normal",
              trust_tier="demo", relationship_notes="") -> Contact:
        c = Contact(
            id=self._next,
            display_name=display_name,
            phone_e164=phone_e164,
            handling_rule=handling_rule,
            trust_tier=trust_tier,
            relationship_notes=relationship_notes,
            created_at=time.time(),
            updated_at=time.time(),
        )
        self._next += 1
        return c

    def add(self, display_name, phone_e164, handling_rule="normal",
            trust_tier="demo", relationship_notes="") -> Contact:
        c = self._new(display_name, phone_e164, handling_rule, trust_tier, relationship_notes)
        self._contacts.append(c)
        return c

    def get_by_phone(self, phone):
        return next((c for c in self._contacts if c.phone_e164 == phone), None)

    def get(self, contact_id):
        return next((c for c in self._contacts if c.id == contact_id), None)

    def all(self):
        return list(self._contacts)

    def update(self, contact_id, *, display_name=None, handling_rule=None,
               trust_tier=None, relationship_notes=None) -> bool:
        for c in self._contacts:
            if c.id == contact_id:
                if display_name is not None:
                    object.__setattr__(c, "display_name", display_name)
                if handling_rule is not None:
                    object.__setattr__(c, "handling_rule", handling_rule)
                if trust_tier is not None:
                    object.__setattr__(c, "trust_tier", trust_tier)
                if relationship_notes is not None:
                    object.__setattr__(c, "relationship_notes", relationship_notes)
                return True
        return False

    def delete(self, contact_id) -> bool:
        for i, c in enumerate(self._contacts):
            if c.id == contact_id:
                del self._contacts[i]
                return True
        return False

    def import_contacts(self, contacts) -> ImportResult:
        for d in contacts:
            self.add(d["display_name"], d["phone_e164"])
        return ImportResult(added=len(contacts), skipped=0, conflicts=[])


def _make_roster() -> _StubRoster:
    r = _StubRoster()
    r.add("Alice Johnson", "+15550001", handling_rule="vip")
    r.add("Bob Smith", "+15550002", handling_rule="normal", relationship_notes="Old friend")
    return r


class _ContactsHostApp(App):
    """Minimal host App so ContactsScreen (a Screen) can be driven by Pilot.

    ``run_test()`` lives on ``App``, not ``Screen``; in the real console the
    panel is pushed via [K], so the tests host it the same way.
    """

    def __init__(self, roster: _StubRoster) -> None:
        super().__init__()
        self._roster = roster

    def get_default_screen(self) -> ContactsScreen:
        return ContactsScreen(self._roster)


# ---------------------------------------------------------------------------
# Pilot tests
# ---------------------------------------------------------------------------

def test_contacts_screen_mounts():
    """ContactsScreen mounts without error."""
    async def scenario():
        r = _make_roster()
        app = _ContactsHostApp(r)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
        return True

    assert asyncio.run(scenario())


def test_contacts_table_row_count():
    """Table has one row per contact plus the unknown-caller static row."""
    async def scenario():
        r = _make_roster()
        app = _ContactsHostApp(r)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            table = app.query_one("#contacts-table", DataTable)
            return table.row_count

    count = asyncio.run(scenario())
    assert count == 3  # 2 contacts + unknown-caller row


def test_editor_hidden_initially():
    """ContactEditor starts hidden."""
    async def scenario():
        r = _make_roster()
        app = _ContactsHostApp(r)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            editor = app.query_one(ContactEditor)
            return "visible" in editor.classes

    assert not asyncio.run(scenario())


def test_add_button_shows_editor():
    """Clicking Add Contact makes the editor visible."""
    async def scenario():
        r = _make_roster()
        app = _ContactsHostApp(r)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.query_one("#add-btn", Button).press()
            await pilot.pause()
            editor = app.query_one(ContactEditor)
            return "visible" in editor.classes

    assert asyncio.run(scenario())


def test_cancel_button_hides_editor():
    """Cancel button hides the open editor."""
    async def scenario():
        r = _make_roster()
        app = _ContactsHostApp(r)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.query_one("#add-btn", Button).press()
            await pilot.pause()
            app.query_one("#cancel-btn", Button).press()
            await pilot.pause()
            editor = app.query_one(ContactEditor)
            return "visible" in editor.classes

    assert not asyncio.run(scenario())


def test_search_filters_table():
    """Search field filters the table to matching contacts."""
    async def scenario():
        r = _make_roster()
        app = _ContactsHostApp(r)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.click("#contacts-search")
            await pilot.press("a", "l", "i", "c", "e")
            await pilot.pause()
            table = app.query_one("#contacts-table", DataTable)
            return table.row_count

    count = asyncio.run(scenario())
    # 1 matching + unknown-caller
    assert count == 2


def test_q_closes_screen():
    """Pressing [q] closes the ContactsScreen."""
    async def scenario():
        from iris.console.app import IrisConsole
        roster = _make_roster()
        app = IrisConsole()
        app._roster = roster
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("K")
            await pilot.pause()
            await pilot.press("q")
            await pilot.pause()
            await pilot.press("q")

    asyncio.run(scenario())
