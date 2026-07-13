"""IrisConsole wiring for Save/finalize (ti-viv73), scenarios 13-15.

Deliberately narrow scope: ti-co6cj already shipped (closed, PASS, 35 tests
across tests/test_post_call_review.py + tests/test_post_call_review_wiring.py)
full coverage of _maybe_show_post_call_review's dedup guard and its three
missing-data guards (no call card / no contact_id / unknown contact), plus
the call_card_recap_ready immediate-push and call_card_ended 2.5s fallback
timer -- all of that is ti-qyo3p-scope (pre-existing, untouched by ti-viv73).
Re-testing it here would just be duplicate coverage of the same code path.

What ti-viv73 actually added to app.py, and what this file covers instead:

  - on_save_requested: the three failure branches (proxy None / DaemonNotRunning
    / ack not ok), each of which must write a red console line via self._w(...)
    AND call the CURRENT screen's on_save_failed() -- but only when that screen
    is the PostCallReviewScreen for THIS session_id, not some other screen the
    operator has since navigated to.
  - _on_daemon_event's call_card_written_back branch: routes to on_saved(fresh)
    or on_save_failed() (never raises) depending on whether the store still has
    the card, guarded the same way.
  - _maybe_show_post_call_review: confirms session_id is threaded through as
    PostCallReviewScreen's 5th positional constructor arg (a one-line, narrow
    check -- NOT re-covering the guards themselves, see above).

Bare IrisConsole() construction with attribute overrides follows the existing
precedent in test_contacts_panel.py (app._roster = roster) and
test_trust_grant_app.py (app = IrisConsole(); async with app.run_test() ...).
Message handlers (on_save_requested, _on_daemon_event) are called directly as
plain methods rather than routed through a live daemon queue or Message
bubbling -- consistent with calling screen.action_save() directly elsewhere in
this suite.
"""
from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

from iris.console.app import IrisConsole  # noqa: E402
from iris.console.post_call_review import (  # noqa: E402
    PostCallReviewScreen,
    SaveRequested,
    _ReviewPhase,
)
from iris.daemon.proxy import DaemonNotRunning  # noqa: E402
from iris.roster import Contact  # noqa: E402


class _FakeProxy:
    def __init__(self, *, ack=None, raise_not_running=False):
        self.ack = ack if ack is not None else {"ok": True}
        self.raise_not_running = raise_not_running
        self.sent = []

    def send(self, cmd):
        self.sent.append(cmd)
        if self.raise_not_running:
            raise DaemonNotRunning("daemon not running")
        return self.ack

    def close(self):
        pass


class _FakeCallCardStore:
    def __init__(self, cards=None):
        self._cards = cards or {}

    def get_call_card(self, session_id):
        return self._cards.get(session_id, {})


class _FakeRoster:
    def __init__(self, contacts=None):
        self._contacts = contacts or {}

    def get(self, contact_id):
        return self._contacts.get(contact_id)


class _FakeAfterStore:
    def get_open_commitments(self, contact_id):
        return []


def _contact(**overrides) -> Contact:
    base = dict(
        id=7,
        display_name="Alice Johnson",
        phone_e164="+15550001",
        handling_rule="normal",
        trust_tier="demo",
        relationship_notes="",
        created_at=0.0,
        updated_at=0.0,
    )
    base.update(overrides)
    return Contact(**base)


def _call_card(**overrides) -> dict:
    base = dict(
        facts=[],
        action_items=[],
        outcome_summary="Discussed the account.",
        started_at=1_000.0,
        ended_at=1_090.0,
        disclosure_ack_ts=None,
        caller_number="+15550001",
    )
    base.update(overrides)
    return base


def _review_screen(session_id="sess-1", **kwargs) -> PostCallReviewScreen:
    return PostCallReviewScreen(
        _contact(), _call_card(), [], _FakeAfterStore(), session_id, **kwargs
    )


# ---------------------------------------------------------------------------
# Scenario 13: on_save_requested's three failure branches
# ---------------------------------------------------------------------------

def test_on_save_requested_proxy_none_writes_red_message_and_fails_screen():
    app = IrisConsole()
    screen = _review_screen("sess-1")
    written = []

    async def scenario():
        async with app.run_test() as pilot:
            # Set after mount, not before: on_mount() unconditionally tries a
            # real daemon connection and would otherwise clobber this with
            # whatever that connection attempt resolves to.
            app._proxy = None
            monkeypatch_w = written.append
            app._w = monkeypatch_w
            await app.push_screen(screen)
            await pilot.pause()
            screen.action_save()  # phase -> SAVING, as the real flow would do first
            await pilot.pause()
            app.on_save_requested(SaveRequested("sess-1"))
            await pilot.pause()

    asyncio.run(scenario())
    assert any("Daemon disconnected" in line for line in written)
    assert screen._phase.value == "reviewing"
    assert screen._save_failed is True


def test_on_save_requested_daemon_not_running_writes_red_message_and_fails_screen():
    app = IrisConsole()
    screen = _review_screen("sess-1")
    written = []

    async def scenario():
        async with app.run_test() as pilot:
            app._proxy = _FakeProxy(raise_not_running=True)  # after mount, see above
            app._w = written.append
            await app.push_screen(screen)
            await pilot.pause()
            screen.action_save()  # phase -> SAVING, as the real flow would do first
            await pilot.pause()
            app.on_save_requested(SaveRequested("sess-1"))
            await pilot.pause()

    asyncio.run(scenario())
    assert any("Daemon disconnected" in line for line in written)
    assert screen._save_failed is True


def test_on_save_requested_ack_not_ok_writes_error_and_fails_screen():
    app = IrisConsole()
    screen = _review_screen("sess-1")
    written = []

    async def scenario():
        async with app.run_test() as pilot:
            app._proxy = _FakeProxy(ack={"ok": False, "error": "disk full"})  # after mount
            app._w = written.append
            await app.push_screen(screen)
            await pilot.pause()
            screen.action_save()  # phase -> SAVING, as the real flow would do first
            await pilot.pause()
            app.on_save_requested(SaveRequested("sess-1"))
            await pilot.pause()

    asyncio.run(scenario())
    assert any("Save failed" in line and "disk full" in line for line in written)
    assert screen._save_failed is True


def test_on_save_requested_sends_finalize_call_card_with_session_id():
    app = IrisConsole()
    proxy = _FakeProxy(ack={"ok": True})
    screen = _review_screen("sess-99")

    async def scenario():
        async with app.run_test() as pilot:
            app._proxy = proxy  # after mount, see above
            app._w = lambda *a, **k: None
            await app.push_screen(screen)
            await pilot.pause()
            app.on_save_requested(SaveRequested("sess-99"))
            await pilot.pause()

    asyncio.run(scenario())
    assert proxy.sent == [{"cmd": "finalize_call_card", "session_id": "sess-99"}]


def test_on_save_requested_ack_ok_writes_nothing_and_does_not_touch_screen():
    app = IrisConsole()
    screen = _review_screen("sess-1")
    written = []

    async def scenario():
        async with app.run_test() as pilot:
            app._proxy = _FakeProxy(ack={"ok": True})  # after mount, see above
            app._w = written.append
            await app.push_screen(screen)
            await pilot.pause()
            screen.action_save()  # phase -> SAVING, as the real flow would do first
            await pilot.pause()
            app.on_save_requested(SaveRequested("sess-1"))
            await pilot.pause()

    asyncio.run(scenario())
    assert written == []
    assert screen._phase.value == "saving"  # unchanged -- waits for call_card_written_back
    assert screen._save_failed is False


def test_on_save_requested_does_not_fail_screen_for_different_session_id():
    """sess-1 is saving elsewhere while the operator is on a screen for
    sess-2 that is independently mid-save too. sess-1's failure ack must
    not reach into sess-2's unrelated SAVING screen.

    other_screen is put in SAVING (not left at the REVIEWING default)
    specifically so this test exercises the session_id guard in
    on_save_requested: on_save_failed() has its own internal phase guard
    (no-ops unless SAVING) that would otherwise independently mask a
    missing/broken session_id guard, since a REVIEWING screen wouldn't
    observably change either way.
    """
    app = IrisConsole()
    other_screen = _review_screen("sess-2")

    async def scenario():
        async with app.run_test() as pilot:
            app._proxy = None  # forces the failure branch; after mount, see above
            app._w = lambda *a, **k: None
            await app.push_screen(other_screen)
            await pilot.pause()
            other_screen._phase = _ReviewPhase.SAVING
            app.on_save_requested(SaveRequested("sess-1"))
            await pilot.pause()

    asyncio.run(scenario())
    assert other_screen._phase is _ReviewPhase.SAVING
    assert other_screen._save_failed is False


# ---------------------------------------------------------------------------
# Scenario 14: _on_daemon_event's call_card_written_back branch
# ---------------------------------------------------------------------------

def test_call_card_written_back_calls_on_saved_when_screen_matches():
    app = IrisConsole()
    fresh_card = _call_card(outcome_summary="fresh from server")
    app._call_card_store = _FakeCallCardStore({"sess-1": fresh_card})
    screen = _review_screen("sess-1")

    async def scenario():
        async with app.run_test() as pilot:
            await app.push_screen(screen)
            await pilot.pause()
            screen.action_save()
            await pilot.pause()
            app._on_daemon_event({"event": "call_card_written_back", "session_id": "sess-1"})
            await pilot.pause()

    asyncio.run(scenario())
    assert screen._phase.value == "saved"
    assert screen._call_card["outcome_summary"] == "fresh from server"


def test_call_card_written_back_calls_on_save_failed_when_card_missing():
    app = IrisConsole()
    app._call_card_store = _FakeCallCardStore({})  # get_call_card returns {} (falsy)
    screen = _review_screen("sess-1")

    async def scenario():
        async with app.run_test() as pilot:
            await app.push_screen(screen)
            await pilot.pause()
            screen.action_save()
            await pilot.pause()
            app._on_daemon_event({"event": "call_card_written_back", "session_id": "sess-1"})
            await pilot.pause()

    asyncio.run(scenario())
    assert screen._phase.value == "reviewing"
    assert screen._save_failed is True


def test_call_card_written_back_is_noop_when_screen_does_not_match():
    app = IrisConsole()
    app._call_card_store = _FakeCallCardStore({"sess-1": _call_card()})
    other_screen = _review_screen("sess-2")

    async def scenario():
        async with app.run_test() as pilot:
            await app.push_screen(other_screen)
            await pilot.pause()
            # SAVING (not the REVIEWING default): on_saved()/on_save_failed()
            # each no-op unless SAVING, which would mask a missing/broken
            # session_id guard below -- see the sibling test's docstring in
            # test_on_save_requested_does_not_fail_screen_for_different_session_id.
            other_screen._phase = _ReviewPhase.SAVING
            # Must not raise even though the event is for a session with no
            # matching screen currently pushed.
            app._on_daemon_event({"event": "call_card_written_back", "session_id": "sess-1"})
            await pilot.pause()

    asyncio.run(scenario())
    assert other_screen._phase is _ReviewPhase.SAVING
    assert other_screen._save_failed is False


# ---------------------------------------------------------------------------
# Scenario 15: _maybe_show_post_call_review threads session_id positionally
# ---------------------------------------------------------------------------

def test_maybe_show_post_call_review_threads_session_id_into_screen():
    app = IrisConsole()
    app._call_card_store = _FakeCallCardStore({"sess-77": _call_card(contact_id=7)})
    app._roster = _FakeRoster({7: _contact(id=7)})
    app._after_store = _FakeAfterStore()

    async def scenario():
        async with app.run_test() as pilot:
            app._maybe_show_post_call_review("sess-77")
            await pilot.pause()
            return app.screen

    pushed = asyncio.run(scenario())
    assert isinstance(pushed, PostCallReviewScreen)
    assert pushed.session_id == "sess-77"
