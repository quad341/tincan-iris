"""IrisConsole <-> PostCallReviewScreen wiring regression guard (ti-qyo3p).

Written as ti-co6cj (validator phase). Covers what test_post_call_review.py's
minimal _ReviewHostApp harness can't: the two real daemon-event triggers
(call_card_recap_ready immediate / call_card_ended's bounded-wait fallback),
the _post_call_review_shown dedup guard, the missing-data guards inside
_maybe_show_post_call_review's try/except, and the "q must close the review
screen, not quit the whole app" priority-binding gate in
IrisConsole.check_action (the hazard documented directly in
post_call_review.py's own BINDINGS comment and in check_action's "quit" case).

IrisConsole() constructs CallCardStore()/RosterStore()/AfterStore() with no
path argument, which all fall back to shared on-disk defaults under
~/.local/share/iris/ -- confirmed live and already touched (mtimes from
today) on this machine, presumably by other concurrent gc-rig sessions using
the same $HOME. Every test here immediately swaps in fresh instances pointed
at tmp_path before dispatching any event, so seeded rows can't collide with
(or leak into) that shared state. See the ti-co6cj handoff notes for a
follow-up bead on test_console_app.py's existing suite, which does not do
this and shares that default path across its ~30 IrisConsole() tests.
"""
from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

from iris.capture.after_store import AfterStore
from iris.capture.store import CallCardStore
from iris.console.app import IrisConsole
from iris.console.post_call_review import PostCallReviewScreen
from iris.roster import RosterStore


def _fresh_stores(tmp_path):
    return (
        CallCardStore(db_path=tmp_path / "call_cards.db"),
        RosterStore(path=tmp_path / "roster.db"),
        AfterStore(db_path=tmp_path / "after.db"),
    )


def _app_with_isolated_stores(tmp_path):
    app = IrisConsole()
    call_card_store, roster, after_store = _fresh_stores(tmp_path)
    app._call_card_store = call_card_store
    app._roster = roster
    app._after_store = after_store
    return app, call_card_store, roster, after_store


def _seed(call_card_store, roster, *, session_id="sess-1", caller_number="+15551234567", with_contact=True):
    """Seed a call_cards row (and, unless with_contact=False, a matching
    roster contact) so _maybe_show_post_call_review's lookups succeed."""
    contact_id = None
    if with_contact:
        contact_id = roster.add("Jane Doe", caller_number, trust_tier="full").id
    call_card_store.load_or_create(session_id, caller_number, contact_id=contact_id)
    return contact_id


def _dispatch(app, event: str, session_id: str = "sess-1") -> None:
    app.events.put(("daemon_event", {"event": event, "session_id": session_id}))
    app._drain()


# --- primary trigger: call_card_recap_ready -------------------------------

def test_call_card_recap_ready_pushes_review_screen_immediately(tmp_path):
    async def scenario():
        app, call_card_store, roster, _after = _app_with_isolated_stores(tmp_path)
        _seed(call_card_store, roster)
        async with app.run_test() as pilot:
            await pilot.pause()
            _dispatch(app, "call_card_recap_ready")
            await pilot.pause()
            assert isinstance(app.screen, PostCallReviewScreen)

    asyncio.run(scenario())


# --- NFR2 fallback: call_card_ended + bounded-wait timer ------------------

def test_call_card_ended_alone_schedules_a_fallback_timer():
    """No API key configured means call_card_recap_ready never fires;
    call_card_ended alone must schedule (not immediately run) a 2.5s
    fallback via set_timer rather than pushing synchronously."""
    async def scenario():
        app = IrisConsole()
        calls = []
        app.set_timer = lambda delay, callback, **kw: calls.append((delay, callback))
        async with app.run_test() as pilot:
            await pilot.pause()
            _dispatch(app, "call_card_ended")
            await pilot.pause()
            assert not isinstance(app.screen, PostCallReviewScreen)
            assert len(calls) == 1
            assert calls[0][0] == 2.5

    asyncio.run(scenario())


def test_call_card_ended_fallback_timer_firing_pushes_review_screen(tmp_path):
    async def scenario():
        app, call_card_store, roster, _after = _app_with_isolated_stores(tmp_path)
        _seed(call_card_store, roster)
        calls = []
        app.set_timer = lambda delay, callback, **kw: calls.append((delay, callback))
        async with app.run_test() as pilot:
            await pilot.pause()
            _dispatch(app, "call_card_ended")
            await pilot.pause()
            assert len(calls) == 1
            calls[0][1]()  # simulate the 2.5s fallback elapsing
            await pilot.pause()
            assert isinstance(app.screen, PostCallReviewScreen)

    asyncio.run(scenario())


# --- dedup guard -----------------------------------------------------------

def test_second_trigger_for_same_session_is_a_noop(tmp_path):
    """Whichever of the two triggers fires first wins; the other (here,
    recap_ready firing twice, standing in for the ended-fallback racing it)
    must not push a second screen on top."""
    async def scenario():
        app, call_card_store, roster, _after = _app_with_isolated_stores(tmp_path)
        _seed(call_card_store, roster)
        async with app.run_test() as pilot:
            await pilot.pause()
            _dispatch(app, "call_card_recap_ready")
            await pilot.pause()
            first_screen = app.screen
            assert isinstance(first_screen, PostCallReviewScreen)

            _dispatch(app, "call_card_recap_ready")
            await pilot.pause()
            assert app.screen is first_screen

    asyncio.run(scenario())


# --- missing-data guards (try/except body in _maybe_show_post_call_review) --

def test_no_call_card_row_does_not_push_screen(tmp_path):
    async def scenario():
        app, _store, _roster, _after = _app_with_isolated_stores(tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            _dispatch(app, "call_card_recap_ready", session_id="never-seeded")
            await pilot.pause()
            assert not isinstance(app.screen, PostCallReviewScreen)

    asyncio.run(scenario())


def test_call_card_with_no_contact_id_does_not_push_screen(tmp_path):
    async def scenario():
        app, call_card_store, roster, _after = _app_with_isolated_stores(tmp_path)
        _seed(call_card_store, roster, with_contact=False)
        async with app.run_test() as pilot:
            await pilot.pause()
            _dispatch(app, "call_card_recap_ready")
            await pilot.pause()
            assert not isinstance(app.screen, PostCallReviewScreen)

    asyncio.run(scenario())


def test_unknown_contact_id_does_not_push_screen(tmp_path):
    async def scenario():
        app, call_card_store, _roster, _after = _app_with_isolated_stores(tmp_path)
        call_card_store.load_or_create("sess-1", "+15551234567", contact_id=999999)
        async with app.run_test() as pilot:
            await pilot.pause()
            _dispatch(app, "call_card_recap_ready")
            await pilot.pause()
            assert not isinstance(app.screen, PostCallReviewScreen)

    asyncio.run(scenario())


# --- "q" priority-binding hazard (documented in check_action's "quit" case) --

def test_q_closes_review_screen_without_quitting_the_app(tmp_path):
    """IrisConsole's own "q" is priority=True and bound to "quit"; without
    check_action's isinstance gate for PostCallReviewScreen, pressing "q"
    here would quit the whole app instead of closing just this screen."""
    async def scenario():
        app, call_card_store, roster, _after = _app_with_isolated_stores(tmp_path)
        _seed(call_card_store, roster)
        async with app.run_test() as pilot:
            await pilot.pause()
            _dispatch(app, "call_card_recap_ready")
            await pilot.pause()
            assert isinstance(app.screen, PostCallReviewScreen)

            await pilot.press("q")
            await pilot.pause()
            assert app.is_running
            assert not isinstance(app.screen, PostCallReviewScreen)

    asyncio.run(scenario())
