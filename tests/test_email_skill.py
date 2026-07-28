"""Tests for iris.email_skill — _resolve_email_via_roster + SendEmailSkill roster path."""
from __future__ import annotations

from unittest.mock import MagicMock

from iris.email_provider import EmailMessage, EmailProvider
from iris.email_skill import (
    CancelEmailSkill,
    ConfirmEmailSkill,
    ReadEmailSkill,
    SendEmailSkill,
    TriageEmailSkill,
    _EmailPendingState,
    _format_email_address,
    _format_sender,
    _format_subject,
    _resolve_email_via_roster,
    _spoken_list,
    _strip_html_artifacts,
    _TriageState,
    _truncate_body,
)
from iris.roster import Contact, ContactAddress, ContactWithAddresses

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _contact(name: str = "Alice") -> Contact:
    return Contact(id=1, display_name=name, phone_e164=None,
                   handling_rule="normal", trust_tier="demo",
                   relationship_notes="", created_at=0.0, updated_at=0.0)


def _cwa(name: str, addresses: list[ContactAddress]) -> ContactWithAddresses:
    return ContactWithAddresses(contact=_contact(name), addresses=addresses)


def _email_addr(value: str) -> ContactAddress:
    return ContactAddress(id=1, contact_id=1, channel="email", value=value,
                          label="", created_at=0.0)


def _phone_addr(value: str) -> ContactAddress:
    return ContactAddress(id=2, contact_id=1, channel="phone", value=value,
                          label="", created_at=0.0)


def _mock_provider(**kwargs):
    m = MagicMock(spec=EmailProvider)
    for attr, val in kwargs.items():
        getattr(m, attr).return_value = val
    return m


# ---------------------------------------------------------------------------
# _resolve_email_via_roster
# ---------------------------------------------------------------------------

def test_resolve_no_roster():
    assert _resolve_email_via_roster("Alice", None) == ("", "Alice")


def test_resolve_roster_search_returns_empty():
    roster = MagicMock()
    roster.search.return_value = []
    assert _resolve_email_via_roster("Alice", roster) == ("", "Alice")


def test_resolve_roster_has_email_address():
    roster = MagicMock()
    roster.search.return_value = [_cwa("Alice", [_email_addr("alice@example.com")])]
    addr, label = _resolve_email_via_roster("Alice", roster)
    assert addr == "alice@example.com"
    assert "Alice" in label
    assert "alice" in label  # spoken form includes the address


def test_resolve_roster_has_no_email_address():
    roster = MagicMock()
    roster.search.return_value = [_cwa("Alice", [_phone_addr("+12025550001")])]
    assert _resolve_email_via_roster("Alice", roster) == ("", "Alice")


def test_resolve_roster_without_search_attr():
    class NoSearchRoster:
        pass
    assert _resolve_email_via_roster("Alice", NoSearchRoster()) == ("", "Alice")


# ---------------------------------------------------------------------------
# SendEmailSkill.run with roster
# ---------------------------------------------------------------------------

def test_send_email_name_resolves_to_email():
    provider = _mock_provider(send=True)
    pending = _EmailPendingState()
    roster = MagicMock()
    roster.search.return_value = [_cwa("Alice", [_email_addr("alice@example.com")])]
    skill = SendEmailSkill(provider, pending, roster=roster)
    result = skill.run(to="Alice", subject="Hi", body="Hello there")
    assert "alice" in result.lower()
    assert "right" in result or "?" in result  # confirmation prompt staged


def test_send_email_name_not_found_returns_error():
    provider = _mock_provider(send=True)
    pending = _EmailPendingState()
    roster = MagicMock()
    roster.search.return_value = []
    skill = SendEmailSkill(provider, pending, roster=roster)
    result = skill.run(to="UnknownPerson", subject="Hi", body="Hello")
    assert "couldn't find" in result.lower() or "email address" in result.lower()


def test_send_email_explicit_address_bypasses_roster():
    provider = _mock_provider(send=True)
    pending = _EmailPendingState()
    roster = MagicMock()
    skill = SendEmailSkill(provider, pending, roster=roster)
    result = skill.run(to="alice@example.com", subject="Hi", body="Hello")
    roster.search.assert_not_called()
    assert "right" in result or "?" in result  # staged confirmation, not error


# ---------------------------------------------------------------------------
# EmailMessage fixture helper
# ---------------------------------------------------------------------------

def _msg(
    id: str = "1",
    subject: str = "Test subject",
    sender_name: str = "Alice",
    sender_email: str = "alice@example.com",
    date: str = "Mon, 1 Jan 2024 10:00:00 +0000",
    body_text: str = "Hello world",
) -> EmailMessage:
    return EmailMessage(
        id=id, subject=subject, sender_name=sender_name,
        sender_email=sender_email, date=date, body_text=body_text, unread=True,
    )


# ---------------------------------------------------------------------------
# Pure formatting helpers
# ---------------------------------------------------------------------------

def test_format_email_address_with_at():
    assert _format_email_address("alice@example.com") == "alice at example dot com"


def test_format_email_address_no_at():
    assert _format_email_address("Alice") == "Alice"


def test_format_sender_with_distinct_name():
    assert _format_sender("Alice", "alice@example.com") == "Alice"


def test_format_sender_no_name_falls_back_to_spoken_email():
    result = _format_sender("", "alice@example.com")
    assert "alice" in result and "example" in result


def test_format_sender_name_equals_email_gives_spoken_email():
    result = _format_sender("alice@example.com", "alice@example.com")
    assert "at" in result  # spoken form, not raw address


def test_format_subject_short_unchanged():
    assert _format_subject("Hello") == "Hello"


def test_format_subject_exactly_60_unchanged():
    s = "A" * 60
    assert _format_subject(s) == s


def test_format_subject_over_60_truncated_with_ellipsis():
    result = _format_subject("A" * 80)
    assert result.endswith("…")
    assert len(result) == 61  # 60 chars + ellipsis character


def test_truncate_body_under_limit_unchanged():
    text = " ".join(["word"] * 10)
    assert _truncate_body(text) == text


def test_truncate_body_over_200_words_appends_ellipsis():
    text = " ".join(["word"] * 250)
    result = _truncate_body(text)
    assert result.endswith("…")
    assert len(result.split()) <= 201  # 200 word chunks + possibly trailing "…"


def test_strip_html_artifacts_removes_tag_patterns():
    assert _strip_html_artifacts("Hello <br> world") == "Hello  world"


def test_strip_html_artifacts_no_tags_unchanged():
    assert _strip_html_artifacts("Hello world") == "Hello world"


# ---------------------------------------------------------------------------
# _spoken_list
# ---------------------------------------------------------------------------

def test_spoken_list_empty():
    assert _spoken_list([]) == "No unread emails."


def test_spoken_list_one_message_uses_ordinal():
    result = _spoken_list([_msg()])
    assert "One" in result
    assert "1 unread email" in result


def test_spoken_list_five_messages_count_and_ordinals():
    msgs = [_msg(id=str(i), subject=f"Msg {i}") for i in range(5)]
    result = _spoken_list(msgs)
    assert "5 unread emails" in result
    assert "One" in result
    assert "Five" in result


def test_spoken_list_long_subject_truncated():
    msg = _msg(subject="A" * 100)
    result = _spoken_list([msg])
    assert "…" in result


def test_spoken_list_uses_sender_name_when_available():
    msg = _msg(sender_name="Alice", sender_email="alice@example.com")
    assert "Alice" in _spoken_list([msg])


# ---------------------------------------------------------------------------
# _EmailPendingState
# ---------------------------------------------------------------------------

def test_pending_state_stage_returns_prompt():
    ps = _EmailPendingState()
    assert ps.stage("Send this?", lambda: True) == "Send this?"


def test_pending_state_confirm_executes_fn():
    calls = []
    ps = _EmailPendingState()
    ps.stage("Send?", lambda: (calls.append(1) or True))
    ps.confirm()
    assert len(calls) == 1


def test_pending_state_confirm_clears_pending():
    ps = _EmailPendingState()
    ps.stage("Send?", lambda: True)
    ps.confirm()
    assert ps.confirm() == "Nothing to confirm."


def test_pending_state_confirm_nothing_pending():
    assert _EmailPendingState().confirm() == "Nothing to confirm."


def test_pending_state_confirm_success_message():
    ps = _EmailPendingState()
    ps.stage("Send?", lambda: True)
    assert "sent" in ps.confirm().lower()


def test_pending_state_confirm_failure_message():
    ps = _EmailPendingState()
    ps.stage("Send?", lambda: False)
    assert "couldn't" in ps.confirm().lower()


def test_pending_state_cancel_returns_cancelled():
    ps = _EmailPendingState()
    ps.stage("Send?", lambda: True)
    result = ps.cancel()
    assert "cancel" in result.lower()
    assert ps.confirm() == "Nothing to confirm."


# ---------------------------------------------------------------------------
# ReadEmailSkill.run
# ---------------------------------------------------------------------------

def test_read_skill_list_unread_empty_inbox():
    skill = ReadEmailSkill(_mock_provider(list_unread=[]), _TriageState())
    assert "no unread" in skill.run(action="list_unread").lower()


def test_read_skill_list_unread_one_message():
    skill = ReadEmailSkill(_mock_provider(list_unread=[_msg()]), _TriageState())
    result = skill.run(action="list_unread")
    assert "1 unread email" in result


def test_read_skill_list_unread_five_messages():
    msgs = [_msg(id=str(i)) for i in range(5)]
    skill = ReadEmailSkill(_mock_provider(list_unread=msgs), _TriageState())
    assert "5 unread emails" in skill.run(action="list_unread")


def test_read_skill_list_unread_stores_inbox_ids():
    triage = _TriageState()
    skill = ReadEmailSkill(_mock_provider(list_unread=[_msg(id="42")]), triage)
    skill.run(action="list_unread")
    assert triage.inbox_ids == ["42"]


def test_read_skill_read_message_with_explicit_id():
    msg = _msg(id="42", body_text="Hello there")
    skill = ReadEmailSkill(_mock_provider(get_message=msg), _TriageState())
    result = skill.run(action="read_message", message_id="42")
    assert "Hello there" in result


def test_read_skill_read_message_fallback_to_inbox_id():
    msg = _msg(id="1")
    provider = _mock_provider(get_message=msg)
    triage = _TriageState()
    triage.inbox_ids = ["1"]
    skill = ReadEmailSkill(provider, triage)
    skill.run(action="read_message", message_id="")
    provider.get_message.assert_called_once_with("1")


def test_read_skill_read_message_empty_uid_no_inbox():
    skill = ReadEmailSkill(_mock_provider(), _TriageState())
    result = skill.run(action="read_message", message_id="")
    assert "which email" in result.lower()


def test_read_skill_read_message_sets_triage_current_id():
    msg = _msg(id="99")
    triage = _TriageState()
    skill = ReadEmailSkill(_mock_provider(get_message=msg), triage)
    skill.run(action="read_message", message_id="99")
    assert triage.current_id == "99"


# ---------------------------------------------------------------------------
# SendEmailSkill.run — missing fields
# ---------------------------------------------------------------------------

def test_send_skill_missing_to_returns_error():
    skill = SendEmailSkill(_mock_provider(), _EmailPendingState())
    result = skill.run(to="", subject="Hi", body="Hello")
    assert "need" in result.lower()


def test_send_skill_missing_subject_returns_error():
    skill = SendEmailSkill(_mock_provider(), _EmailPendingState())
    result = skill.run(to="alice@example.com", subject="", body="Hello")
    assert "need" in result.lower()


def test_send_skill_missing_body_returns_error():
    skill = SendEmailSkill(_mock_provider(), _EmailPendingState())
    result = skill.run(to="alice@example.com", subject="Hi", body="")
    assert "need" in result.lower()


def test_send_skill_explicit_address_stages_confirmation():
    skill = SendEmailSkill(_mock_provider(send=True), _EmailPendingState())
    result = skill.run(to="alice@example.com", subject="Hi", body="Hello there")
    assert "right" in result or "?" in result


# ---------------------------------------------------------------------------
# ConfirmEmailSkill.run
# ---------------------------------------------------------------------------

def test_confirm_skill_nothing_pending():
    assert ConfirmEmailSkill(_EmailPendingState()).run() == "Nothing to confirm."


def test_confirm_skill_sends_and_reports_success():
    provider = _mock_provider(send=True)
    pending = _EmailPendingState()
    SendEmailSkill(provider, pending).run(to="a@b.com", subject="Hi", body="Hello")
    assert "sent" in ConfirmEmailSkill(pending).run().lower()


def test_confirm_skill_reports_failure_when_send_returns_false():
    provider = _mock_provider(send=False)
    pending = _EmailPendingState()
    SendEmailSkill(provider, pending).run(to="a@b.com", subject="Hi", body="Hello")
    assert "couldn't" in ConfirmEmailSkill(pending).run().lower()


# ---------------------------------------------------------------------------
# CancelEmailSkill.run
# ---------------------------------------------------------------------------

def test_cancel_skill_cancels_pending():
    provider = _mock_provider(send=True)
    pending = _EmailPendingState()
    SendEmailSkill(provider, pending).run(to="a@b.com", subject="Hi", body="Hello")
    result = CancelEmailSkill(pending).run()
    assert "cancel" in result.lower()
    assert pending.confirm() == "Nothing to confirm."


def test_cancel_skill_nothing_pending_returns_cancelled():
    result = CancelEmailSkill(_EmailPendingState()).run()
    assert "cancel" in result.lower()


# ---------------------------------------------------------------------------
# TriageEmailSkill.run
# ---------------------------------------------------------------------------

def _triage_skill(*, mark_read=None, archive=None):
    kwargs = {}
    if mark_read is not None:
        kwargs["mark_read"] = mark_read
    if archive is not None:
        kwargs["archive"] = archive
    provider = _mock_provider(**kwargs)
    triage = _TriageState()
    triage.current_id = "42"
    return TriageEmailSkill(provider, triage), triage


def test_triage_skill_mark_read_success():
    skill, _ = _triage_skill(mark_read=True)
    result = skill.run(action="mark_read")
    assert "marked" in result.lower() or "read" in result.lower()


def test_triage_skill_archive_success():
    skill, _ = _triage_skill(archive=True)
    assert "archived" in skill.run(action="archive").lower()


def test_triage_skill_archive_clears_current_id():
    skill, triage = _triage_skill(archive=True)
    skill.run(action="archive")
    assert triage.current_id == ""


def test_triage_skill_flag_is_noop():
    skill, _ = _triage_skill()
    result = skill.run(action="flag")
    assert "not available" in result.lower()


def test_triage_skill_missing_uid_returns_prompt():
    provider = _mock_provider()
    skill = TriageEmailSkill(provider, _TriageState())  # current_id="" and no message_id
    result = skill.run(action="mark_read", message_id="")
    assert "which email" in result.lower()
