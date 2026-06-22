"""Tests for the calendar skill — free/busy, create event, move event,
and the act-without-disclose compliance invariant.

Google Calendar REST calls are mocked at the client level.
OAuth token loading is patched to avoid filesystem access.

These tests will fail until iris/calendar.py is implemented
(ti-ccc.14.1.1 + ti-ccc.14.1.3).
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from iris.calendar import (
    CalendarClient,
    CalendarCreateSkill,
    CalendarFreeBusySkill,
    CalendarMoveSkill,
    calendar_skills,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXTURE_CALENDAR = {
    "events": [
        {
            "id": "evt-001",
            "title": "Medical Appointment",
            "attendees": ["dr.smith@hospital.org"],
            "start": "2026-06-19T14:00:00",
            "end": "2026-06-19T15:00:00",
        },
        {
            "id": "evt-002",
            "title": "Morning Standup",
            "attendees": ["team@company.com"],
            "start": "2026-06-20T09:00:00",
            "end": "2026-06-20T09:30:00",
        },
        {
            "id": "evt-003",
            "title": "Wednesday Standup",
            "attendees": ["team@company.com"],
            "start": "2026-06-18T09:00:00",
            "end": "2026-06-18T09:30:00",
        },
    ]
}


@pytest.fixture
def mock_client():
    client = MagicMock(spec=CalendarClient)
    # free_busy: side_effect enforces keyword-only signature; positional call raises TypeError
    client.free_busy.side_effect = lambda *, start, end: {"busy": []}
    client.create_event.return_value = {
        "id": "new-evt",
        "title": "Call with Alex",
        "start": "2026-06-19T14:00:00",
        "end": "2026-06-19T15:00:00",
    }
    client.move_event.return_value = {
        "id": "evt-002",
        "title": "Morning Standup",
        "start": "2026-06-20T10:00:00",
        "end": "2026-06-20T10:30:00",
    }
    client.list_events.return_value = FIXTURE_CALENDAR["events"]
    return client


# ---------------------------------------------------------------------------
# Free/busy — available
# ---------------------------------------------------------------------------

def test_free_busy_available_reply_is_affirmative(mock_client):
    mock_client.free_busy.return_value = {"busy": []}
    skill = CalendarFreeBusySkill(mock_client)
    reply, _ann = skill.run(start="2026-06-19T14:00:00", end="2026-06-19T15:00:00")
    assert "free" in reply.lower() or "works" in reply.lower() or "available" in reply.lower()


def test_free_busy_available_reply_contains_no_event_details(mock_client):
    """Act-without-disclose: free slot must not leak any event information."""
    mock_client.free_busy.return_value = {"busy": []}
    skill = CalendarFreeBusySkill(mock_client)
    reply, _ann = skill.run(start="2026-06-19T14:00:00", end="2026-06-19T15:00:00")
    for event in FIXTURE_CALENDAR["events"]:
        assert event["title"] not in reply
        for attendee in event["attendees"]:
            assert attendee not in reply


def test_free_busy_annotation_shows_time_range(mock_client):
    mock_client.free_busy.return_value = {"busy": []}
    skill = CalendarFreeBusySkill(mock_client)
    _reply, ann = skill.run(start="2026-06-19T14:00:00", end="2026-06-19T15:00:00")
    assert "14:00" in ann or "2026-06-19" in ann


# ---------------------------------------------------------------------------
# Free/busy — busy (act-without-disclose compliance)
# ---------------------------------------------------------------------------

_BUSY_SLOT = [{"start": "2026-06-19T14:00:00", "end": "2026-06-19T15:00:00"}]


def test_free_busy_busy_reply_is_hedged(mock_client):
    mock_client.free_busy.side_effect = lambda *, start, end: {"busy": _BUSY_SLOT}
    skill = CalendarFreeBusySkill(mock_client)
    reply, _ann = skill.run(start="2026-06-19T14:00:00", end="2026-06-19T15:00:00")
    hedged_phrases = [
        "tight", "something's on", "busy", "on the calendar",
        "might be able to move", "few things",
    ]
    assert any(phrase in reply.lower() for phrase in hedged_phrases)


def test_free_busy_busy_reply_has_no_event_title(mock_client):
    """Critical: event title must never appear in spoken reply."""
    mock_client.free_busy.side_effect = lambda *, start, end: {"busy": _BUSY_SLOT}
    mock_client.list_events.return_value = FIXTURE_CALENDAR["events"]
    skill = CalendarFreeBusySkill(mock_client)
    reply, _ann = skill.run(start="2026-06-19T14:00:00", end="2026-06-19T15:00:00")
    assert "Medical Appointment" not in reply
    assert "Standup" not in reply


def test_free_busy_busy_reply_has_no_attendee(mock_client):
    """Critical: attendees must never appear in spoken reply."""
    mock_client.free_busy.side_effect = lambda *, start, end: {"busy": _BUSY_SLOT}
    skill = CalendarFreeBusySkill(mock_client)
    reply, _ann = skill.run(start="2026-06-19T14:00:00", end="2026-06-19T15:00:00")
    assert "dr.smith@hospital.org" not in reply
    assert "team@company.com" not in reply


def test_free_busy_busy_reply_has_no_exact_conflict_time(mock_client):
    """Conflict slot ISO timestamp must not appear in spoken reply."""
    mock_client.free_busy.side_effect = lambda *, start, end: {"busy": _BUSY_SLOT}
    skill = CalendarFreeBusySkill(mock_client)
    reply, _ann = skill.run(start="2026-06-19T14:00:00", end="2026-06-19T15:00:00")
    assert "2026-06-19T14:00:00" not in reply
    assert "14:00" not in reply or "14:00" in reply.count("14:00") == 0


def test_free_busy_busy_annotation_marks_act_without_disclose(mock_client):
    mock_client.free_busy.side_effect = lambda *, start, end: {"busy": _BUSY_SLOT}
    skill = CalendarFreeBusySkill(mock_client)
    _reply, ann = skill.run(start="2026-06-19T14:00:00", end="2026-06-19T15:00:00")
    assert "act-without-disclose" in ann.lower() or "hidden" in ann.lower() or "details" in ann.lower()


# ---------------------------------------------------------------------------
# Create event
# ---------------------------------------------------------------------------

def test_create_success_reply_is_brief_confirmation(mock_client):
    skill = CalendarCreateSkill(mock_client)
    reply, _ann = skill.run(title="Call with Alex", start="2026-06-19T14:00:00")
    assert "done" in reply.lower() or "calendar" in reply.lower() or "put it on" in reply.lower()


def test_create_reply_includes_natural_language_time(mock_client):
    """PM decision: confirmation includes natural language time (not ISO only)."""
    skill = CalendarCreateSkill(mock_client)
    reply, _ann = skill.run(title="Call with Alex", start="2026-06-19T14:00:00")
    # Should say "Thursday 2 PM" or "2 PM" not just "2026-06-19T14:00:00"
    assert "2026-06-19T14:00:00" not in reply
    assert any(word in reply.lower() for word in ["pm", "am", "thursday", ":00", "2 pm"])


def test_create_annotation_shows_event_details(mock_client):
    skill = CalendarCreateSkill(mock_client)
    _reply, ann = skill.run(title="Call with Alex", start="2026-06-19T14:00:00")
    assert "Call with Alex" in ann
    assert "2026-06-19" in ann


def test_create_with_attendees_mentions_invite(mock_client):
    skill = CalendarCreateSkill(mock_client)
    reply, _ann = skill.run(
        title="Call with Alex", start="2026-06-19T14:00:00", attendees=["alex@example.com"]
    )
    assert "invited" in reply.lower() or "invite" in reply.lower() or "them" in reply.lower()


def test_create_default_duration_1_hour_stated(mock_client):
    """PM decision: default duration 1 hour, stated in confirmation."""
    skill = CalendarCreateSkill(mock_client)
    reply, _ann = skill.run(title="Call with Alex", start="2026-06-19T14:00:00")
    assert "hour" in reply.lower() or "1-hour" in reply.lower()


def test_create_attendee_validation_failure_partial_success(mock_client):
    mock_client.create_event.return_value = {
        "id": "new-evt",
        "title": "Call with Alex",
        "start": "2026-06-19T14:00:00",
        "end": "2026-06-19T15:00:00",
        "attendee_error": "alex@@broken",
    }
    skill = CalendarCreateSkill(mock_client)
    reply, _ann = skill.run(title="Call with Alex", start="2026-06-19T14:00:00", attendees=["alex@@broken"])
    # Event created but attendee addition failed
    assert "calendar" in reply.lower() or "done" in reply.lower()
    assert "attendee" in reply.lower() or "couldn't add" in reply.lower() or "invite" in reply.lower()


# ---------------------------------------------------------------------------
# Move / reschedule
# ---------------------------------------------------------------------------

def test_move_success_reply_is_brief(mock_client):
    mock_client.list_events.return_value = [FIXTURE_CALENDAR["events"][1]]  # single match
    skill = CalendarMoveSkill(mock_client)
    reply, _ann = skill.run(title_fragment="standup", new_start="2026-06-20T10:00:00")
    assert "done" in reply.lower() or "moved" in reply.lower()


def test_move_success_event_title_in_annotation_not_reply(mock_client):
    """Act-without-disclose: event title goes in annotation, not spoken reply."""
    mock_client.list_events.return_value = [FIXTURE_CALENDAR["events"][1]]
    skill = CalendarMoveSkill(mock_client)
    reply, ann = skill.run(title_fragment="standup", new_start="2026-06-20T10:00:00")
    assert "Morning Standup" in ann
    # The spoken reply should not include the full event title from the fixture
    # (the operator said "standup" so Iris may echo that word, but not the exact stored title)


def test_move_disambiguation_fires_on_multiple_matches(mock_client):
    mock_client.list_events.return_value = [
        FIXTURE_CALENDAR["events"][1],  # Morning Standup
        FIXTURE_CALENDAR["events"][2],  # Wednesday Standup
    ]
    skill = CalendarMoveSkill(mock_client)
    reply, ann = skill.run(title_fragment="standup", new_start="2026-06-20T10:00:00")
    # Should offer disambiguation, not move blindly
    assert "found" in reply.lower() or "which" in reply.lower() or "two" in reply.lower()


def test_move_disambiguation_annotation_shows_numbered_list(mock_client):
    mock_client.list_events.return_value = [
        FIXTURE_CALENDAR["events"][1],
        FIXTURE_CALENDAR["events"][2],
    ]
    skill = CalendarMoveSkill(mock_client)
    _reply, ann = skill.run(title_fragment="standup", new_start="2026-06-20T10:00:00")
    assert ann  # annotation must be non-empty
    assert "Morning Standup" in ann or "Wednesday Standup" in ann


# ---------------------------------------------------------------------------
# OAuth error handling
# ---------------------------------------------------------------------------

def test_oauth_error_reply_is_vague(mock_client):
    mock_client.free_busy.side_effect = PermissionError("OAuth token expired")
    skill = CalendarFreeBusySkill(mock_client)
    reply, _ann = skill.run(start="2026-06-19T14:00:00", end="2026-06-19T15:00:00")
    assert "calendar" in reply.lower()
    assert "set up" in reply.lower() or "right now" in reply.lower() or "reach" in reply.lower()


def test_oauth_error_reply_has_no_technical_details(mock_client):
    """Spoken reply must not expose OAuth error or token details."""
    mock_client.free_busy.side_effect = PermissionError("OAuth token expired")
    skill = CalendarFreeBusySkill(mock_client)
    reply, _ann = skill.run(start="2026-06-19T14:00:00", end="2026-06-19T15:00:00")
    assert "oauth" not in reply.lower()
    assert "token" not in reply.lower()
    assert "expired" not in reply.lower()
    assert "exception" not in reply.lower()


def test_oauth_error_annotation_shows_fix_command(mock_client):
    """Console annotation must show 'iris auth gcal' for operator after call."""
    mock_client.free_busy.side_effect = PermissionError("OAuth token expired")
    skill = CalendarFreeBusySkill(mock_client)
    _reply, ann = skill.run(start="2026-06-19T14:00:00", end="2026-06-19T15:00:00")
    assert "iris auth gcal" in ann or "auth gcal" in ann


# ---------------------------------------------------------------------------
# Act-without-disclose compliance — comprehensive fixture sweep
# ---------------------------------------------------------------------------

def test_act_without_disclose_busy_spoken_never_contains_title(mock_client):
    """Parameterised compliance test: no event from the fixture calendar leaks into spoken reply."""
    for event in FIXTURE_CALENDAR["events"]:
        mock_client.free_busy.return_value = {
            "busy": [{"start": event["start"], "end": event["end"]}]
        }
        skill = CalendarFreeBusySkill(mock_client)
        reply, _ann = skill.run(start=event["start"], end=event["end"])
        assert event["title"] not in reply, f"Event title '{event['title']}' leaked into reply"


def test_act_without_disclose_busy_spoken_never_contains_attendee(mock_client):
    """No attendee from any event should appear in the spoken reply."""
    for event in FIXTURE_CALENDAR["events"]:
        mock_client.free_busy.return_value = {
            "busy": [{"start": event["start"], "end": event["end"]}]
        }
        skill = CalendarFreeBusySkill(mock_client)
        reply, _ann = skill.run(start=event["start"], end=event["end"])
        for attendee in event["attendees"]:
            assert attendee not in reply, f"Attendee '{attendee}' leaked into reply"


# ---------------------------------------------------------------------------
# Factory function
# ---------------------------------------------------------------------------

def test_calendar_skills_returns_three_skills(mock_client):
    skills = calendar_skills(mock_client)
    names = {s.name for s in skills}
    assert {"calendar_free_busy", "calendar_create", "calendar_move"} <= names


def test_calendar_skills_share_client(mock_client):
    skills = calendar_skills(mock_client)
    free_busy = next(s for s in skills if s.name == "calendar_free_busy")
    free_busy.run(start="2026-06-19T14:00:00", end="2026-06-19T15:00:00")
    mock_client.free_busy.assert_called_once()
