"""Tests for iris/console/call_card.py — DisclosureCard, fact cards, ActionItemCard, CallCardView.

Bead: ti-rnlqo.6.6 (validator phase)

Coverage map:
  DisclosureCard:
    - Expanded → collapsed on [D] (badge '✓ AI Disclosed')
    - Expanded → collapsed on [S] (badge '⊘ Skipped')
    - Re-init with existing state file shows badge, not expanded
    - Focus trap: Tab cycles D↔S only (no focus leaks to CardFeed)
    - Esc triggers Skip (same as [S])

  CriticalFactCard:
    - Renders amber border, '⚡ CRITICAL FACT' header, confidence bar, raw_text + normalized_value
    - Confidence bar CSS classes: ≥85% → confidence-high, 60-84% → confidence-medium, <60% → confidence-low
    - prefers-reduced-motion: no-animation/reduced-motion CSS class applied
    - [E] opens edit mode, Enter confirms with edited value, Esc cancels
    - [E] button disabled while in edit mode
    - [D] marks confirmed, [X] removes card

  FactCard:
    - Renders teal border, '● FACT' header, confidence bar, raw_text + normalized_value
    - No [E] Edit action present
    - [D] Confirm, [X] Dismiss work correctly

  ActionItemCard:
    - Renders description + owner + due_date (or 'Due: —' when absent)
    - Empty owner field displays 'Them'
    - [E] opens edit for all three fields; Enter saves; Esc cancels

  CallCardView:
    - call_card_started sets caller_phone + topic on the view, shows expanded DisclosureCard
    - call_card_fact with critical=True → prepends CriticalFactCard
    - call_card_fact with critical=False → prepends FactCard
    - call_card_action_item → prepends ActionItemCard
    - call_card_ended shows '⏳ Enriching...' indicator
    - call_card_enriched hides '⏳ Enriching...' indicator
    - Newest card is always at top of feed (prepend order)

All tests are intentionally RED until ti-rnlqo.6.1–6.5 are merged.
No daemon, no audio, no network.
"""
from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("textual")

from textual.app import App, ComposeResult  # noqa: E402
from textual.binding import Binding  # noqa: E402

from iris.capture.schemas import ActionItem, CapturedFact, FactType  # noqa: E402
from iris.console.call_card import (  # noqa: E402
    ActionItemCard,
    CallCardView,
    CriticalFactCard,
    DisclosureCard,
    FactCard,
)


# ---------------------------------------------------------------------------
# Minimal host app
# ---------------------------------------------------------------------------

class _CallCardHostApp(App):
    """Minimal App so CallCardView widgets can be driven by a Pilot."""

    BINDINGS = [Binding("q", "quit", "Quit")]

    def compose(self) -> ComposeResult:
        yield CallCardView()


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _make_fact(
    *,
    fact_type: FactType = FactType.CASE_ID,
    raw_text: str = "reference number is REF-88211",
    normalized_value: str = "REF-88211",
    confidence: float = 0.95,
    critical: bool = True,
    speaker: str = "far",
    session_id: str = "sess-001",
) -> CapturedFact:
    return CapturedFact(
        session_id=session_id,
        fact_type=fact_type,
        raw_text=raw_text,
        normalized_value=normalized_value,
        transcript_turn_id=1,
        transcript_offset_s=10.0,
        speaker=speaker,
        confidence=confidence,
        critical=critical,
    )


def _make_action_item(
    *,
    description: str = "Call you back by Friday",
    owner: str = "operator",
    due_date: str | None = "2026-07-03",
    session_id: str = "sess-001",
) -> ActionItem:
    return ActionItem(
        session_id=session_id,
        description=description,
        trigger="I'll call you back",
        owner=owner,
        transcript_turn_id=2,
        transcript_offset_s=20.0,
        speaker="operator",
        confidence=0.85,
        due_date=due_date,
    )


# ---------------------------------------------------------------------------
# DisclosureCard
# ---------------------------------------------------------------------------

class TestDisclosureCard:
    def test_disclosed_collapses_and_shows_ack_badge(self):
        async def scenario():
            app = _CallCardHostApp()
            async with app.run_test(size=(120, 40)) as pilot:
                app.post_message(
                    CallCardView.CallCardStarted(
                        caller_phone="+15551234567",
                        topic="billing",
                        session_id="sess-d",
                    )
                )
                await pilot.pause()
                card = app.query_one(DisclosureCard)
                assert card.is_expanded, "DisclosureCard must start expanded"
                card.action_disclosed()
                await pilot.pause()
                assert not card.is_expanded
                assert "✓" in card.ack_label
                assert "Disclosed" in card.ack_label
                await pilot.press("q")

        asyncio.run(scenario())

    def test_skip_collapses_and_shows_skip_badge(self):
        async def scenario():
            app = _CallCardHostApp()
            async with app.run_test(size=(120, 40)) as pilot:
                app.post_message(
                    CallCardView.CallCardStarted(
                        caller_phone="+15551234567",
                        topic="billing",
                        session_id="sess-s",
                    )
                )
                await pilot.pause()
                card = app.query_one(DisclosureCard)
                card.action_skip()
                await pilot.pause()
                assert not card.is_expanded
                assert "Skipped" in card.ack_label or "⊘" in card.ack_label
                await pilot.press("q")

        asyncio.run(scenario())

    def test_reinit_with_existing_state_shows_badge_not_expanded(
        self, tmp_path, monkeypatch
    ):
        import iris.console.call_card as cc

        state_file = tmp_path / "disclosure-sess-restore.json"
        state_file.write_text(json.dumps({"ack": "disclosed", "timestamp": 1751000000}))
        monkeypatch.setattr(
            cc,
            "_get_disclosure_state_path",
            lambda session_id: tmp_path / f"disclosure-{session_id}.json",
        )

        async def scenario():
            app = _CallCardHostApp()
            async with app.run_test(size=(120, 40)) as pilot:
                app.post_message(
                    CallCardView.CallCardStarted(
                        caller_phone="+15551234567",
                        topic="billing",
                        session_id="sess-restore",
                    )
                )
                await pilot.pause()
                card = app.query_one(DisclosureCard)
                assert not card.is_expanded, (
                    "Re-attached session with acknowledged disclosure must show badge, not expansion"
                )
                await pilot.press("q")

        asyncio.run(scenario())

    def test_focus_trap_tab_stays_within_disclosure_card(self):
        async def scenario():
            app = _CallCardHostApp()
            async with app.run_test(size=(120, 40)) as pilot:
                app.post_message(
                    CallCardView.CallCardStarted(
                        caller_phone="+15551234567",
                        topic="billing",
                        session_id="sess-ft",
                    )
                )
                await pilot.pause()
                card = app.query_one(DisclosureCard)
                assert card.is_expanded
                await pilot.press("tab")
                await pilot.press("tab")
                focused = app.focused
                assert focused is not None
                card_children = list(card.query("*"))
                assert focused in card_children or focused is card, (
                    "Focus must stay within DisclosureCard after two Tab presses"
                )
                await pilot.press("q")

        asyncio.run(scenario())

    def test_esc_triggers_skip(self):
        async def scenario():
            app = _CallCardHostApp()
            async with app.run_test(size=(120, 40)) as pilot:
                app.post_message(
                    CallCardView.CallCardStarted(
                        caller_phone="+15551234567",
                        topic="billing",
                        session_id="sess-esc",
                    )
                )
                await pilot.pause()
                card = app.query_one(DisclosureCard)
                assert card.is_expanded
                await pilot.press("escape")
                await pilot.pause()
                assert not card.is_expanded, "Esc must collapse DisclosureCard (same as Skip)"
                assert "Skipped" in card.ack_label or "⊘" in card.ack_label
                await pilot.press("q")

        asyncio.run(scenario())


# ---------------------------------------------------------------------------
# CriticalFactCard
# ---------------------------------------------------------------------------

class TestCriticalFactCard:
    def test_renders_critical_header_and_both_values(self):
        async def scenario():
            fact = _make_fact(
                critical=True,
                raw_text="reference number REF-88211",
                normalized_value="REF-88211",
            )
            app = _CallCardHostApp()
            async with app.run_test(size=(120, 40)) as pilot:
                app.post_message(CallCardView.CallCardFact(fact=fact))
                await pilot.pause()
                card = app.query_one(CriticalFactCard)
                rendered = str(card.render())
                assert "⚡ CRITICAL FACT" in rendered or card.has_class("critical-fact-card"), (
                    "CriticalFactCard must show '⚡ CRITICAL FACT' header"
                )
                assert "REF-88211" in rendered
                assert "reference number REF-88211" in rendered
                await pilot.press("q")

        asyncio.run(scenario())

    def test_confidence_bar_high_class_at_or_above_85_percent(self):
        async def scenario():
            fact = _make_fact(critical=True, confidence=0.92)
            app = _CallCardHostApp()
            async with app.run_test(size=(120, 40)) as pilot:
                app.post_message(CallCardView.CallCardFact(fact=fact))
                await pilot.pause()
                card = app.query_one(CriticalFactCard)
                bar = card.query_one(".confidence-bar")
                assert bar.has_class("confidence-high"), (
                    "Confidence ≥85% must use confidence-high CSS class"
                )
                await pilot.press("q")

        asyncio.run(scenario())

    def test_confidence_bar_medium_class_at_60_to_84_percent(self):
        async def scenario():
            fact = _make_fact(critical=True, confidence=0.72)
            app = _CallCardHostApp()
            async with app.run_test(size=(120, 40)) as pilot:
                app.post_message(CallCardView.CallCardFact(fact=fact))
                await pilot.pause()
                card = app.query_one(CriticalFactCard)
                bar = card.query_one(".confidence-bar")
                assert bar.has_class("confidence-medium"), (
                    "Confidence 60-84% must use confidence-medium CSS class"
                )
                await pilot.press("q")

        asyncio.run(scenario())

    def test_confidence_bar_low_class_below_60_percent(self):
        async def scenario():
            fact = _make_fact(critical=True, confidence=0.45)
            app = _CallCardHostApp()
            async with app.run_test(size=(120, 40)) as pilot:
                app.post_message(CallCardView.CallCardFact(fact=fact))
                await pilot.pause()
                card = app.query_one(CriticalFactCard)
                bar = card.query_one(".confidence-bar")
                assert bar.has_class("confidence-low"), (
                    "Confidence <60% must use confidence-low CSS class"
                )
                await pilot.press("q")

        asyncio.run(scenario())

    def test_reduced_motion_applies_no_animation_class(self):
        async def scenario():
            fact = _make_fact(critical=True)
            app = _CallCardHostApp()
            async with app.run_test(size=(120, 40)) as pilot:
                app.post_message(CallCardView.CallCardFact(fact=fact))
                await pilot.pause()
                card = app.query_one(CriticalFactCard)
                card.reduced_motion = True
                await pilot.pause()
                assert card.has_class("reduced-motion") or card.has_class("no-animation"), (
                    "reduced_motion=True must add 'reduced-motion' or 'no-animation' CSS class"
                )
                await pilot.press("q")

        asyncio.run(scenario())

    def test_edit_mode_opens_on_action_edit(self):
        async def scenario():
            fact = _make_fact(critical=True)
            app = _CallCardHostApp()
            async with app.run_test(size=(120, 40)) as pilot:
                app.post_message(CallCardView.CallCardFact(fact=fact))
                await pilot.pause()
                card = app.query_one(CriticalFactCard)
                assert not card.editing
                card.action_edit()
                await pilot.pause()
                assert card.editing, "[E] must set card.editing = True"
                await pilot.press("q")

        asyncio.run(scenario())

    def test_edit_enter_confirms_with_edited_value(self):
        async def scenario():
            fact = _make_fact(critical=True, normalized_value="REF-88211")
            app = _CallCardHostApp()
            async with app.run_test(size=(120, 40)) as pilot:
                app.post_message(CallCardView.CallCardFact(fact=fact))
                await pilot.pause()
                card = app.query_one(CriticalFactCard)
                card.action_edit()
                await pilot.pause()
                edit_input = card.query_one("#edit-input")
                edit_input.value = "REF-88999"
                await pilot.press("enter")
                await pilot.pause()
                assert not card.editing, "Enter must exit edit mode"
                assert card.normalized_value == "REF-88999", (
                    "Enter must confirm the edited value"
                )
                await pilot.press("q")

        asyncio.run(scenario())

    def test_edit_esc_cancels_without_changing_value(self):
        async def scenario():
            fact = _make_fact(critical=True, normalized_value="REF-88211")
            app = _CallCardHostApp()
            async with app.run_test(size=(120, 40)) as pilot:
                app.post_message(CallCardView.CallCardFact(fact=fact))
                await pilot.pause()
                card = app.query_one(CriticalFactCard)
                card.action_edit()
                await pilot.pause()
                edit_input = card.query_one("#edit-input")
                edit_input.value = "REF-WRONG"
                await pilot.press("escape")
                await pilot.pause()
                assert not card.editing, "Esc must exit edit mode"
                assert card.normalized_value == "REF-88211", (
                    "Esc must revert to original value, not save the edit"
                )
                await pilot.press("q")

        asyncio.run(scenario())

    def test_edit_button_disabled_while_editing(self):
        async def scenario():
            fact = _make_fact(critical=True)
            app = _CallCardHostApp()
            async with app.run_test(size=(120, 40)) as pilot:
                app.post_message(CallCardView.CallCardFact(fact=fact))
                await pilot.pause()
                card = app.query_one(CriticalFactCard)
                card.action_edit()
                await pilot.pause()
                edit_btn = card.query_one("#edit-btn")
                assert edit_btn.disabled, "[E] button must be disabled while edit mode is active"
                await pilot.press("q")

        asyncio.run(scenario())

    def test_confirm_marks_card_confirmed(self):
        async def scenario():
            fact = _make_fact(critical=True)
            app = _CallCardHostApp()
            async with app.run_test(size=(120, 40)) as pilot:
                app.post_message(CallCardView.CallCardFact(fact=fact))
                await pilot.pause()
                card = app.query_one(CriticalFactCard)
                assert not card.confirmed
                card.action_confirm()
                await pilot.pause()
                assert card.confirmed, "[D] must set card.confirmed = True"
                await pilot.press("q")

        asyncio.run(scenario())

    def test_dismiss_removes_card_from_feed(self):
        async def scenario():
            fact = _make_fact(critical=True)
            app = _CallCardHostApp()
            async with app.run_test(size=(120, 40)) as pilot:
                app.post_message(CallCardView.CallCardFact(fact=fact))
                await pilot.pause()
                assert len(list(app.query(CriticalFactCard))) == 1
                card = app.query_one(CriticalFactCard)
                card.action_dismiss()
                await pilot.pause()
                assert len(list(app.query(CriticalFactCard))) == 0, (
                    "[X] must remove the CriticalFactCard from the feed"
                )
                await pilot.press("q")

        asyncio.run(scenario())


# ---------------------------------------------------------------------------
# FactCard
# ---------------------------------------------------------------------------

class TestFactCard:
    def test_renders_fact_header_raw_text_and_normalized_value(self):
        async def scenario():
            fact = _make_fact(
                critical=False,
                fact_type=FactType.PHONE,
                raw_text="my number is 415-555-1234",
                normalized_value="+14155551234",
                confidence=0.80,
            )
            app = _CallCardHostApp()
            async with app.run_test(size=(120, 40)) as pilot:
                app.post_message(CallCardView.CallCardFact(fact=fact))
                await pilot.pause()
                card = app.query_one(FactCard)
                rendered = str(card.render())
                assert "● FACT" in rendered or card.has_class("fact-card"), (
                    "FactCard must show '● FACT' header"
                )
                assert "+14155551234" in rendered
                assert "415-555-1234" in rendered
                await pilot.press("q")

        asyncio.run(scenario())

    def test_no_edit_button_on_fact_card(self):
        async def scenario():
            fact = _make_fact(critical=False)
            app = _CallCardHostApp()
            async with app.run_test(size=(120, 40)) as pilot:
                app.post_message(CallCardView.CallCardFact(fact=fact))
                await pilot.pause()
                card = app.query_one(FactCard)
                assert list(card.query("#edit-btn")) == [], (
                    "FactCard must not have an [E] Edit button"
                )
                await pilot.press("q")

        asyncio.run(scenario())

    def test_confirm_marks_fact_card_confirmed(self):
        async def scenario():
            fact = _make_fact(critical=False)
            app = _CallCardHostApp()
            async with app.run_test(size=(120, 40)) as pilot:
                app.post_message(CallCardView.CallCardFact(fact=fact))
                await pilot.pause()
                card = app.query_one(FactCard)
                assert not card.confirmed
                card.action_confirm()
                await pilot.pause()
                assert card.confirmed, "[D] must set FactCard.confirmed = True"
                await pilot.press("q")

        asyncio.run(scenario())

    def test_dismiss_removes_fact_card(self):
        async def scenario():
            fact = _make_fact(critical=False)
            app = _CallCardHostApp()
            async with app.run_test(size=(120, 40)) as pilot:
                app.post_message(CallCardView.CallCardFact(fact=fact))
                await pilot.pause()
                assert len(list(app.query(FactCard))) == 1
                card = app.query_one(FactCard)
                card.action_dismiss()
                await pilot.pause()
                assert len(list(app.query(FactCard))) == 0, (
                    "[X] must remove the FactCard from the feed"
                )
                await pilot.press("q")

        asyncio.run(scenario())


# ---------------------------------------------------------------------------
# ActionItemCard
# ---------------------------------------------------------------------------

class TestActionItemCard:
    def test_renders_description_owner_and_due_date(self):
        async def scenario():
            item = _make_action_item(
                description="Call back by Friday",
                owner="operator",
                due_date="2026-07-03",
            )
            app = _CallCardHostApp()
            async with app.run_test(size=(120, 40)) as pilot:
                app.post_message(CallCardView.CallCardActionItem(item=item))
                await pilot.pause()
                card = app.query_one(ActionItemCard)
                rendered = str(card.render())
                assert "Call back by Friday" in rendered
                assert "2026-07-03" in rendered
                await pilot.press("q")

        asyncio.run(scenario())

    def test_empty_owner_displays_them(self):
        async def scenario():
            item = _make_action_item(owner="")
            app = _CallCardHostApp()
            async with app.run_test(size=(120, 40)) as pilot:
                app.post_message(CallCardView.CallCardActionItem(item=item))
                await pilot.pause()
                card = app.query_one(ActionItemCard)
                rendered = str(card.render())
                assert "Them" in rendered, (
                    "Empty ActionItem.owner must display as 'Them'"
                )
                await pilot.press("q")

        asyncio.run(scenario())

    def test_absent_due_date_shows_placeholder(self):
        async def scenario():
            item = _make_action_item(due_date=None)
            app = _CallCardHostApp()
            async with app.run_test(size=(120, 40)) as pilot:
                app.post_message(CallCardView.CallCardActionItem(item=item))
                await pilot.pause()
                card = app.query_one(ActionItemCard)
                rendered = str(card.render())
                assert "Due: —" in rendered or "Due: -" in rendered, (
                    "Absent due_date must render as 'Due: —' or 'Due: -'"
                )
                await pilot.press("q")

        asyncio.run(scenario())

    def test_edit_opens_three_input_fields(self):
        async def scenario():
            item = _make_action_item()
            app = _CallCardHostApp()
            async with app.run_test(size=(120, 40)) as pilot:
                app.post_message(CallCardView.CallCardActionItem(item=item))
                await pilot.pause()
                card = app.query_one(ActionItemCard)
                assert not card.editing
                card.action_edit()
                await pilot.pause()
                assert card.editing
                inputs = list(card.query("Input"))
                assert len(inputs) >= 3, (
                    "[E] edit mode must show inputs for description, owner, and due_date"
                )
                await pilot.press("q")

        asyncio.run(scenario())

    def test_edit_enter_saves_description_change(self):
        async def scenario():
            item = _make_action_item(description="Original description")
            app = _CallCardHostApp()
            async with app.run_test(size=(120, 40)) as pilot:
                app.post_message(CallCardView.CallCardActionItem(item=item))
                await pilot.pause()
                card = app.query_one(ActionItemCard)
                card.action_edit()
                await pilot.pause()
                desc_input = card.query_one("#desc-input")
                desc_input.value = "Updated description"
                await pilot.press("enter")
                await pilot.pause()
                assert not card.editing, "Enter must exit edit mode"
                assert card.description == "Updated description", (
                    "Enter must persist the edited description"
                )
                await pilot.press("q")

        asyncio.run(scenario())

    def test_edit_esc_cancels_without_saving(self):
        async def scenario():
            item = _make_action_item(description="Original description")
            app = _CallCardHostApp()
            async with app.run_test(size=(120, 40)) as pilot:
                app.post_message(CallCardView.CallCardActionItem(item=item))
                await pilot.pause()
                card = app.query_one(ActionItemCard)
                card.action_edit()
                await pilot.pause()
                desc_input = card.query_one("#desc-input")
                desc_input.value = "Discarded edit"
                await pilot.press("escape")
                await pilot.pause()
                assert not card.editing, "Esc must exit edit mode"
                assert card.description == "Original description", (
                    "Esc must not save the edit"
                )
                await pilot.press("q")

        asyncio.run(scenario())


# ---------------------------------------------------------------------------
# CallCardView — event routing
# ---------------------------------------------------------------------------

class TestCallCardView:
    def test_call_card_started_sets_caller_phone_and_topic(self):
        async def scenario():
            app = _CallCardHostApp()
            async with app.run_test(size=(120, 40)) as pilot:
                app.post_message(
                    CallCardView.CallCardStarted(
                        caller_phone="+15551234567",
                        topic="Insurance Claims",
                        session_id="sess-hdr",
                    )
                )
                await pilot.pause()
                view = app.query_one(CallCardView)
                assert view.caller_phone == "+15551234567"
                assert view.topic == "Insurance Claims"
                await pilot.press("q")

        asyncio.run(scenario())

    def test_call_card_started_shows_expanded_disclosure_card(self):
        async def scenario():
            app = _CallCardHostApp()
            async with app.run_test(size=(120, 40)) as pilot:
                app.post_message(
                    CallCardView.CallCardStarted(
                        caller_phone="+15551234567",
                        topic="billing",
                        session_id="sess-dc",
                    )
                )
                await pilot.pause()
                cards = list(app.query(DisclosureCard))
                assert len(cards) == 1
                assert cards[0].is_expanded, (
                    "call_card_started must show DisclosureCard in expanded state"
                )
                await pilot.press("q")

        asyncio.run(scenario())

    def test_critical_fact_routes_to_critical_fact_card(self):
        async def scenario():
            fact = _make_fact(critical=True)
            app = _CallCardHostApp()
            async with app.run_test(size=(120, 40)) as pilot:
                app.post_message(CallCardView.CallCardFact(fact=fact))
                await pilot.pause()
                assert len(list(app.query(CriticalFactCard))) == 1
                assert len(list(app.query(FactCard))) == 0, (
                    "critical=True must produce CriticalFactCard, not FactCard"
                )
                await pilot.press("q")

        asyncio.run(scenario())

    def test_non_critical_fact_routes_to_fact_card(self):
        async def scenario():
            fact = _make_fact(critical=False)
            app = _CallCardHostApp()
            async with app.run_test(size=(120, 40)) as pilot:
                app.post_message(CallCardView.CallCardFact(fact=fact))
                await pilot.pause()
                assert len(list(app.query(FactCard))) == 1
                assert len(list(app.query(CriticalFactCard))) == 0, (
                    "critical=False must produce FactCard, not CriticalFactCard"
                )
                await pilot.press("q")

        asyncio.run(scenario())

    def test_action_item_event_prepends_action_item_card(self):
        async def scenario():
            item = _make_action_item()
            app = _CallCardHostApp()
            async with app.run_test(size=(120, 40)) as pilot:
                app.post_message(CallCardView.CallCardActionItem(item=item))
                await pilot.pause()
                assert len(list(app.query(ActionItemCard))) == 1
                await pilot.press("q")

        asyncio.run(scenario())

    def test_call_card_ended_shows_enriching_indicator(self):
        async def scenario():
            app = _CallCardHostApp()
            async with app.run_test(size=(120, 40)) as pilot:
                app.post_message(
                    CallCardView.CallCardEnded(session_id="sess-end")
                )
                await pilot.pause()
                indicator = app.query_one("#enriching-indicator")
                assert indicator.display, (
                    "call_card_ended must show the enriching indicator"
                )
                rendered = str(indicator.render())
                assert "Enriching" in rendered or "⏳" in rendered
                await pilot.press("q")

        asyncio.run(scenario())

    def test_call_card_enriched_hides_enriching_indicator(self):
        async def scenario():
            app = _CallCardHostApp()
            async with app.run_test(size=(120, 40)) as pilot:
                app.post_message(
                    CallCardView.CallCardEnded(session_id="sess-enr")
                )
                await pilot.pause()
                app.post_message(
                    CallCardView.CallCardEnriched(
                        session_id="sess-enr",
                        new_facts=[],
                        enriched_items=[],
                    )
                )
                await pilot.pause()
                indicator = app.query_one("#enriching-indicator")
                assert not indicator.display, (
                    "call_card_enriched must hide the enriching indicator"
                )
                await pilot.press("q")

        asyncio.run(scenario())

    def test_newest_card_prepended_at_top_of_feed(self):
        async def scenario():
            fact1 = _make_fact(
                normalized_value="REF-11111",
                raw_text="first reference REF-11111",
                critical=False,
            )
            fact2 = _make_fact(
                normalized_value="REF-22222",
                raw_text="second reference REF-22222",
                critical=False,
            )
            app = _CallCardHostApp()
            async with app.run_test(size=(120, 40)) as pilot:
                app.post_message(CallCardView.CallCardFact(fact=fact1))
                await pilot.pause()
                app.post_message(CallCardView.CallCardFact(fact=fact2))
                await pilot.pause()
                feed_cards = list(app.query(FactCard))
                assert len(feed_cards) == 2
                assert feed_cards[0].normalized_value == "REF-22222", (
                    "The most recently added card must appear first (prepend order)"
                )
                assert feed_cards[1].normalized_value == "REF-11111"
                await pilot.press("q")

        asyncio.run(scenario())
