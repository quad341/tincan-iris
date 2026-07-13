"""PostCallReviewScreen — Save/finalize + delta view (Screen 2, ti-viv73).

Scope is deliberately narrow: only what ti-viv73 added on top of the
already-tested Screen 1 (ti-qyo3p, covered elsewhere) -- the [S] save phase
transition (REVIEWING -> SAVING -> SAVED, or back to REVIEWING on failure/
timeout), the delta view's promotion filter (must mirror
CallCardHost.finalize_writeback's own gate exactly -- see ti-hb2dx), and the
screen-side bookkeeping for CommitmentResolved (posted by PriorCommitmentCard;
the posting side is covered in test_prior_commitment_card.py).

IrisConsole's app.py wiring (on_save_requested / _on_daemon_event's
call_card_written_back branch / _maybe_show_post_call_review) lives in
test_post_call_review_app_wiring.py -- a different, heavier harness.

Skipped when textual isn't installed (optional console extra), matching
test_contacts_panel.py / test_console_app.py convention.

_ReviewHostApp mounts a #log RichLog on its own base screen and PUSHES
PostCallReviewScreen on top of it, rather than making the screen
get_default_screen()'s return value directly -- same fix ti-co6cj's sibling
test_post_call_review.py already had to apply for this exact widget:
PostCallReviewScreen.on_unmount() unconditionally does
self.app.query_one("#log", RichLog).focus() (real IrisConsole always has
one), and Textual runs on_unmount both on an explicit pop AND on app
teardown at the end of every run_test() block -- so every test here would
hit a NoMatches error without it, not just ones that explicitly dismiss.
"""
from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

from textual.app import App, ComposeResult  # noqa: E402
from textual.widgets import RichLog, Static  # noqa: E402

from iris.capture.schemas import FactType  # noqa: E402
from iris.console.call_card import CommitmentResolved  # noqa: E402
from iris.console.post_call_review import (  # noqa: E402
    DeltaRow,
    PostCallReviewScreen,
    SaveRequested,
    _ReviewPhase,
)
from iris.roster import Contact  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

class _FakeTimer:
    """Stand-in for the real Timer object set_timer() normally returns."""

    def stop(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _no_real_save_timer(monkeypatch):
    """action_save() schedules a real 7s Timer via self.set_timer(...). Any
    test that doesn't chase it with on_saved()/on_save_failed() (both of
    which call _stop_save_timeout()) leaves it pending when run_test()'s
    Pilot session exits -- and Textual's shutdown sequence then hangs
    waiting on it (a real, reproducible deadlock, not just a slow test).
    Rather than track which tests happen to clean up after themselves,
    replace set_timer everywhere: same root cause and same fix ti-co6cj's
    test_post_call_review_wiring.py already applies (there via
    app.set_timer) for app.py's 2.5s call_card_ended fallback timer. Tests
    that simulate the timeout firing call screen._on_save_timeout()
    directly instead of waiting out real time either way.
    """
    monkeypatch.setattr(PostCallReviewScreen, "set_timer", lambda self, *a, **k: _FakeTimer())


class _FakeAfterStore:
    """Threaded through to PriorCommitmentCard only -- the screen itself never
    calls AfterStore methods directly. [H]/[B] -> resolve_commitment coverage
    already lives in test_prior_commitment_card.py.
    """

    def resolve_commitment(self, commitment_id, status):
        pass


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


def _fact(**overrides) -> dict:
    base = dict(
        id="f1",
        session_id="sess-1",
        fact_type=FactType.ACCOUNT_ID.value,
        raw_text="account number nine one two",
        normalized_value="912",
        transcript_turn_id=1,
        transcript_offset_s=1.0,
        speaker="far",
        confidence=0.9,
        critical=True,
        confirmed=True,
        source_layer=1,
        created_at=0.0,
    )
    base.update(overrides)
    return base


def _item(**overrides) -> dict:
    base = dict(
        id="i1",
        session_id="sess-1",
        description="send the check",
        trigger="",
        owner="far",
        transcript_turn_id=1,
        transcript_offset_s=1.0,
        speaker="far",
        confidence=0.9,
        due_date="2026-07-01",
        confirmed=True,
        source_layer=1,
        created_at=0.0,
    )
    base.update(overrides)
    return base


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


def _commitment(**overrides) -> dict:
    base = dict(
        id=1,
        contact_id=7,
        call_log_id=1,
        direction="they_promised",
        description="send the check",
        due_date="2026-06-01",
        captured_at=1_774_000_000.0,
    )
    base.update(overrides)
    return base


class _ReviewHostApp(App):
    """Minimal host App so PostCallReviewScreen (a Screen) can be driven by
    Pilot -- run_test() lives on App, not Screen (same convention as
    test_contacts_panel.py's _ContactsHostApp).

    Mounts a #log RichLog on its own base screen and PUSHES
    PostCallReviewScreen on top of it, rather than returning the screen
    directly from get_default_screen() -- see module docstring.
    """

    def __init__(self, screen: PostCallReviewScreen) -> None:
        super().__init__()
        self._screen = screen

    def compose(self) -> ComposeResult:
        yield RichLog(id="log")

    def on_mount(self) -> None:
        self.push_screen(self._screen)


def _make_screen(
    *,
    contact=None,
    call_card=None,
    commitments=None,
    after_store=None,
    session_id="sess-1",
    rep_name="",
) -> PostCallReviewScreen:
    return PostCallReviewScreen(
        contact if contact is not None else _contact(),
        call_card if call_card is not None else _call_card(),
        commitments if commitments is not None else [],
        after_store if after_store is not None else _FakeAfterStore(),
        session_id,
        rep_name=rep_name,
    )


def _footer_text(screen: PostCallReviewScreen) -> str:
    return str(screen.query_one("#review-footer", Static).content)


def _banner_text(screen: PostCallReviewScreen) -> str:
    return str(screen.query_one("#recap-banner", Static).content)


def _record_posted_messages(screen: PostCallReviewScreen, monkeypatch) -> list:
    """Wrap post_message to record what's posted while still delivering it for
    real. Pilot.pause()'s own _wait_for_screen() idle-detection posts a
    bookkeeping Callback through this same screen.post_message -- a
    swallow-only replacement (record without forwarding to the real
    post_message) silently eats that Callback too, so _wait_for_screen()
    never sees its counter reach zero and run_test()'s teardown deadlocks.
    Only matters for tests here that drive a live Pilot/run_test() harness;
    the Pilot-less widget tests in test_prior_commitment_card.py /
    test_disclosure_card.py swallow post_message outright with no such risk.
    """
    posted = []
    real_post_message = screen.post_message

    def record(msg):
        posted.append(msg)
        return real_post_message(msg)

    monkeypatch.setattr(screen, "post_message", record)
    return posted


# ---------------------------------------------------------------------------
# check_action gate (no mount needed -- reads only self._phase)
# ---------------------------------------------------------------------------

def test_check_action_save_true_only_while_reviewing():
    screen = _make_screen()
    assert screen.check_action("save", ()) is True
    screen._phase = _ReviewPhase.SAVING
    assert screen.check_action("save", ()) is False
    screen._phase = _ReviewPhase.SAVED
    assert screen.check_action("save", ()) is False


def test_check_action_other_actions_always_true_regardless_of_phase():
    screen = _make_screen()
    assert screen.check_action("app.pop_screen", ()) is True
    screen._phase = _ReviewPhase.SAVING
    assert screen.check_action("app.pop_screen", ()) is True
    screen._phase = _ReviewPhase.SAVED
    assert screen.check_action("app.pop_screen", ()) is True


# ---------------------------------------------------------------------------
# on_commitment_resolved bookkeeping (no mount needed -- pure list append)
# ---------------------------------------------------------------------------

def test_on_commitment_resolved_records_matching_commitment():
    commitments = [_commitment(id=5, description="match me"), _commitment(id=6, description="other")]
    screen = _make_screen(commitments=commitments)
    screen.on_commitment_resolved(CommitmentResolved(5, "honored"))
    assert screen._resolved_commitments == [(commitments[0], "honored")]


def test_on_commitment_resolved_ignores_unknown_id():
    commitments = [_commitment(id=5)]
    screen = _make_screen(commitments=commitments)
    screen.on_commitment_resolved(CommitmentResolved(999, "honored"))
    assert screen._resolved_commitments == []


# ---------------------------------------------------------------------------
# action_save: phase transition, unconfirmed count, SaveRequested posting
# ---------------------------------------------------------------------------

def test_action_save_transitions_to_saving_and_posts_save_requested(monkeypatch):
    screen = _make_screen(session_id="sess-42")
    posted = _record_posted_messages(screen, monkeypatch)

    async def scenario():
        app = _ReviewHostApp(screen)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            screen.action_save()
            await pilot.pause()

    asyncio.run(scenario())
    assert screen._phase is _ReviewPhase.SAVING
    save_requested = [m for m in posted if isinstance(m, SaveRequested)]
    assert len(save_requested) == 1
    assert save_requested[0].session_id == "sess-42"


def test_action_save_noop_when_not_reviewing(monkeypatch):
    screen = _make_screen()
    posted = _record_posted_messages(screen, monkeypatch)

    async def scenario():
        app = _ReviewHostApp(screen)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            screen._phase = _ReviewPhase.SAVING
            screen.action_save()
            await pilot.pause()

    asyncio.run(scenario())
    assert not any(isinstance(m, SaveRequested) for m in posted)


def test_action_save_counts_only_unconfirmed_cards():
    facts = [
        _fact(id="crit-unconfirmed", fact_type=FactType.ACCOUNT_ID.value, critical=True, confirmed=None),
        _fact(id="normal-confirmed", fact_type=FactType.EMAIL.value, critical=False, confirmed=True),
    ]
    items = [_item(id="item-unconfirmed", confirmed=None)]
    screen = _make_screen(call_card=_call_card(facts=facts, action_items=items))

    async def scenario():
        app = _ReviewHostApp(screen)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            screen.action_save()
            await pilot.pause()

    asyncio.run(scenario())
    # Only the unconfirmed critical fact + unconfirmed action item count --
    # the confirmed normal fact rendered as a quiet SettledRow, not a card.
    assert screen._unconfirmed_count == 2


def test_save_timeout_fires_on_save_failed():
    screen = _make_screen()

    async def scenario():
        app = _ReviewHostApp(screen)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            screen.action_save()
            await pilot.pause()
            screen._on_save_timeout()  # simulate the 7s timer firing, no real wait
            await pilot.pause()

    asyncio.run(scenario())
    assert screen._phase is _ReviewPhase.REVIEWING
    assert screen._save_failed is True
    assert screen._save_timeout_timer is None


def test_retry_after_failure_reposts_save_requested(monkeypatch):
    screen = _make_screen(session_id="sess-9")
    posted = None

    async def scenario():
        nonlocal posted
        app = _ReviewHostApp(screen)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            screen.action_save()
            await pilot.pause()
            screen.on_save_failed()
            await pilot.pause()
            posted = _record_posted_messages(screen, monkeypatch)
            screen.action_save()
            await pilot.pause()

    asyncio.run(scenario())
    assert screen._phase is _ReviewPhase.SAVING
    save_requested = [m for m in posted if isinstance(m, SaveRequested)]
    assert len(save_requested) == 1


# ---------------------------------------------------------------------------
# on_save_failed
# ---------------------------------------------------------------------------

def test_on_save_failed_returns_to_reviewing_and_flags_footer():
    screen = _make_screen()
    footer = None

    async def scenario():
        nonlocal footer
        app = _ReviewHostApp(screen)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            screen.action_save()
            await pilot.pause()
            screen.on_save_failed()
            await pilot.pause()
            footer = _footer_text(screen)

    asyncio.run(scenario())
    assert screen._phase is _ReviewPhase.REVIEWING
    assert screen._save_failed is True
    assert "did not save" in footer


def test_on_save_failed_noop_when_not_saving():
    screen = _make_screen()

    async def scenario():
        app = _ReviewHostApp(screen)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            # Still REVIEWING -- never called action_save().
            screen.on_save_failed()
            await pilot.pause()

    asyncio.run(scenario())
    assert screen._phase is _ReviewPhase.REVIEWING
    assert screen._save_failed is False


def test_on_save_failed_stops_pending_timeout_timer():
    screen = _make_screen()

    async def scenario():
        app = _ReviewHostApp(screen)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            screen.action_save()
            await pilot.pause()
            assert screen._save_timeout_timer is not None
            screen.on_save_failed()

    asyncio.run(scenario())
    assert screen._save_timeout_timer is None


# ---------------------------------------------------------------------------
# on_saved
# ---------------------------------------------------------------------------

def test_on_saved_transitions_to_saved_and_replaces_call_card():
    screen = _make_screen(call_card=_call_card(outcome_summary="stale"))
    fresh = _call_card(outcome_summary="fresh")

    async def scenario():
        app = _ReviewHostApp(screen)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            screen.action_save()
            await pilot.pause()
            screen.on_saved(fresh)
            await pilot.pause()

    asyncio.run(scenario())
    assert screen._phase is _ReviewPhase.SAVED
    assert screen._call_card["outcome_summary"] == "fresh"
    assert screen._save_timeout_timer is None


def test_on_saved_noop_when_not_saving():
    screen = _make_screen(call_card=_call_card(outcome_summary="original"))

    async def scenario():
        app = _ReviewHostApp(screen)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            # Never called action_save() -- still REVIEWING.
            screen.on_saved(_call_card(outcome_summary="should not apply"))
            await pilot.pause()

    asyncio.run(scenario())
    assert screen._phase is _ReviewPhase.REVIEWING
    assert screen._call_card["outcome_summary"] == "original"


def test_saved_adds_saved_css_class_to_screen_and_banner():
    screen = _make_screen()
    banner_has_saved_class = None

    async def scenario():
        nonlocal banner_has_saved_class
        app = _ReviewHostApp(screen)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            screen.action_save()
            await pilot.pause()
            screen.on_saved(_call_card())
            await pilot.pause()
            banner_has_saved_class = screen.query_one("#recap-banner", Static).has_class("-saved")

    asyncio.run(scenario())
    assert screen.has_class("-saved")
    assert banner_has_saved_class


def test_focus_after_saved_focuses_recap_banner():
    screen = _make_screen()
    can_focus = None
    is_focused = None

    async def scenario():
        nonlocal can_focus, is_focused
        app = _ReviewHostApp(screen)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            screen.action_save()
            await pilot.pause()
            screen.on_saved(_call_card())
            await pilot.pause()
            banner = screen.query_one("#recap-banner", Static)
            can_focus = banner.can_focus
            is_focused = app.focused is banner

    asyncio.run(scenario())
    assert can_focus is True
    assert is_focused is True


# ---------------------------------------------------------------------------
# Delta view: promotion filter must mirror CallCardHost.finalize_writeback
# exactly (ti-hb2dx) -- facts need confirmed AND a durable fact_type; action
# items promote on confirmed alone, regardless of owner/direction.
# ---------------------------------------------------------------------------

def _saved_delta_rows(screen: PostCallReviewScreen) -> list[DeltaRow]:
    return list(screen.query(DeltaRow))


def test_delta_view_promotes_only_confirmed_durable_facts():
    facts = [
        _fact(id="a", fact_type=FactType.ACCOUNT_ID.value, critical=True, confirmed=True, normalized_value="912"),
        _fact(id="b", fact_type=FactType.EMAIL.value, critical=False, confirmed=True, normalized_value="a@b.com"),
        _fact(id="c", fact_type=FactType.PHONE.value, critical=False, confirmed=True, normalized_value="+15551234"),
        _fact(id="d", fact_type=FactType.MEMBER_ID.value, critical=False, confirmed=None, normalized_value="M1"),
        _fact(id="e", fact_type=FactType.POLICY_ID.value, critical=False, confirmed=False, normalized_value="P1"),
    ]
    card = _call_card(facts=facts)
    screen = _make_screen(call_card=card)
    texts = None

    async def scenario():
        nonlocal texts
        app = _ReviewHostApp(screen)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            screen.action_save()
            await pilot.pause()
            screen.on_saved(card)
            await pilot.pause()
            texts = [str(r.render()) for r in _saved_delta_rows(screen)]

    asyncio.run(scenario())
    assert any("912" in t for t in texts)
    assert any("a@b.com" in t for t in texts)
    assert not any("+15551234" in t for t in texts)  # PHONE not durable
    assert not any("M1" in t for t in texts)  # unconfirmed
    assert not any("P1" in t for t in texts)  # dismissed


def test_delta_view_orders_critical_facts_before_normal_facts():
    facts = [
        _fact(id="n1", fact_type=FactType.EMAIL.value, critical=False, confirmed=True, normalized_value="normal-1"),
        _fact(id="c1", fact_type=FactType.ACCOUNT_ID.value, critical=True, confirmed=True, normalized_value="critical-1"),
        _fact(id="n2", fact_type=FactType.MEMBER_ID.value, critical=False, confirmed=True, normalized_value="normal-2"),
    ]
    card = _call_card(facts=facts)
    screen = _make_screen(call_card=card)
    row_texts = None

    async def scenario():
        nonlocal row_texts
        app = _ReviewHostApp(screen)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            screen.action_save()
            await pilot.pause()
            screen.on_saved(card)
            await pilot.pause()
            row_texts = [str(row.render()) for row in _saved_delta_rows(screen)]

    asyncio.run(scenario())
    order = []
    for text in row_texts:
        for marker in ("critical-1", "normal-1", "normal-2"):
            if marker in text:
                order.append(marker)
    assert order == ["critical-1", "normal-1", "normal-2"]


def test_delta_view_action_item_direction_label_only_far_is_they_promised():
    items = [
        _item(id="i-far", owner="far", confirmed=True, description="they will call back"),
        _item(id="i-near", owner="near", confirmed=True, description="I will call back"),
        _item(id="i-blank", owner="", confirmed=True, description="unspecified owner"),
    ]
    card = _call_card(action_items=items)
    screen = _make_screen(call_card=card)
    texts = None

    async def scenario():
        nonlocal texts
        app = _ReviewHostApp(screen)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            screen.action_save()
            await pilot.pause()
            screen.on_saved(card)
            await pilot.pause()
            texts = [str(r.render()) for r in _saved_delta_rows(screen) if r.has_class("-commitment")]

    asyncio.run(scenario())
    far_text = next(t for t in texts if "they will call back" in t)
    assert "they_promised" in far_text
    near_text = next(t for t in texts if "I will call back" in t)
    assert "i_promised" in near_text
    blank_text = next(t for t in texts if "unspecified owner" in t)
    assert "i_promised" in blank_text


def test_delta_view_excludes_unconfirmed_and_dismissed_action_items():
    items = [
        _item(id="i1", confirmed=True, description="keep-me"),
        _item(id="i2", confirmed=None, description="drop-me-unconfirmed"),
        _item(id="i3", confirmed=False, description="drop-me-dismissed"),
    ]
    card = _call_card(action_items=items)
    screen = _make_screen(call_card=card)
    texts = None

    async def scenario():
        nonlocal texts
        app = _ReviewHostApp(screen)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            screen.action_save()
            await pilot.pause()
            screen.on_saved(card)
            await pilot.pause()
            texts = [str(r.render()) for r in _saved_delta_rows(screen) if r.has_class("-commitment")]

    asyncio.run(scenario())
    assert any("keep-me" in t for t in texts)
    assert not any("drop-me-unconfirmed" in t for t in texts)
    assert not any("drop-me-dismissed" in t for t in texts)


def test_call_log_row_has_duration_and_no_disclosed_when_absent():
    card = _call_card(started_at=1_000.0, ended_at=1_125.0, disclosure_ack_ts=None)
    screen = _make_screen(call_card=card)
    call_log_text = None

    async def scenario():
        nonlocal call_log_text
        app = _ReviewHostApp(screen)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            screen.action_save()
            await pilot.pause()
            screen.on_saved(card)
            await pilot.pause()
            call_log_text = next(str(r.render()) for r in _saved_delta_rows(screen) if r.has_class("-call-log"))

    asyncio.run(scenario())
    assert "2m05s" in call_log_text
    assert "disclosed" not in call_log_text


def test_call_log_row_includes_disclosed_clock_when_present():
    card = _call_card(started_at=1_000.0, ended_at=1_125.0, disclosure_ack_ts=1_050.0)
    screen = _make_screen(call_card=card)
    call_log_text = None

    async def scenario():
        nonlocal call_log_text
        app = _ReviewHostApp(screen)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            screen.action_save()
            await pilot.pause()
            screen.on_saved(card)
            await pilot.pause()
            call_log_text = next(str(r.render()) for r in _saved_delta_rows(screen) if r.has_class("-call-log"))

    asyncio.run(scenario())
    assert "disclosed" in call_log_text


# ---------------------------------------------------------------------------
# Success banner pluralization
# ---------------------------------------------------------------------------

def test_success_banner_singular_counts():
    card = _call_card(
        facts=[_fact(fact_type=FactType.ACCOUNT_ID.value, confirmed=True)],
        action_items=[_item(confirmed=True)],
    )
    screen = _make_screen(call_card=card)
    banner = None

    async def scenario():
        nonlocal banner
        app = _ReviewHostApp(screen)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            screen.action_save()
            await pilot.pause()
            screen.on_saved(card)
            await pilot.pause()
            banner = _banner_text(screen)

    asyncio.run(scenario())
    assert "1 fact ·" in banner
    assert "1 action item ·" in banner


def test_success_banner_plural_and_zero_counts():
    card = _call_card(
        facts=[
            _fact(id="a", fact_type=FactType.ACCOUNT_ID.value, confirmed=True),
            _fact(id="b", fact_type=FactType.EMAIL.value, confirmed=True),
        ],
        action_items=[],
    )
    screen = _make_screen(call_card=card)
    banner = None

    async def scenario():
        nonlocal banner
        app = _ReviewHostApp(screen)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            screen.action_save()
            await pilot.pause()
            screen.on_saved(card)
            await pilot.pause()
            banner = _banner_text(screen)

    asyncio.run(scenario())
    assert "2 facts ·" in banner
    assert "0 action items ·" in banner


# ---------------------------------------------------------------------------
# Resolved-commitment lines + broken preview / next-call seam contract.
#
# Two behaviors are deliberately locked in here as regression guards rather
# than "fixed", per the bead's own framing -- they're existing, intentional-
# looking asymmetries in this module, not something a test bead should alter:
#
#   1. _broken_preview_text() returns on the FIRST broken commitment in
#      self._resolved_commitments and ignores any later ones.
#   2. _seam_contract_text()'s `who = self._rep_name or "your rep"` never
#      branches on commitment direction, unlike PriorCommitmentCard._who()
#      (see test_prior_commitment_card.py) which says "you"/"You" for
#      direction == "i_promised". A broken commitment the OPERATOR made
#      (not the rep) still previews as "<rep> promised ... it didn't
#      happen" here -- worth a human look, flagged in the ti-8rlc7 handoff,
#      not silently patched by this test suite.
# ---------------------------------------------------------------------------

def test_resolved_line_shows_honored_and_broken_text():
    commitments = [_commitment(id=1, description="thing one"), _commitment(id=2, description="thing two")]
    card = _call_card()
    screen = _make_screen(call_card=card, commitments=commitments)
    resolved_texts = None

    async def scenario():
        nonlocal resolved_texts
        app = _ReviewHostApp(screen)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            screen.action_save()
            await pilot.pause()
            screen.on_commitment_resolved(CommitmentResolved(1, "honored"))
            screen.on_commitment_resolved(CommitmentResolved(2, "broken"))
            screen.on_saved(card)
            await pilot.pause()
            resolved_texts = [str(w.content) for w in screen.query(".resolved-line")]

    asyncio.run(scenario())
    assert any("thing one" in t and "HONORED" in t for t in resolved_texts)
    assert any("thing two" in t and "BROKEN" in t for t in resolved_texts)


def test_broken_preview_shows_only_first_broken_commitment():
    commitments = [_commitment(id=1, description="first broken thing"), _commitment(id=2, description="second broken thing")]
    card = _call_card()
    screen = _make_screen(call_card=card, commitments=commitments)
    footer = None

    async def scenario():
        nonlocal footer
        app = _ReviewHostApp(screen)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            screen.action_save()
            await pilot.pause()
            screen.on_commitment_resolved(CommitmentResolved(1, "broken"))
            screen.on_commitment_resolved(CommitmentResolved(2, "broken"))
            screen.on_saved(card)
            await pilot.pause()
            footer = _footer_text(screen)

    asyncio.run(scenario())
    assert "first broken thing" in footer
    assert "second broken thing" not in footer


def test_no_broken_preview_when_all_resolutions_are_honored():
    commitments = [_commitment(id=1, description="thing one")]
    card = _call_card()
    screen = _make_screen(call_card=card, commitments=commitments)
    footer = None

    async def scenario():
        nonlocal footer
        app = _ReviewHostApp(screen)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            screen.action_save()
            await pilot.pause()
            screen.on_commitment_resolved(CommitmentResolved(1, "honored"))
            screen.on_saved(card)
            await pilot.pause()
            footer = _footer_text(screen)

    asyncio.run(scenario())
    assert "Next call to" not in footer


def test_broken_preview_uses_rep_name_regardless_of_commitment_direction():
    """Regression guard for a real-looking asymmetry -- see module docstring
    above. direction="i_promised" here means the OPERATOR broke their own
    promise, yet the preview still reads "<rep_name> promised ...".
    """
    commitment = _commitment(id=1, description="call back Tuesday", due_date="2026-06-01", direction="i_promised")
    card = _call_card()
    screen = _make_screen(call_card=card, commitments=[commitment], rep_name="Maria")
    footer = None

    async def scenario():
        nonlocal footer
        app = _ReviewHostApp(screen)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            screen.action_save()
            await pilot.pause()
            screen.on_commitment_resolved(CommitmentResolved(1, "broken"))
            screen.on_saved(card)
            await pilot.pause()
            footer = _footer_text(screen)

    asyncio.run(scenario())
    assert "Maria promised call back Tuesday by 2026-06-01" in footer


def test_broken_preview_defaults_to_your_rep_when_rep_name_blank():
    commitment = _commitment(id=1, description="call back Tuesday", due_date="2026-06-01")
    card = _call_card()
    screen = _make_screen(call_card=card, commitments=[commitment], rep_name="")
    footer = None

    async def scenario():
        nonlocal footer
        app = _ReviewHostApp(screen)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            screen.action_save()
            await pilot.pause()
            screen.on_commitment_resolved(CommitmentResolved(1, "broken"))
            screen.on_saved(card)
            await pilot.pause()
            footer = _footer_text(screen)

    asyncio.run(scenario())
    assert "your rep promised call back Tuesday by 2026-06-01" in footer
