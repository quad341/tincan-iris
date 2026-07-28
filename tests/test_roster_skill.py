"""Tests for RosterVoiceSkills — roster voice command skills (ti-lda5)."""
from __future__ import annotations

import time

from iris.roster import Contact, ImportResult
from iris.roster_skill import (
    AddContactSkill,
    AddNoteSkill,
    CancelRosterSkill,
    ConfirmRosterSkill,
    EditHandlingRuleSkill,
    RemoveContactSkill,
    RosterVoiceSkills,
    UpdateNoteSkill,
    _find_by_name,
    _PendingState,
)

# ---------------------------------------------------------------------------
# Minimal in-memory roster stub
# ---------------------------------------------------------------------------

class _StubRoster:
    """Minimal in-memory roster satisfying RosterProvider."""

    def __init__(self) -> None:
        self._contacts: list[Contact] = []
        self._next_id = 1

    def _make(self, display_name, phone_e164, handling_rule="normal",
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
        return c

    def add(self, display_name, phone_e164, handling_rule="normal",
            trust_tier="demo", relationship_notes="") -> Contact:
        c = self._make(display_name, phone_e164, handling_rule, trust_tier, relationship_notes)
        self._contacts.append(c)
        return c

    def get_by_phone(self, phone: str) -> Contact | None:
        return next((c for c in self._contacts if c.phone_e164 == phone), None)

    def get(self, contact_id: int) -> Contact | None:
        return next((c for c in self._contacts if c.id == contact_id), None)

    def all(self) -> list[Contact]:
        return list(self._contacts)

    def update(self, contact_id, *, display_name=None, handling_rule=None,
               trust_tier=None, relationship_notes=None) -> bool:
        for c in self._contacts:
            if c.id == contact_id:
                if display_name is not None:
                    object.__setattr__(c, "display_name", display_name)
                if handling_rule is not None:
                    object.__setattr__(c, "handling_rule", handling_rule)
                if trust_tier is not None:
                    object.__setattr__(c, "trust_tier", trust_tier)
                if relationship_notes is not None:
                    object.__setattr__(c, "relationship_notes", relationship_notes)
                return True
        return False

    def delete(self, contact_id: int) -> bool:
        for i, c in enumerate(self._contacts):
            if c.id == contact_id:
                del self._contacts[i]
                return True
        return False

    def import_contacts(self, contacts) -> ImportResult:
        added = 0
        for d in contacts:
            self.add(d["display_name"], d["phone_e164"])
            added += 1
        return ImportResult(added=added, skipped=0, conflicts=[])


# ---------------------------------------------------------------------------
# _find_by_name helper
# ---------------------------------------------------------------------------

def test_find_by_name_returns_exact_match():
    r = _StubRoster()
    r.add("Alice Johnson", "+15550001")
    r.add("Bob Smith", "+15550002")
    assert len(_find_by_name(r, "Alice")) == 1


def test_find_by_name_case_insensitive():
    r = _StubRoster()
    r.add("Alice Johnson", "+15550001")
    assert len(_find_by_name(r, "alice johnson")) == 1


def test_find_by_name_multiple_matches():
    r = _StubRoster()
    r.add("Alice Johnson", "+15550001")
    r.add("Alice Smith", "+15550002")
    assert len(_find_by_name(r, "alice")) == 2


def test_find_by_name_not_found():
    r = _StubRoster()
    r.add("Bob", "+15550001")
    assert _find_by_name(r, "Charlie") == []


def test_find_by_name_empty_query():
    r = _StubRoster()
    r.add("Alice", "+15550001")
    assert _find_by_name(r, "") == []


# ---------------------------------------------------------------------------
# _PendingState
# ---------------------------------------------------------------------------

def test_pending_stage_returns_confirmation_prompt():
    p = _PendingState()
    result = p.stage("Do it. Is that right?", lambda: "done")
    assert result == "Do it. Is that right?"


def test_pending_confirm_executes_and_clears():
    p = _PendingState()
    executed: list[bool] = []
    p.stage("Confirm?", lambda: (executed.append(True), "done")[1])
    result = p.confirm()
    assert result == "done"
    assert len(executed) == 1
    assert not p.has_pending


def test_pending_confirm_when_empty():
    p = _PendingState()
    result = p.confirm()
    assert "nothing" in result.lower()


def test_pending_cancel_clears():
    p = _PendingState()
    p.stage("Confirm?", lambda: "done")
    result = p.cancel()
    assert "cancel" in result.lower()
    assert not p.has_pending


# ---------------------------------------------------------------------------
# AddContactSkill
# ---------------------------------------------------------------------------

def test_add_contact_stages_confirmation_prompt():
    r = _StubRoster()
    p = _PendingState()
    skill = AddContactSkill(r, p)
    result = skill.run(display_name="Carol", phone_e164="+15550010")
    assert "Carol" in result
    assert "+15550010" in result
    assert p.has_pending


def test_add_contact_confirm_adds_to_roster():
    r = _StubRoster()
    p = _PendingState()
    skill = AddContactSkill(r, p)
    skill.run(display_name="Carol", phone_e164="+15550010", handling_rule="vip")
    p.confirm()
    assert len(r.all()) == 1
    assert r.all()[0].display_name == "Carol"
    assert r.all()[0].handling_rule == "vip"


def test_add_contact_no_name():
    r = _StubRoster()
    p = _PendingState()
    skill = AddContactSkill(r, p)
    result = skill.run(display_name="", phone_e164="+15550010")
    assert not p.has_pending
    assert "name" in result.lower()


def test_add_contact_no_phone():
    r = _StubRoster()
    p = _PendingState()
    skill = AddContactSkill(r, p)
    result = skill.run(display_name="Dave", phone_e164="")
    assert not p.has_pending
    assert "Dave" in result


def test_add_contact_invalid_rule_defaults_to_normal():
    r = _StubRoster()
    p = _PendingState()
    skill = AddContactSkill(r, p)
    skill.run(display_name="Eve", phone_e164="+15550020", handling_rule="BOGUS")
    p.confirm()
    assert r.all()[0].handling_rule == "normal"


# ---------------------------------------------------------------------------
# EditHandlingRuleSkill
# ---------------------------------------------------------------------------

def test_edit_rule_stages_confirmation():
    r = _StubRoster()
    r.add("Alice", "+15550001")
    p = _PendingState()
    skill = EditHandlingRuleSkill(r, p)
    result = skill.run(contact_name="Alice", handling_rule="vip")
    assert "Alice" in result
    assert "vip" in result
    assert p.has_pending


def test_edit_rule_confirm_updates_roster():
    r = _StubRoster()
    r.add("Alice", "+15550001", handling_rule="normal")
    p = _PendingState()
    skill = EditHandlingRuleSkill(r, p)
    skill.run(contact_name="Alice", handling_rule="block")
    p.confirm()
    assert r.all()[0].handling_rule == "block"


def test_edit_rule_not_found():
    r = _StubRoster()
    p = _PendingState()
    skill = EditHandlingRuleSkill(r, p)
    result = skill.run(contact_name="Nobody", handling_rule="vip")
    assert "Nobody" in result
    assert not p.has_pending


def test_edit_rule_disambiguation():
    r = _StubRoster()
    r.add("Alice Johnson", "+15550001")
    r.add("Alice Smith", "+15550002")
    p = _PendingState()
    skill = EditHandlingRuleSkill(r, p)
    result = skill.run(contact_name="Alice", handling_rule="vip")
    assert "Alice Johnson" in result or "Alice Smith" in result
    assert not p.has_pending  # must NOT stage on ambiguous match


# ---------------------------------------------------------------------------
# AddNoteSkill
# ---------------------------------------------------------------------------

def test_add_note_stages_confirmation():
    r = _StubRoster()
    r.add("Bob", "+15550001")
    p = _PendingState()
    skill = AddNoteSkill(r, p)
    result = skill.run(contact_name="Bob", note_text="Prefers email over phone.")
    assert "Bob" in result
    assert p.has_pending


def test_add_note_confirm_appends_to_existing():
    r = _StubRoster()
    c = r.add("Bob", "+15550001", relationship_notes="Old note.")
    p = _PendingState()
    skill = AddNoteSkill(r, p)
    skill.run(contact_name="Bob", note_text="New line.")
    p.confirm()
    updated = r.get(c.id)
    assert "Old note." in updated.relationship_notes
    assert "New line." in updated.relationship_notes


def test_add_note_to_empty_existing():
    r = _StubRoster()
    c = r.add("Sam", "+15550003", relationship_notes="")
    p = _PendingState()
    skill = AddNoteSkill(r, p)
    skill.run(contact_name="Sam", note_text="First note.")
    p.confirm()
    assert r.get(c.id).relationship_notes == "First note."


def test_add_note_warns_near_limit():
    r = _StubRoster()
    r.add("Carol", "+15550001", relationship_notes="x" * 495)
    p = _PendingState()
    skill = AddNoteSkill(r, p)
    result = skill.run(contact_name="Carol", note_text="Extra info.")
    assert "limit" in result.lower() or "long" in result.lower()


def test_add_note_not_found():
    r = _StubRoster()
    p = _PendingState()
    result = AddNoteSkill(r, p).run(contact_name="Ghost", note_text="text")
    assert "Ghost" in result
    assert not p.has_pending


# ---------------------------------------------------------------------------
# UpdateNoteSkill
# ---------------------------------------------------------------------------

def test_update_note_stages_confirmation():
    r = _StubRoster()
    r.add("Dave", "+15550001", relationship_notes="Old notes.")
    p = _PendingState()
    skill = UpdateNoteSkill(r, p)
    result = skill.run(contact_name="Dave", note_text="Brand new notes.")
    assert "Dave" in result
    assert p.has_pending


def test_update_note_confirm_replaces_existing():
    r = _StubRoster()
    c = r.add("Dave", "+15550001", relationship_notes="Old notes.")
    p = _PendingState()
    skill = UpdateNoteSkill(r, p)
    skill.run(contact_name="Dave", note_text="Brand new notes.")
    p.confirm()
    assert r.get(c.id).relationship_notes == "Brand new notes."


def test_update_note_trims_at_600_chars():
    r = _StubRoster()
    c = r.add("Eve", "+15550001")
    p = _PendingState()
    skill = UpdateNoteSkill(r, p)
    long_text = "a" * 700
    skill.run(contact_name="Eve", note_text=long_text)
    p.confirm()
    assert len(r.get(c.id).relationship_notes) <= 600


def test_update_note_not_found():
    r = _StubRoster()
    p = _PendingState()
    result = UpdateNoteSkill(r, p).run(contact_name="Ghost", note_text="text")
    assert "Ghost" in result
    assert not p.has_pending


# ---------------------------------------------------------------------------
# RemoveContactSkill
# ---------------------------------------------------------------------------

def test_remove_contact_stages_confirmation():
    r = _StubRoster()
    r.add("Frank", "+15550001")
    p = _PendingState()
    skill = RemoveContactSkill(r, p)
    result = skill.run(contact_name="Frank")
    assert "Frank" in result
    assert p.has_pending


def test_remove_contact_confirm_deletes():
    r = _StubRoster()
    r.add("Frank", "+15550001")
    p = _PendingState()
    skill = RemoveContactSkill(r, p)
    skill.run(contact_name="Frank")
    p.confirm()
    assert r.all() == []


def test_remove_contact_not_found():
    r = _StubRoster()
    p = _PendingState()
    result = RemoveContactSkill(r, p).run(contact_name="Ghost")
    assert "Ghost" in result
    assert not p.has_pending


def test_remove_contact_disambiguation():
    r = _StubRoster()
    r.add("Alice Johnson", "+15550001")
    r.add("Alice Smith", "+15550002")
    p = _PendingState()
    result = RemoveContactSkill(r, p).run(contact_name="Alice")
    assert not p.has_pending
    assert "Alice" in result


# ---------------------------------------------------------------------------
# ConfirmRosterSkill / CancelRosterSkill
# ---------------------------------------------------------------------------

def test_confirm_skill_executes_pending():
    r = _StubRoster()
    p = _PendingState()
    add_skill = AddContactSkill(r, p)
    add_skill.run(display_name="Grace", phone_e164="+15550099")
    confirm_skill = ConfirmRosterSkill(p)
    result = confirm_skill.run()
    assert "Grace" in result
    assert len(r.all()) == 1


def test_cancel_skill_clears_pending():
    r = _StubRoster()
    p = _PendingState()
    add_skill = AddContactSkill(r, p)
    add_skill.run(display_name="Henry", phone_e164="+15550088")
    cancel_skill = CancelRosterSkill(p)
    cancel_skill.run()
    assert r.all() == []
    assert not p.has_pending


# ---------------------------------------------------------------------------
# RosterVoiceSkills factory
# ---------------------------------------------------------------------------

def test_factory_returns_all_skills():
    r = _StubRoster()
    rv = RosterVoiceSkills(r)
    skills = rv.skills()
    names = {s.name for s in skills}
    assert "roster_add_contact" in names
    assert "roster_edit_rule" in names
    assert "roster_add_note" in names
    assert "roster_update_note" in names
    assert "roster_remove_contact" in names
    assert "roster_confirm" in names
    assert "roster_cancel" in names


def test_factory_shares_pending_state():
    """Confirm and cancel must operate on the same pending state as add."""
    r = _StubRoster()
    rv = RosterVoiceSkills(r)
    skills_by_name = {s.name: s for s in rv.skills()}

    skills_by_name["roster_add_contact"].run(
        display_name="Iris", phone_e164="+15550001"
    )
    assert rv.pending.has_pending

    skills_by_name["roster_cancel"].run()
    assert not rv.pending.has_pending
    assert r.all() == []


def test_trust_tier_not_in_roster_skills():
    """Trust-tier commands must NOT be present in the voice skill set."""
    r = _StubRoster()
    rv = RosterVoiceSkills(r)
    names = {s.name for s in rv.skills()}
    assert not any("trust" in n for n in names)
