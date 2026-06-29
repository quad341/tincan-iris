"""Unit tests for iris/dial_skill.py (ti-vai5.3.1).

Covers: _DialState, DialSkill, ConfirmDialSkill, CancelDialSkill, DialVoiceSkills.
No D-Bus, no real roster — roster is a minimal in-memory stub; ctrl is a MagicMock.
"""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch


from iris.dial_skill import (
    CancelDialSkill,
    ConfirmDialSkill,
    DialSkill,
    DialVoiceSkills,
    _DialState,
)
from iris.roster import Contact


# ---------------------------------------------------------------------------
# Minimal roster stub
# ---------------------------------------------------------------------------

class _StubRoster:
    def __init__(self) -> None:
        self._contacts: list[Contact] = []
        self._next_id = 1

    def add(self, display_name: str, phone_e164: str) -> Contact:
        c = Contact(
            id=self._next_id,
            display_name=display_name,
            phone_e164=phone_e164,
            handling_rule="normal",
            trust_tier="demo",
            relationship_notes="",
            created_at=0.0,
            updated_at=0.0,
        )
        self._next_id += 1
        self._contacts.append(c)
        return c

    def all(self) -> list[Contact]:
        return list(self._contacts)

    # RosterProvider stubs not needed by DialSkill:
    def get_by_phone(self, phone: str) -> Contact | None: ...
    def get(self, cid: int) -> Contact | None: ...
    def update(self, *a, **kw) -> bool: return False
    def delete(self, cid: int) -> bool: return False
    def import_contacts(self, contacts) -> object: ...  # type: ignore[return]


# ---------------------------------------------------------------------------
# _DialState
# ---------------------------------------------------------------------------

def test_dial_state_initially_has_no_pending():
    s = _DialState()
    assert not s.has_pending


def test_dial_state_stage_makes_pending():
    s = _DialState()
    s.stage("Alice", "+15550001")
    assert s.has_pending


def test_dial_state_pop_returns_name_and_number():
    s = _DialState()
    s.stage("Alice", "+15550001")
    name, number = s.pop()
    assert name == "Alice"
    assert number == "+15550001"


def test_dial_state_pop_clears_pending():
    s = _DialState()
    s.stage("Alice", "+15550001")
    s.pop()
    assert not s.has_pending


def test_dial_state_clear_removes_pending():
    s = _DialState()
    s.stage("Bob", "+15550002")
    s.clear()
    assert not s.has_pending


def test_dial_state_clear_then_pop_returns_empty():
    s = _DialState()
    s.stage("Bob", "+15550002")
    s.clear()
    name, number = s.pop()
    assert name == "" and number == ""


# ---------------------------------------------------------------------------
# DialSkill
# ---------------------------------------------------------------------------

def _dial_skill(roster=None):
    return DialSkill(roster or _StubRoster(), _DialState())


def test_dial_skill_far_speaker_returns_none():
    r = _StubRoster()
    r.add("Alice", "+15550001")
    skill = _dial_skill(r)
    assert skill.run(contact_name="Alice", speaker="far") is None


def test_dial_skill_unknown_speaker_does_not_block():
    r = _StubRoster()
    r.add("Alice", "+15550001")
    skill = DialSkill(r, _DialState())
    result = skill.run(contact_name="Alice", speaker="")
    assert result is not None and "Alice" in result


def test_dial_skill_zero_matches_returns_not_found():
    skill = _dial_skill()
    result = skill.run(contact_name="Charlie", speaker="operator")
    assert result is not None
    assert "Charlie" in result
    assert "don't have" in result.lower() or "no contact" in result.lower()


def test_dial_skill_multiple_matches_returns_disambiguation():
    r = _StubRoster()
    r.add("Alice Johnson", "+15550001")
    r.add("Alice Smith", "+15550002")
    r.add("Alice Cooper", "+15550003")
    skill = DialSkill(r, _DialState())
    result = skill.run(contact_name="Alice", speaker="operator")
    assert result is not None
    assert "3" in result or "three" in result.lower() or "found" in result.lower()


def test_dial_skill_one_match_stages_and_returns_prompt():
    r = _StubRoster()
    r.add("Alice", "+15550001")
    pending = _DialState()
    skill = DialSkill(r, pending)
    result = skill.run(contact_name="Alice", speaker="operator")
    assert result is not None
    assert "Alice" in result
    assert "+15550001" in result
    assert pending.has_pending


def test_dial_skill_one_match_prompt_asks_to_confirm():
    r = _StubRoster()
    r.add("Alice", "+15550001")
    skill = DialSkill(r, _DialState())
    result = skill.run(contact_name="Alice", speaker="operator")
    assert result is not None
    assert "?" in result or "shall" in result.lower() or "dial" in result.lower()


# ---------------------------------------------------------------------------
# ConfirmDialSkill
# ---------------------------------------------------------------------------

def _confirm_skill(pending=None, connected=None, ctrl=None):
    ctrl = ctrl or MagicMock()
    ctrl.dial.return_value = None
    pending = pending or _DialState()
    connected = connected or threading.Event()
    return ConfirmDialSkill(ctrl, pending, connected), ctrl, pending, connected


def test_confirm_skill_no_pending_returns_nothing_to_confirm():
    skill, _, _, _ = _confirm_skill()
    assert skill.run() == "Nothing to confirm."


def test_confirm_skill_dial_error_returns_failure_phrase():
    ctrl = MagicMock()
    ctrl.dial.return_value = "D-Bus error"
    pending = _DialState()
    pending.stage("Alice", "+15550001")
    skill = ConfirmDialSkill(ctrl, pending, threading.Event())
    result = skill.run()
    assert result is not None
    assert "couldn't" in result.lower() or "failed" in result.lower()


def test_confirm_skill_connected_event_returns_none():
    ctrl = MagicMock()
    ctrl.dial.return_value = None
    pending = _DialState()
    pending.stage("Alice", "+15550001")
    connected = threading.Event()
    skill = ConfirmDialSkill(ctrl, pending, connected)

    def _connect_after_delay():
        time.sleep(0.05)
        connected.set()

    t = threading.Thread(target=_connect_after_delay, daemon=True)
    t.start()
    result = skill.run()
    t.join(timeout=1)
    assert result is None


def test_confirm_skill_timeout_returns_failure_phrase():
    ctrl = MagicMock()
    ctrl.dial.return_value = None
    pending = _DialState()
    pending.stage("Alice", "+15550001")
    connected = threading.Event()  # never set
    skill = ConfirmDialSkill(ctrl, pending, connected)

    with patch("iris.dial_skill._DIAL_TIMEOUT_S", 0.01):
        result = skill.run()

    assert result is not None
    assert "couldn't" in result.lower() or "failed" in result.lower()


def test_confirm_skill_pops_pending_before_dialing():
    ctrl = MagicMock()
    ctrl.dial.return_value = "err"
    pending = _DialState()
    pending.stage("Alice", "+15550001")
    skill = ConfirmDialSkill(ctrl, pending, threading.Event())
    skill.run()
    assert not pending.has_pending


def test_confirm_skill_clears_event_before_dialing():
    ctrl = MagicMock()
    ctrl.dial.return_value = None
    pending = _DialState()
    pending.stage("Alice", "+15550001")
    connected = threading.Event()
    connected.set()  # pre-set from a previous call
    skill = ConfirmDialSkill(ctrl, pending, connected)

    with patch("iris.dial_skill._DIAL_TIMEOUT_S", 0.01):
        result = skill.run()
    # Event was cleared before dial; no signal arrived → timeout
    assert result is not None


# ---------------------------------------------------------------------------
# CancelDialSkill
# ---------------------------------------------------------------------------

def test_cancel_skill_clears_pending():
    pending = _DialState()
    pending.stage("Alice", "+15550001")
    skill = CancelDialSkill(pending)
    skill.run()
    assert not pending.has_pending


def test_cancel_skill_returns_skip_phrase():
    pending = _DialState()
    pending.stage("Alice", "+15550001")
    skill = CancelDialSkill(pending)
    result = skill.run()
    assert "skip" in result.lower() or "ok" in result.lower()


def test_cancel_skill_no_pending_still_succeeds():
    skill = CancelDialSkill(_DialState())
    result = skill.run()
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# DialVoiceSkills
# ---------------------------------------------------------------------------

def test_dial_voice_skills_returns_three_skills():
    ctrl = MagicMock()
    ctrl.emit = MagicMock()
    roster = _StubRoster()
    dvs = DialVoiceSkills(ctrl, roster)
    skills = dvs.skills()
    names = {s.name for s in skills}
    assert names == {"dial_contact", "dial_confirm", "dial_cancel"}


def test_dial_voice_skills_intercepts_call_connected():
    events: list = []
    ctrl = MagicMock()
    ctrl.emit = events.append
    dvs = DialVoiceSkills(ctrl, _StubRoster())
    ctrl.emit(("call_connected", "sink", "src"))
    assert dvs._connected.is_set()


def test_dial_voice_skills_passes_other_events_through():
    events: list = []
    ctrl = MagicMock()
    ctrl.emit = events.append
    DialVoiceSkills(ctrl, _StubRoster())
    ctrl.emit(("call_ended", "id-1"))
    assert ("call_ended", "id-1") in events


def test_dial_voice_skills_does_not_set_event_for_non_connected():
    ctrl = MagicMock()
    ctrl.emit = MagicMock()
    dvs = DialVoiceSkills(ctrl, _StubRoster())
    ctrl.emit(("incoming_call", "Alice", "+15550001"))
    assert not dvs._connected.is_set()


def test_dial_voice_skills_all_skills_are_operator_only():
    ctrl = MagicMock()
    ctrl.emit = MagicMock()
    dvs = DialVoiceSkills(ctrl, _StubRoster())
    for skill in dvs.skills():
        assert getattr(skill, "operator_only", False), f"{skill.name} should be operator_only"
