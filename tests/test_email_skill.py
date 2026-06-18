"""Tests for iris.email_skill — _resolve_email_via_roster + SendEmailSkill roster path."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from iris.email_skill import SendEmailSkill, _EmailPendingState, _resolve_email_via_roster
from iris.email_provider import EmailProvider
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
