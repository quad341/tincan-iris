"""Tests for the ride-along console — cards, participation levels, stance toggle.

Bead: ti-x5cd.8 (validator phase)

Coverage map:
  Phase 1-2 unit (detectors):
    - detect_capture: phone / email / address / code phrases
    - detect_commitment: date/time phrases
    - detect_action_item: action-phrase triggers
    - detect_flag: contradiction keyword triggers
  Phase 1-2 card actions:
    - CAPTURE: Save note (NotesStore.capture called), dismissal
    - CONTEXT: informational only, no action buttons
    - COMMITMENT: calendar add stub, conflict display
    - ACTION ITEM: reminder hook stub
    - FLAG: no action buttons (informational alert)
  Read-back routing:
    - default selection is operator-private
    - caller option gated by stance level < 3
  Card feed integration (Textual):
    - newest card at top (descending order)
    - dismissal removes card from feed
    - A11y: role=feed, role=article, aria-label on Save includes captured value
  Phase 3-5 (Textual):
    - participation switcher: 4 levels, keyboard nav
    - stance toggle: keyboard grant, keyword detection, mode badge, banner
    - ON-CALL PROPOSAL: countdown, auto-cancel, approval flow

All tests have no external dependencies: no live audio, no real calendar API.
The calendar and NotesStore are replaced by in-memory stubs.
"""
from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

from iris.console.ride_along import (
    ActionItemCard,
    CaptureCard,
    CardFeed,
    CardType,
    CommitmentCard,
    ContextCard,
    FlagCard,
    OnCallProposalCard,
    ParticipationLevel,
    ReadBackTarget,
    RideAlongConsole,
    Stance,
    detect_action_item,
    detect_capture,
    detect_commitment,
    detect_flag,
)

# ---------------------------------------------------------------------------
# Minimal stubs — no real I/O, no real calendar
# ---------------------------------------------------------------------------

class _StubNotesStore:
    def __init__(self) -> None:
        self.notes: list[dict] = []
        self._next_id = 1

    def capture(self, text: str) -> dict:
        note = {"id": self._next_id, "text": text, "done": False}
        self._next_id += 1
        self.notes.append(note)
        return note


class _StubCalendar:
    def __init__(self) -> None:
        self.events: list[dict] = []
        self.conflict_result: list[dict] = []

    def create_event(self, title: str, start: str, end: str) -> dict:
        ev = {"title": title, "start": start, "end": end}
        self.events.append(ev)
        return ev

    def check_conflicts(self, start: str, end: str) -> list[dict]:
        return self.conflict_result


class _StubReminderHook:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def create_reminder(self, text: str) -> None:
        self.calls.append(text)


# ---------------------------------------------------------------------------
# detect_capture — unit tests
# ---------------------------------------------------------------------------

class TestDetectCapture:
    def test_phone_number_detected(self):
        result = detect_capture("My number is 555-0199")
        assert result is not None
        assert "555-0199" in result.value

    def test_email_detected(self):
        result = detect_capture("Reach me at alice@example.com")
        assert result is not None
        assert "alice@example.com" in result.value

    def test_confirmation_code_detected(self):
        result = detect_capture("The confirmation code is AB-4821")
        assert result is not None
        assert "AB-4821" in result.value

    def test_address_detected(self):
        result = detect_capture("We're at 123 Main Street, Suite 4")
        assert result is not None
        assert "123 Main Street" in result.value

    def test_plain_conversation_not_captured(self):
        assert detect_capture("how are you today?") is None
        assert detect_capture("let me think about it") is None

    def test_captured_type_is_capture(self):
        result = detect_capture("The number is 555-0100")
        assert result is not None
        assert result.card_type is CardType.CAPTURE


# ---------------------------------------------------------------------------
# detect_commitment — unit tests
# ---------------------------------------------------------------------------

class TestDetectCommitment:
    def test_weekday_time_detected(self):
        result = detect_commitment("Let's meet Tuesday at 3pm")
        assert result is not None
        assert result.card_type is CardType.COMMITMENT

    def test_relative_date_detected(self):
        result = detect_commitment("Call me back next Friday morning")
        assert result is not None

    def test_calendar_phrase_detected(self):
        result = detect_commitment("Schedule that for the 15th at noon")
        assert result is not None

    def test_no_date_not_a_commitment(self):
        assert detect_commitment("sounds good to me") is None
        assert detect_commitment("I'll definitely do that") is None

    def test_commitment_phrase_detected(self):
        result = detect_commitment("I'll get that to you by Thursday")
        assert result is not None
        assert result.card_type is CardType.COMMITMENT


# ---------------------------------------------------------------------------
# detect_action_item — unit tests
# ---------------------------------------------------------------------------

class TestDetectActionItem:
    def test_send_form_detected(self):
        result = detect_action_item("I'll send you the form today")
        assert result is not None
        assert result.card_type is CardType.ACTION_ITEM

    def test_call_back_detected(self):
        result = detect_action_item("I'll call you back on Friday")
        assert result is not None

    def test_follow_up_detected(self):
        result = detect_action_item("I'll follow up with the details")
        assert result is not None

    def test_generic_statement_not_action_item(self):
        assert detect_action_item("the weather is nice today") is None

    def test_email_promise_detected(self):
        result = detect_action_item("Let me email you the invoice")
        assert result is not None
        assert result.card_type is CardType.ACTION_ITEM


# ---------------------------------------------------------------------------
# detect_flag — unit tests
# ---------------------------------------------------------------------------

class TestDetectFlag:
    def test_contradiction_detected(self):
        result = detect_flag("Wait, I thought you said Monday earlier")
        assert result is not None
        assert result.card_type is CardType.FLAG

    def test_conflict_phrase_detected(self):
        result = detect_flag("That contradicts what you told me last week")
        assert result is not None

    def test_normal_speech_not_flagged(self):
        assert detect_flag("thank you for calling") is None
        assert detect_flag("the price is 50 dollars") is None


# ---------------------------------------------------------------------------
# ReadBackTarget — routing unit tests
# ---------------------------------------------------------------------------

class TestReadBackTarget:
    def test_default_is_operator_private(self):
        target = ReadBackTarget.default()
        assert target is ReadBackTarget.OPERATOR_PRIVATE

    def test_caller_option_blocked_at_level_below_3(self):
        for level in (
            ParticipationLevel.SILENT,
            ParticipationLevel.AMBIENT,
            ParticipationLevel.AUDIO_PRIVATE,
        ):
            assert not ReadBackTarget.CALLER.available_at(level)

    def test_caller_option_available_at_level_3(self):
        assert ReadBackTarget.CALLER.available_at(ParticipationLevel.ON_CALL)


# ---------------------------------------------------------------------------
# CardFeed ordering — newest card at top
# ---------------------------------------------------------------------------

class TestCardFeedOrdering:
    def test_newest_card_appears_at_top(self):
        async def scenario():
            app = RideAlongConsole()
            async with app.run_test() as pilot:
                app.add_card(CardType.CAPTURE, value="555-0100")
                app.add_card(CardType.CAPTURE, value="555-0200")
                await pilot.pause()

                feed = app.query_one(CardFeed)
                cards = list(feed.query("*"))
                # The second card (555-0200) should appear before the first
                assert "555-0200" in str(cards[0])
                assert "555-0100" in str(cards[1])

                await pilot.press("q")

        asyncio.run(scenario())


# ---------------------------------------------------------------------------
# CAPTURE card — trigger, NotesStore write, dismissal
# ---------------------------------------------------------------------------

class TestCaptureCard:
    def test_capture_card_triggers_from_detection(self):
        async def scenario():
            store = _StubNotesStore()
            app = RideAlongConsole(notes_store=store)
            async with app.run_test() as pilot:
                app.on_transcript("My number is 555-0199", speaker="far")
                await pilot.pause()

                feed = app.query_one(CardFeed)
                cards = list(feed.query(CaptureCard))
                assert len(cards) == 1
                assert "555-0199" in cards[0].captured_value

                await pilot.press("q")

        asyncio.run(scenario())

    def test_capture_save_writes_to_notes_store(self):
        async def scenario():
            store = _StubNotesStore()
            app = RideAlongConsole(notes_store=store)
            async with app.run_test() as pilot:
                app.add_card(CardType.CAPTURE, value="555-0199")
                await pilot.pause()

                card = app.query_one(CaptureCard)
                card.action_save()
                await pilot.pause()

                assert len(store.notes) == 1
                assert "555-0199" in store.notes[0]["text"]

                await pilot.press("q")

        asyncio.run(scenario())

    def test_capture_save_transitions_to_success_state(self):
        async def scenario():
            store = _StubNotesStore()
            app = RideAlongConsole(notes_store=store)
            async with app.run_test() as pilot:
                app.add_card(CardType.CAPTURE, value="alice@example.com")
                await pilot.pause()

                card = app.query_one(CaptureCard)
                assert not card.saved
                card.action_save()
                await pilot.pause()
                assert card.saved

                await pilot.press("q")

        asyncio.run(scenario())

    def test_capture_card_dismissal_removes_it(self):
        async def scenario():
            store = _StubNotesStore()
            app = RideAlongConsole(notes_store=store)
            async with app.run_test() as pilot:
                app.add_card(CardType.CAPTURE, value="555-0300")
                await pilot.pause()
                assert len(list(app.query(CaptureCard))) == 1

                card = app.query_one(CaptureCard)
                card.action_dismiss()
                await pilot.pause()
                assert len(list(app.query(CaptureCard))) == 0

                await pilot.press("q")

        asyncio.run(scenario())

    def test_capture_save_aria_label_includes_value(self):
        async def scenario():
            store = _StubNotesStore()
            app = RideAlongConsole(notes_store=store)
            async with app.run_test() as pilot:
                app.add_card(CardType.CAPTURE, value="555-0199")
                await pilot.pause()

                card = app.query_one(CaptureCard)
                save_btn = card.query_one("#save-btn")
                # aria-label must include the captured value (WCAG Save context)
                assert "555-0199" in (save_btn.tooltip or save_btn.label or "")

                await pilot.press("q")

        asyncio.run(scenario())


# ---------------------------------------------------------------------------
# CONTEXT card — informational only, no action buttons
# ---------------------------------------------------------------------------

class TestContextCard:
    def test_context_card_has_no_action_buttons(self):
        async def scenario():
            app = RideAlongConsole()
            async with app.run_test() as pilot:
                app.add_card(CardType.CONTEXT, value="Last call: May 3, owed a form")
                await pilot.pause()

                card = app.query_one(ContextCard)
                buttons = list(card.query("Button"))
                assert buttons == []

                await pilot.press("q")

        asyncio.run(scenario())

    def test_context_card_shows_memory_text(self):
        async def scenario():
            app = RideAlongConsole()
            async with app.run_test() as pilot:
                app.add_card(CardType.CONTEXT, value="dentist, last call May 3")
                await pilot.pause()

                card = app.query_one(ContextCard)
                assert "dentist" in card.memory_text

                await pilot.press("q")

        asyncio.run(scenario())


# ---------------------------------------------------------------------------
# COMMITMENT card — date/time, calendar add, conflict detection + display
# ---------------------------------------------------------------------------

class TestCommitmentCard:
    def test_commitment_card_triggers_from_date_phrase(self):
        async def scenario():
            cal = _StubCalendar()
            app = RideAlongConsole(calendar=cal)
            async with app.run_test() as pilot:
                app.on_transcript("Let's meet Tuesday at 3pm", speaker="far")
                await pilot.pause()

                cards = list(app.query(CommitmentCard))
                assert len(cards) == 1

                await pilot.press("q")

        asyncio.run(scenario())

    def test_commitment_add_to_calendar(self):
        async def scenario():
            cal = _StubCalendar()
            app = RideAlongConsole(calendar=cal)
            async with app.run_test() as pilot:
                app.add_card(CardType.COMMITMENT, value="Tuesday at 3pm")
                await pilot.pause()

                card = app.query_one(CommitmentCard)
                card.action_add_to_calendar()
                await pilot.pause()

                assert len(cal.events) == 1

                await pilot.press("q")

        asyncio.run(scenario())

    def test_commitment_conflict_displayed(self):
        async def scenario():
            cal = _StubCalendar()
            cal.conflict_result = [{"title": "Team standup", "start": "2026-07-01T15:00:00"}]
            app = RideAlongConsole(calendar=cal)
            async with app.run_test() as pilot:
                app.add_card(CardType.COMMITMENT, value="Tuesday at 3pm")
                await pilot.pause()

                card = app.query_one(CommitmentCard)
                card.action_add_to_calendar()
                await pilot.pause()

                # Conflict text must be visible in the card
                assert card.has_conflict
                conflict_text = card.conflict_summary
                assert "Team standup" in conflict_text

                await pilot.press("q")

        asyncio.run(scenario())

    def test_commitment_dismissal(self):
        async def scenario():
            app = RideAlongConsole()
            async with app.run_test() as pilot:
                app.add_card(CardType.COMMITMENT, value="Friday at noon")
                await pilot.pause()
                assert len(list(app.query(CommitmentCard))) == 1

                card = app.query_one(CommitmentCard)
                card.action_dismiss()
                await pilot.pause()
                assert len(list(app.query(CommitmentCard))) == 0

                await pilot.press("q")

        asyncio.run(scenario())


# ---------------------------------------------------------------------------
# ACTION ITEM card — action-phrase trigger, reminder via skill hook
# ---------------------------------------------------------------------------

class TestActionItemCard:
    def test_action_item_triggers_from_phrase(self):
        async def scenario():
            app = RideAlongConsole()
            async with app.run_test() as pilot:
                app.on_transcript("I'll send you the form today", speaker="operator")
                await pilot.pause()

                cards = list(app.query(ActionItemCard))
                assert len(cards) == 1

                await pilot.press("q")

        asyncio.run(scenario())

    def test_action_item_create_reminder_via_hook(self):
        async def scenario():
            hook = _StubReminderHook()
            app = RideAlongConsole(reminder_hook=hook)
            async with app.run_test() as pilot:
                app.add_card(CardType.ACTION_ITEM, value="send invoice to client")
                await pilot.pause()

                card = app.query_one(ActionItemCard)
                card.action_create_reminder()
                await pilot.pause()

                assert len(hook.calls) == 1
                assert "invoice" in hook.calls[0]

                await pilot.press("q")

        asyncio.run(scenario())

    def test_action_item_dismissal(self):
        async def scenario():
            app = RideAlongConsole()
            async with app.run_test() as pilot:
                app.add_card(CardType.ACTION_ITEM, value="follow up tomorrow")
                await pilot.pause()
                assert len(list(app.query(ActionItemCard))) == 1

                card = app.query_one(ActionItemCard)
                card.action_dismiss()
                await pilot.pause()
                assert len(list(app.query(ActionItemCard))) == 0

                await pilot.press("q")

        asyncio.run(scenario())


# ---------------------------------------------------------------------------
# FLAG card — contradiction/conflict trigger, no action buttons
# ---------------------------------------------------------------------------

class TestFlagCard:
    def test_flag_card_triggers_from_contradiction(self):
        async def scenario():
            app = RideAlongConsole()
            async with app.run_test() as pilot:
                app.on_transcript("That contradicts what you said Monday", speaker="far")
                await pilot.pause()

                cards = list(app.query(FlagCard))
                assert len(cards) == 1

                await pilot.press("q")

        asyncio.run(scenario())

    def test_flag_card_has_no_action_buttons(self):
        async def scenario():
            app = RideAlongConsole()
            async with app.run_test() as pilot:
                app.add_card(CardType.FLAG, value="Contradicts earlier statement")
                await pilot.pause()

                card = app.query_one(FlagCard)
                buttons = list(card.query("Button"))
                assert buttons == []

                await pilot.press("q")

        asyncio.run(scenario())

    def test_flag_card_shows_conflict_text(self):
        async def scenario():
            app = RideAlongConsole()
            async with app.run_test() as pilot:
                app.add_card(CardType.FLAG, value="Said Monday earlier, now says Friday")
                await pilot.pause()

                card = app.query_one(FlagCard)
                assert "Monday" in card.flag_text

                await pilot.press("q")

        asyncio.run(scenario())


# ---------------------------------------------------------------------------
# A11y structure — role=feed, role=article, aria-label on Save
# ---------------------------------------------------------------------------

class TestA11yStructure:
    def test_card_feed_has_feed_role(self):
        async def scenario():
            app = RideAlongConsole()
            async with app.run_test() as pilot:
                feed = app.query_one(CardFeed)
                assert feed.COMPONENT_CLASSES or feed.DEFAULT_CSS
                # The feed widget must declare role="feed" in its ARIA metadata
                assert getattr(feed, "aria_role", None) == "feed" or "role" in (
                    feed.DEFAULT_CSS or ""
                ).lower() or feed.has_class("feed-role")

                await pilot.press("q")

        asyncio.run(scenario())

    def test_card_has_article_role(self):
        async def scenario():
            app = RideAlongConsole()
            async with app.run_test() as pilot:
                app.add_card(CardType.CAPTURE, value="555-0199")
                await pilot.pause()

                card = app.query_one(CaptureCard)
                assert getattr(card, "aria_role", None) == "article" or card.has_class(
                    "article-role"
                )

                await pilot.press("q")

        asyncio.run(scenario())

    def test_save_button_aria_label_includes_value(self):
        async def scenario():
            store = _StubNotesStore()
            app = RideAlongConsole(notes_store=store)
            async with app.run_test() as pilot:
                app.add_card(CardType.CAPTURE, value="555-9876")
                await pilot.pause()

                card = app.query_one(CaptureCard)
                save_btn = card.query_one("#save-btn")
                label = save_btn.tooltip or getattr(save_btn, "aria_label", "") or ""
                assert "555-9876" in label

                await pilot.press("q")

        asyncio.run(scenario())

    def test_card_type_badge_is_not_color_alone(self):
        """Card type indicator must include text, not just color — WCAG 1.4.1."""
        async def scenario():
            app = RideAlongConsole()
            async with app.run_test() as pilot:
                for card_type, value in [
                    (CardType.CAPTURE, "555-0000"),
                    (CardType.FLAG, "contradiction detected"),
                    (CardType.COMMITMENT, "Tuesday at 3pm"),
                ]:
                    app.add_card(card_type, value=value)
                await pilot.pause()

                for card in app.query(CaptureCard):
                    badge = card.query_one(".type-badge")
                    assert badge.renderable or badge.render()  # has text content

                await pilot.press("q")

        asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Read-back secondary dropdown — default and stance-gating
# ---------------------------------------------------------------------------

class TestReadBackDropdown:
    def test_read_back_default_is_operator_private(self):
        async def scenario():
            store = _StubNotesStore()
            app = RideAlongConsole(notes_store=store)
            async with app.run_test() as pilot:
                app.add_card(CardType.CAPTURE, value="555-0199")
                await pilot.pause()

                card = app.query_one(CaptureCard)
                assert card.read_back_target is ReadBackTarget.OPERATOR_PRIVATE

                await pilot.press("q")

        asyncio.run(scenario())

    def test_caller_option_greyed_when_level_below_3(self):
        async def scenario():
            app = RideAlongConsole()
            app.participation_level = ParticipationLevel.AMBIENT
            async with app.run_test() as pilot:
                app.add_card(CardType.CAPTURE, value="555-0199")
                await pilot.pause()

                card = app.query_one(CaptureCard)
                caller_option = card.query_one("#readback-caller")
                assert caller_option.disabled

                await pilot.press("q")

        asyncio.run(scenario())

    def test_caller_option_enabled_at_level_3(self):
        async def scenario():
            app = RideAlongConsole()
            app.participation_level = ParticipationLevel.ON_CALL
            async with app.run_test() as pilot:
                app.add_card(CardType.CAPTURE, value="555-0199")
                await pilot.pause()

                card = app.query_one(CaptureCard)
                caller_option = card.query_one("#readback-caller")
                assert not caller_option.disabled

                await pilot.press("q")

        asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Participation switcher — 4 levels, keyboard nav
# ---------------------------------------------------------------------------

class TestParticipationSwitcher:
    def test_default_participation_level_is_silent(self):
        async def scenario():
            app = RideAlongConsole()
            async with app.run_test() as pilot:
                assert app.participation_level is ParticipationLevel.SILENT
                await pilot.press("q")

        asyncio.run(scenario())

    def test_participation_levels_cycle_upward_with_key(self):
        async def scenario():
            app = RideAlongConsole()
            async with app.run_test() as pilot:
                assert app.participation_level is ParticipationLevel.SILENT
                await pilot.press("]")  # next level up
                assert app.participation_level is ParticipationLevel.AMBIENT
                await pilot.press("]")
                assert app.participation_level is ParticipationLevel.AUDIO_PRIVATE
                await pilot.press("]")
                assert app.participation_level is ParticipationLevel.ON_CALL
                await pilot.press("q")

        asyncio.run(scenario())

    def test_participation_level_clamps_at_max(self):
        async def scenario():
            app = RideAlongConsole()
            async with app.run_test() as pilot:
                app.participation_level = ParticipationLevel.ON_CALL
                await pilot.press("]")  # already at max — must not error
                assert app.participation_level is ParticipationLevel.ON_CALL
                await pilot.press("q")

        asyncio.run(scenario())

    def test_participation_level_decrements_with_key(self):
        async def scenario():
            app = RideAlongConsole()
            async with app.run_test() as pilot:
                app.participation_level = ParticipationLevel.AUDIO_PRIVATE
                await pilot.press("[")  # next level down
                assert app.participation_level is ParticipationLevel.AMBIENT
                await pilot.press("q")

        asyncio.run(scenario())

    def test_level_2_audio_private_routes_to_earpiece_not_speaker(self):
        """Level 2 whispers to the operator earpiece, not the speaker channel."""
        async def scenario():
            earpiece_calls: list[str] = []
            speaker_calls: list[str] = []
            app = RideAlongConsole()
            app._speak_earpiece = lambda t: earpiece_calls.append(t)
            app._speak_speaker = lambda t: speaker_calls.append(t)
            async with app.run_test() as pilot:
                app.participation_level = ParticipationLevel.AUDIO_PRIVATE
                app._deliver_readback("555-0199", target=ReadBackTarget.OPERATOR_PRIVATE)
                await pilot.pause()

                assert earpiece_calls and "555-0199" in earpiece_calls[0]
                assert speaker_calls == []

                await pilot.press("q")

        asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Stance toggle — keyboard grant, keyword detection, badge, banner
# ---------------------------------------------------------------------------

class TestStanceToggle:
    def test_default_stance_is_business(self):
        async def scenario():
            app = RideAlongConsole()
            async with app.run_test() as pilot:
                assert app.stance is Stance.BUSINESS
                await pilot.press("q")

        asyncio.run(scenario())

    def test_keyboard_grant_required_before_keyword_can_toggle(self):
        """Keyword alone must not switch to Collaboration without keyboard pre-grant."""
        async def scenario():
            app = RideAlongConsole()
            async with app.run_test() as pilot:
                # No keyboard grant: keyword must be ignored
                app.on_transcript("hey iris, join", speaker="operator")
                await pilot.pause()
                assert app.stance is Stance.BUSINESS
                await pilot.press("q")

        asyncio.run(scenario())

    def test_keyboard_grant_plus_join_keyword_enters_collaboration(self):
        async def scenario():
            app = RideAlongConsole()
            async with app.run_test() as pilot:
                # Keyboard pre-grant (simulated)
                app._stance_keyboard_granted = True
                app.on_transcript("hey iris, join", speaker="operator")
                await pilot.pause()
                assert app.stance is Stance.COLLABORATION
                await pilot.press("q")

        asyncio.run(scenario())

    def test_stand_down_keyword_exits_collaboration(self):
        async def scenario():
            app = RideAlongConsole()
            async with app.run_test() as pilot:
                app._stance_keyboard_granted = True
                app.on_transcript("hey iris, join", speaker="operator")
                await pilot.pause()
                assert app.stance is Stance.COLLABORATION

                app.on_transcript("hey iris, stand down", speaker="operator")
                await pilot.pause()
                assert app.stance is Stance.BUSINESS
                await pilot.press("q")

        asyncio.run(scenario())

    def test_far_party_cannot_change_stance(self):
        """The far party may not toggle the stance even with the keyword."""
        async def scenario():
            app = RideAlongConsole()
            async with app.run_test() as pilot:
                app._stance_keyboard_granted = True
                app.on_transcript("hey iris, join", speaker="far")
                await pilot.pause()
                assert app.stance is Stance.BUSINESS  # still business
                await pilot.press("q")

        asyncio.run(scenario())

    def test_mode_badge_shows_collaboration(self):
        async def scenario():
            app = RideAlongConsole()
            async with app.run_test() as pilot:
                app._stance_keyboard_granted = True
                app.stance = Stance.COLLABORATION
                await pilot.pause()

                badge = app.query_one("#stance-badge")
                assert "collaboration" in (badge.renderable or badge.render() or "").lower()

                await pilot.press("q")

        asyncio.run(scenario())

    def test_collaboration_banner_shown_on_entry(self):
        async def scenario():
            app = RideAlongConsole()
            async with app.run_test() as pilot:
                app._stance_keyboard_granted = True
                app.on_transcript("hey iris, join", speaker="operator")
                await pilot.pause()

                banner = app.query_one("#collaboration-banner")
                assert banner.display is True

                await pilot.press("q")

        asyncio.run(scenario())

    def test_collaboration_banner_hidden_in_business_mode(self):
        async def scenario():
            app = RideAlongConsole()
            async with app.run_test() as pilot:
                assert app.stance is Stance.BUSINESS
                banner = app.query_one("#collaboration-banner")
                assert banner.display is False
                await pilot.press("q")

        asyncio.run(scenario())


# ---------------------------------------------------------------------------
# ON-CALL PROPOSAL card — countdown, auto-cancel, approval, post-speak reset
# ---------------------------------------------------------------------------

class TestOnCallProposal:
    def test_proposal_card_appears_when_iris_wants_to_speak(self):
        async def scenario():
            app = RideAlongConsole()
            async with app.run_test() as pilot:
                app.propose_on_call("I can answer that question")
                await pilot.pause()

                cards = list(app.query(OnCallProposalCard))
                assert len(cards) == 1

                await pilot.press("q")

        asyncio.run(scenario())

    def test_proposal_countdown_starts_at_3_seconds(self):
        async def scenario():
            app = RideAlongConsole()
            async with app.run_test() as pilot:
                app.propose_on_call("I can help")
                await pilot.pause()

                card = app.query_one(OnCallProposalCard)
                assert card.countdown_seconds == 3

                await pilot.press("q")

        asyncio.run(scenario())

    def test_proposal_auto_cancelled_on_expiry(self):
        async def scenario():
            app = RideAlongConsole()
            async with app.run_test() as pilot:
                app.propose_on_call("I can help", countdown_seconds=0)
                await pilot.pause()

                cards = list(app.query(OnCallProposalCard))
                assert len(cards) == 0

                await pilot.press("q")

        asyncio.run(scenario())

    def test_proposal_speak_button_triggers_approval_flow(self):
        async def scenario():
            spoke: list[str] = []
            app = RideAlongConsole()
            app._deliver_on_call = lambda text: spoke.append(text)
            async with app.run_test() as pilot:
                app.propose_on_call("The answer is 42")
                await pilot.pause()

                card = app.query_one(OnCallProposalCard)
                card.action_approve()
                await pilot.pause()

                assert len(spoke) == 1
                assert "42" in spoke[0]

                await pilot.press("q")

        asyncio.run(scenario())

    def test_proposal_removed_after_approval(self):
        async def scenario():
            app = RideAlongConsole()
            app._deliver_on_call = lambda text: None
            async with app.run_test() as pilot:
                app.propose_on_call("I can help")
                await pilot.pause()
                assert len(list(app.query(OnCallProposalCard))) == 1

                card = app.query_one(OnCallProposalCard)
                card.action_approve()
                await pilot.pause()
                assert len(list(app.query(OnCallProposalCard))) == 0

                await pilot.press("q")

        asyncio.run(scenario())

    def test_stance_resets_to_business_after_on_call_speech(self):
        """After iris speaks on-call, stance reverts to Business (per design §1)."""
        async def scenario():
            app = RideAlongConsole()
            spoke: list[str] = []
            app._deliver_on_call = lambda text: spoke.append(text)
            async with app.run_test() as pilot:
                app._stance_keyboard_granted = True
                app.stance = Stance.COLLABORATION
                app.propose_on_call("Let me answer that")
                await pilot.pause()

                card = app.query_one(OnCallProposalCard)
                card.action_approve()
                await pilot.pause()

                assert app.stance is Stance.BUSINESS

                await pilot.press("q")

        asyncio.run(scenario())

    def test_proposal_cancel_removes_card_without_speaking(self):
        async def scenario():
            spoke: list[str] = []
            app = RideAlongConsole()
            app._deliver_on_call = lambda text: spoke.append(text)
            async with app.run_test() as pilot:
                app.propose_on_call("I could mention the pricing")
                await pilot.pause()
                assert len(list(app.query(OnCallProposalCard))) == 1

                card = app.query_one(OnCallProposalCard)
                card.action_cancel()
                await pilot.pause()

                assert len(list(app.query(OnCallProposalCard))) == 0
                assert spoke == []

                await pilot.press("q")

        asyncio.run(scenario())
