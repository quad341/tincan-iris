"""Tests for the dial skill (CallContactSkill) — Iris places outgoing calls.

No D-Bus daemon and no telephony hardware: TincanCallControl is a MagicMock spec
(no real call is placed) and the roster is the same in-memory stub the roster
skill tests use. Covers contact→number resolution, the dial invocation,
unknown-contact handling, and — importantly — the operator-only privilege gate
(placing a call must NEVER be reachable by the far party)."""
from __future__ import annotations

import time
from unittest.mock import MagicMock

from iris.call_control import TincanCallControl
from iris.dial_skill import (
    CallContactSkill,
    configured_dial_skills,
    dial_skills,
)
from iris.roster import Contact, ImportResult
from iris.skills import is_operator_only


# ---------------------------------------------------------------------------
# Minimal in-memory roster stub (same shape as test_roster_skill._StubRoster)
# ---------------------------------------------------------------------------

class _StubRoster:
    def __init__(self) -> None:
        self._contacts: list[Contact] = []
        self._next_id = 1

    def add(self, display_name, phone_e164, handling_rule="normal",
            trust_tier="demo", relationship_notes="") -> Contact:
        c = Contact(
            id=self._next_id,
            display_name=display_name,
            phone_e164=phone_e164,
            handling_rule=handling_rule,
            trust_tier=trust_tier,
            relationship_notes=relationship_notes,
            created_at=time.time(),
            updated_at=time.time(),
        )
        self._next_id += 1
        self._contacts.append(c)
        return c

    def get_by_phone(self, phone: str) -> Contact | None:
        return next((c for c in self._contacts if c.phone_e164 == phone), None)

    def get(self, contact_id: int) -> Contact | None:
        return next((c for c in self._contacts if c.id == contact_id), None)

    def all(self) -> list[Contact]:
        return list(self._contacts)

    def update(self, *a, **k) -> bool:
        return False

    def delete(self, contact_id: int) -> bool:
        return False

    def import_contacts(self, contacts) -> ImportResult:
        return ImportResult(added=0, skipped=0, conflicts=[])


def _skill(*, dial_result="call-1"):
    """CallContactSkill wired to a mock call client + a roster with Mom + Bob."""
    calls = MagicMock(spec=TincanCallControl)
    calls.dial.return_value = dial_result
    roster = _StubRoster()
    roster.add("Mom", "+15555550100")
    roster.add("Bob Smith", "+15555550111")
    return CallContactSkill(calls, roster), calls, roster


# ---------------------------------------------------------------------------
# Contact → number resolution + dial invocation
# ---------------------------------------------------------------------------

def test_call_resolves_name_to_number_and_dials():
    skill, calls, _ = _skill()
    reply = skill.run(contact="Mom", speaker="operator")
    calls.dial.assert_called_once_with("+15555550100")
    assert "Mom" in reply


def test_call_name_match_is_case_insensitive():
    skill, calls, _ = _skill()
    skill.run(contact="mom", speaker="operator")
    calls.dial.assert_called_once_with("+15555550100")


def test_call_partial_name_match():
    skill, calls, _ = _skill()
    skill.run(contact="Bob", speaker="operator")
    calls.dial.assert_called_once_with("+15555550111")


def test_call_dials_raw_e164_number_directly():
    skill, calls, _ = _skill()
    reply = skill.run(contact="+15555559999", speaker="operator")
    calls.dial.assert_called_once_with("+15555559999")
    assert "+15555559999" in reply


def test_call_dials_digits_only_number_directly():
    skill, calls, _ = _skill()
    skill.run(contact="5555559999", speaker="operator")
    calls.dial.assert_called_once_with("5555559999")


# ---------------------------------------------------------------------------
# Unknown / unusable contact handling
# ---------------------------------------------------------------------------

def test_call_unknown_contact_does_not_dial():
    skill, calls, _ = _skill()
    reply = skill.run(contact="Nobody", speaker="operator")
    assert "Nobody" in reply
    calls.dial.assert_not_called()


def test_call_ambiguous_name_asks_and_does_not_dial():
    skill, calls, roster = _skill()
    roster.add("Bob Jones", "+15555550222")  # second "Bob"
    reply = skill.run(contact="Bob", speaker="operator")
    assert "Bob" in reply
    calls.dial.assert_not_called()


def test_call_contact_without_number_does_not_dial():
    calls = MagicMock(spec=TincanCallControl)
    roster = _StubRoster()
    roster.add("Grandpa", None)  # phone_e164 is None
    skill = CallContactSkill(calls, roster)
    reply = skill.run(contact="Grandpa", speaker="operator")
    assert "Grandpa" in reply
    calls.dial.assert_not_called()


def test_call_empty_contact_prompts():
    skill, calls, _ = _skill()
    reply = skill.run(contact="", speaker="operator")
    assert "?" in reply
    calls.dial.assert_not_called()


def test_call_dial_failure_is_reported():
    skill, calls, _ = _skill(dial_result=None)  # dial() returns None on D-Bus error
    reply = skill.run(contact="Mom", speaker="operator")
    calls.dial.assert_called_once_with("+15555550100")
    assert "couldn't" in reply.lower() or "could not" in reply.lower()


# ---------------------------------------------------------------------------
# Operator-only privilege gate (NEVER the far party)
# ---------------------------------------------------------------------------

def test_skill_is_marked_operator_only():
    skill, _, _ = _skill()
    assert skill.operator_only is True
    assert is_operator_only(skill) is True


def test_far_party_cannot_dial_even_for_known_contact():
    skill, calls, _ = _skill()
    reply = skill.run(contact="Mom", speaker="far")
    calls.dial.assert_not_called()
    assert "operator" in reply.lower()


def test_far_party_cannot_dial_raw_number():
    skill, calls, _ = _skill()
    reply = skill.run(contact="+15555559999", speaker="far")
    calls.dial.assert_not_called()
    assert "operator" in reply.lower()


def test_default_speaker_is_operator():
    """Direct callers (no speaker kwarg) are treated as the operator."""
    skill, calls, _ = _skill()
    skill.run(contact="Mom")
    calls.dial.assert_called_once_with("+15555550100")


# ---------------------------------------------------------------------------
# Factories + tincand gating
# ---------------------------------------------------------------------------

def test_dial_skills_factory_returns_call_contact():
    calls = MagicMock(spec=TincanCallControl)
    roster = _StubRoster()
    names = {s.name for s in dial_skills(calls, roster)}
    assert "call_contact" in names


def test_configured_dial_skills_empty_without_call_control():
    assert configured_dial_skills(None, _StubRoster()) == []


def test_configured_dial_skills_empty_when_no_bus():
    # A call client that never connected to a bus can't dial → no skill offered.
    calls = TincanCallControl(_bus=None)
    assert configured_dial_skills(calls, _StubRoster()) == []


def test_configured_dial_skills_present_when_bus_connected():
    calls = TincanCallControl(_bus=MagicMock())
    skills = configured_dial_skills(calls, _StubRoster())
    assert {s.name for s in skills} == {"call_contact"}
