"""PostCallReviewScreen -- Call Card AFTER Screen 1 regression guard (ti-qyo3p).

Written as ti-co6cj (validator phase) against the already-shipped
iris/console/post_call_review.py (commit 1481ec3, feat/callcard-after-data-
layer-ti-hb2dx) -- per this rig's convention, builder self-tests but does not
author regression tests.

Uses a minimal host App (_ReviewHostApp), the same convention as
test_contacts_panel.py's _ContactsHostApp, so the Screen can be driven by
Pilot without the full IrisConsole. The host also mounts a #log RichLog on
its base screen: PostCallReviewScreen.on_unmount() focuses "#log"
unconditionally (real IrisConsole always has one), and Textual unmounts the
current screen -- running on_unmount -- both on an explicit pop and on app
teardown at the end of run_test(), so every test here would hit a NoMatches
error without it, not just the explicit dismiss test.

app.py-level wiring (call_card_recap_ready / call_card_ended fallback timer /
the _post_call_review_shown dedup guard / the "q must not quit the whole
app" priority-binding hazard documented in post_call_review.py's own BINDINGS
comment) needs the real IrisConsole and is covered separately in
test_post_call_review_wiring.py.
"""
from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

from textual.app import App, ComposeResult
from textual.content import Content
from textual.widgets import RichLog

from iris.console.call_card import ActionItemCard, CriticalFactCard, FactCard, PriorCommitmentCard
from iris.console.post_call_review import PostCallReviewScreen, SettledRow
from iris.roster import Contact


# --- fixtures ----------------------------------------------------------

class _FakeAfterStore:
    """PostCallReviewScreen never calls AfterStore itself -- it only forwards
    the reference to child PriorCommitmentCard widgets, whose own [H]/[B]
    resolution logic is already covered by test_prior_commitment_card.py.
    Any call here would mean that scope leaked into this screen.
    """

    def resolve_commitment(self, commitment_id: int, status: str) -> None:
        raise AssertionError("PostCallReviewScreen must not call AfterStore directly")


def _contact(**overrides) -> Contact:
    base = dict(
        id=7,
        display_name="Jane Doe",
        phone_e164="+15551234567",
        handling_rule="ring_through",
        trust_tier="full",
        relationship_notes="",
        created_at=0.0,
        updated_at=0.0,
    )
    base.update(overrides)
    return Contact(**base)


def _fact(*, fact_type="case_id", critical=False, confirmed=None, normalized_value="AB123", **overrides) -> dict:
    base = {
        "session_id": "sess-1",
        "fact_type": fact_type,
        "raw_text": normalized_value,
        "normalized_value": normalized_value,
        "critical": critical,
        "confirmed": confirmed,
        "confidence": 0.9,
    }
    base.update(overrides)
    return base


def _action_item(*, description="call back tomorrow", confirmed=None, **overrides) -> dict:
    base = {
        "session_id": "sess-1",
        "description": description,
        "confirmed": confirmed,
        "owner": "far",
    }
    base.update(overrides)
    return base


def _commitment(**overrides) -> dict:
    base = {
        "id": 1,
        "contact_id": 7,
        "call_log_id": 1,
        "direction": "they_promised",
        "description": "send the check",
        "amount": "$50",
        "due_date": "2026-06-01",
        "status": "open",
        "captured_at": 1_774_000_000.0,
        "resolved_at": None,
    }
    base.update(overrides)
    return base


def _call_card(*, facts=None, action_items=None, outcome_summary="") -> dict:
    return {
        "facts": facts or [],
        "action_items": action_items or [],
        "outcome_summary": outcome_summary,
    }


def _plain(content: str) -> str:
    """Parse a Static's stored content the same way Textual's own
    visualize() does (Content.from_markup for markup=True, the Static
    default) and return the rendered plain text -- the most faithful way to
    check that dynamic content survives Rich/Textual markup parsing as
    literal text instead of being swallowed/misinterpreted as style tags.
    """
    return Content.from_markup(content).plain


class _ReviewHostApp(App):
    """Minimal host App so PostCallReviewScreen (a Screen) can be driven by
    Pilot, same convention as test_contacts_panel.py's _ContactsHostApp.

    Pushes PostCallReviewScreen onto a base screen (rather than making it
    get_default_screen()'s return value directly) so q/escape's
    app.pop_screen binding has somewhere to pop back to -- popping a lone
    default screen raises ScreenStackError.
    """

    def __init__(self, contact, call_card, commitments, after_store, *, rep_name=""):
        super().__init__()
        self._contact = contact
        self._call_card = call_card
        self._commitments = commitments
        self._after_store = after_store
        self._rep_name = rep_name

    def compose(self) -> ComposeResult:
        yield RichLog(id="log")

    def on_mount(self) -> None:
        self.push_screen(
            PostCallReviewScreen(
                self._contact,
                self._call_card,
                self._commitments,
                self._after_store,
                rep_name=self._rep_name,
            )
        )


def _host(*, contact=None, call_card=None, commitments=None, rep_name="") -> _ReviewHostApp:
    return _ReviewHostApp(
        contact or _contact(),
        call_card or _call_card(),
        commitments if commitments is not None else [],
        _FakeAfterStore(),
        rep_name=rep_name,
    )


# --- compose()/on_mount() smoke tests (bead's two manually-verified scenarios) --

def test_full_scenario_widget_counts_and_commitment_gets_focus():
    """Mirrors the bead's own manually-verified "full call card" scenario:
    critical fact pending, normal fact already-confirmed, one pending +
    one dismissed action item, one open prior commitment.
    """
    async def scenario():
        card = _call_card(
            facts=[
                _fact(fact_type="case_id", critical=True, confirmed=None, normalized_value="CASE-1"),
                _fact(fact_type="amount", critical=False, confirmed=True, normalized_value="$47.50"),
            ],
            action_items=[
                _action_item(description="send follow-up email", confirmed=None),
                _action_item(description="dismissed one", confirmed=False),
            ],
            outcome_summary="Resolved a billing question.",
        )
        app = _host(call_card=card, commitments=[_commitment()])
        async with app.run_test(size=(120, 50)) as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, PostCallReviewScreen)
            assert len(screen.query(CriticalFactCard)) == 1
            assert len(screen.query(FactCard)) == 0
            assert len(screen.query(ActionItemCard)) == 1
            assert len(screen.query(PriorCommitmentCard)) == 1
            assert len(screen.query(SettledRow)) == 1
            assert isinstance(app.focused, PriorCommitmentCard)

    asyncio.run(scenario())


def test_degraded_scenario_no_facts_no_items_no_commitments_does_not_crash():
    """Mirrors the bead's "degraded/NFR2" scenario: no API key configured,
    so no recap and nothing captured -- must not raise, must not focus
    anything (no candidates).
    """
    async def scenario():
        app = _host(call_card=_call_card(), commitments=[])
        async with app.run_test(size=(120, 50)) as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, PostCallReviewScreen)
            assert len(screen.query(CriticalFactCard)) == 0
            assert len(screen.query(FactCard)) == 0
            assert len(screen.query(ActionItemCard)) == 0
            assert len(screen.query(PriorCommitmentCard)) == 0
            assert len(screen.query(SettledRow)) == 0

    asyncio.run(scenario())


# --- tri-state partition: confirmed=None/True/False -----------------------

def test_critical_fact_confirmed_none_renders_as_live_card():
    async def scenario():
        card = _call_card(facts=[_fact(critical=True, confirmed=None)])
        app = _host(call_card=card)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert len(app.screen.query(CriticalFactCard)) == 1
            assert len(app.screen.query(SettledRow)) == 0

    asyncio.run(scenario())


def test_critical_fact_confirmed_true_renders_as_settled_row_not_card():
    """SettledRow overrides render() directly instead of going through
    Static.update()/.content, so its displayed text must be read via
    render() -- .content stays "" (the unused constructor default)."""
    async def scenario():
        card = _call_card(facts=[_fact(critical=True, confirmed=True, normalized_value="CASE-9")])
        app = _host(call_card=card)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert len(app.screen.query(CriticalFactCard)) == 0
            rows = app.screen.query(SettledRow)
            assert len(rows) == 1
            assert "CASE-9" in _plain(rows.first().render())

    asyncio.run(scenario())


def test_critical_fact_confirmed_false_is_excluded_entirely():
    async def scenario():
        card = _call_card(facts=[_fact(critical=True, confirmed=False)])
        app = _host(call_card=card)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert len(app.screen.query(CriticalFactCard)) == 0
            assert len(app.screen.query(SettledRow)) == 0

    asyncio.run(scenario())


def test_normal_fact_confirmed_none_renders_as_live_card():
    async def scenario():
        card = _call_card(facts=[_fact(critical=False, confirmed=None)])
        app = _host(call_card=card)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert len(app.screen.query(FactCard)) == 1
            assert len(app.screen.query(SettledRow)) == 0

    asyncio.run(scenario())


def test_normal_fact_confirmed_true_renders_as_settled_row_not_card():
    async def scenario():
        card = _call_card(facts=[_fact(critical=False, confirmed=True)])
        app = _host(call_card=card)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert len(app.screen.query(FactCard)) == 0
            assert len(app.screen.query(SettledRow)) == 1

    asyncio.run(scenario())


def test_normal_fact_confirmed_false_is_excluded_entirely():
    async def scenario():
        card = _call_card(facts=[_fact(critical=False, confirmed=False)])
        app = _host(call_card=card)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert len(app.screen.query(FactCard)) == 0
            assert len(app.screen.query(SettledRow)) == 0

    asyncio.run(scenario())


def test_action_item_confirmed_none_renders_as_live_card():
    async def scenario():
        card = _call_card(action_items=[_action_item(confirmed=None)])
        app = _host(call_card=card)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert len(app.screen.query(ActionItemCard)) == 1
            assert len(app.screen.query(SettledRow)) == 0

    asyncio.run(scenario())


def test_action_item_confirmed_true_renders_as_settled_row_not_card():
    async def scenario():
        card = _call_card(action_items=[_action_item(confirmed=True, description="call back")])
        app = _host(call_card=card)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert len(app.screen.query(ActionItemCard)) == 0
            rows = app.screen.query(SettledRow)
            assert len(rows) == 1
            assert "call back" in _plain(rows.first().render())

    asyncio.run(scenario())


def test_action_item_confirmed_false_is_excluded_entirely():
    async def scenario():
        card = _call_card(action_items=[_action_item(confirmed=False)])
        app = _host(call_card=card)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert len(app.screen.query(ActionItemCard)) == 0
            assert len(app.screen.query(SettledRow)) == 0

    asyncio.run(scenario())


# --- focus order ------------------------------------------------------

def test_focus_prefers_commitment_over_critical_fact_and_action_item():
    async def scenario():
        card = _call_card(
            facts=[_fact(critical=True, confirmed=None)],
            action_items=[_action_item(confirmed=None)],
        )
        app = _host(call_card=card, commitments=[_commitment()])
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.focused, PriorCommitmentCard)

    asyncio.run(scenario())


def test_focus_falls_back_to_critical_fact_when_no_commitments():
    async def scenario():
        card = _call_card(
            facts=[_fact(critical=True, confirmed=None)],
            action_items=[_action_item(confirmed=None)],
        )
        app = _host(call_card=card, commitments=[])
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.focused, CriticalFactCard)

    asyncio.run(scenario())


def test_focus_falls_back_to_normal_fact_when_no_commitments_or_critical():
    async def scenario():
        card = _call_card(
            facts=[_fact(critical=False, confirmed=None)],
            action_items=[_action_item(confirmed=None)],
        )
        app = _host(call_card=card, commitments=[])
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.focused, FactCard)

    asyncio.run(scenario())


def test_focus_falls_back_to_action_item_when_only_action_items_present():
    async def scenario():
        card = _call_card(action_items=[_action_item(confirmed=None)])
        app = _host(call_card=card, commitments=[])
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.focused, ActionItemCard)

    asyncio.run(scenario())


def test_focus_lands_on_no_candidate_widget_when_nothing_to_confirm():
    """When on_mount's candidate list is empty, its focus-setting branch is a
    no-op -- Textual's own default auto-focus still lands somewhere (e.g. the
    scrollable body), so this asserts the screen's four candidate widget
    types specifically didn't get focus, not that focus is None."""
    async def scenario():
        app = _host(call_card=_call_card(), commitments=[])
        async with app.run_test() as pilot:
            await pilot.pause()
            assert not isinstance(
                app.focused,
                (PriorCommitmentCard, CriticalFactCard, FactCard, ActionItemCard),
            )

    asyncio.run(scenario())


# --- recap banner -------------------------------------------------------

def test_recap_banner_shows_outcome_summary_when_present():
    async def scenario():
        card = _call_card(outcome_summary="Resolved a billing question.")
        app = _host(call_card=card)
        async with app.run_test() as pilot:
            await pilot.pause()
            banner = app.screen.query_one("#recap-banner")
            plain = _plain(banner.content)
            assert "Resolved a billing question." in plain
            assert "RECAP" in plain

    asyncio.run(scenario())


def test_recap_banner_shows_no_recap_placeholder_when_summary_blank():
    async def scenario():
        app = _host(call_card=_call_card(outcome_summary=""))
        async with app.run_test() as pilot:
            await pilot.pause()
            banner = app.screen.query_one("#recap-banner")
            plain = _plain(banner.content)
            assert "no recap" in plain
            assert "no API key configured" in plain

    asyncio.run(scenario())


def test_recap_banner_treats_whitespace_only_summary_as_blank():
    async def scenario():
        app = _host(call_card=_call_card(outcome_summary="   \n  "))
        async with app.run_test() as pilot:
            await pilot.pause()
            plain = _plain(app.screen.query_one("#recap-banner").content)
            assert "no recap" in plain

    asyncio.run(scenario())


def test_recap_banner_escapes_literal_brackets_in_summary():
    """Regression guard: outcome_summary is model-generated dynamic text. If
    escape() were ever removed from _render_recap_banner, a bracketed
    style-tag-shaped payload like this would be parsed away instead of
    surviving as literal text (matches the adversarial-payload convention
    from test_call_card_markup_escape.py's ti-u4ngs suite).
    """
    async def scenario():
        summary = "Balance shows [bold red]URGENT[/bold red] on file."
        app = _host(call_card=_call_card(outcome_summary=summary))
        async with app.run_test() as pilot:
            await pilot.pause()
            plain = _plain(app.screen.query_one("#recap-banner").content)
            assert summary in plain

    asyncio.run(scenario())


# --- footer -------------------------------------------------------------

def test_footer_includes_hb_hint_when_commitments_present():
    async def scenario():
        app = _host(commitments=[_commitment()])
        async with app.run_test() as pilot:
            await pilot.pause()
            plain = _plain(app.screen.query_one("#review-footer").content)
            assert "[H]/[B] resolve above" in plain

    asyncio.run(scenario())


def test_footer_omits_hb_hint_when_no_commitments():
    async def scenario():
        app = _host(commitments=[])
        async with app.run_test() as pilot:
            await pilot.pause()
            plain = _plain(app.screen.query_one("#review-footer").content)
            assert "resolve above" not in plain
            assert "navigate" in plain
            assert "Skip review" in plain

    asyncio.run(scenario())


def test_footer_bracket_hints_render_without_raising():
    """Regression guard mirroring the historical footer-key-hints-vanish bug
    (commit cb0f2d4): the footer's [H]/[B]/[q] hints are backslash-escaped
    literals in source (not escape()-derived), so this just confirms that
    idiom still renders the brackets as literal text rather than raising or
    silently eating them as style tags.
    """
    async def scenario():
        app = _host(commitments=[_commitment()])
        async with app.run_test() as pilot:
            await pilot.pause()
            plain = _plain(app.screen.query_one("#review-footer").content)
            assert "[q] Skip review (raw record already saved)" in plain
            assert "[↑↓/tab] navigate" in plain

    asyncio.run(scenario())


# --- dismiss behavior -----------------------------------------------------

def test_q_pops_the_screen_even_with_unconfirmed_items():
    async def scenario():
        card = _call_card(facts=[_fact(critical=True, confirmed=None)])
        app = _host(call_card=card)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, PostCallReviewScreen)
            await pilot.press("q")
            await pilot.pause()
            assert not isinstance(app.screen, PostCallReviewScreen)
            assert app.is_running

    asyncio.run(scenario())


def test_escape_pops_the_screen_even_with_unconfirmed_items():
    async def scenario():
        card = _call_card(action_items=[_action_item(confirmed=None)])
        app = _host(call_card=card)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, PostCallReviewScreen)
            assert app.is_running

    asyncio.run(scenario())


# --- sub_title / rep_name threading (cheap, guards __init__ signature) ----

def test_sub_title_includes_rep_name_when_provided():
    async def scenario():
        app = _host(rep_name="Maria")
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.screen.sub_title == "Jane Doe (Maria)"

    asyncio.run(scenario())


def test_sub_title_is_just_contact_name_when_rep_name_blank():
    async def scenario():
        app = _host(rep_name="")
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.screen.sub_title == "Jane Doe"

    asyncio.run(scenario())
