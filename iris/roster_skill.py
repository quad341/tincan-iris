"""Roster voice-command skills — ti-lda5.

All roster-mutating operations use a two-phase confirmation protocol:

  Phase 1 — skill.run(**kwargs) stages a pending write and returns a spoken
             confirmation prompt ("Add Alice at 555-1234 with normal handling.
             Is that right?").

  Phase 2 — if the user confirms ("yes", "correct", etc.), the brain dispatches
             ConfirmRosterSkill.run().  If the user cancels, CancelRosterSkill
             clears the pending state.

Name matching uses case-insensitive substring search over all contacts.
Ambiguous matches (>1 hit) return a disambiguation prompt without staging.
Not-found returns a spoken not-found response without staging.

Trust-tier commands are NOT implemented here — voice must never set trust/privilege
(no-audio-admin principle; see bead ti-lda5 notes).
"""
from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

from .roster import Contact, RosterProvider
from .skills import Skill, SkillParam

_HANDLING_RULES = ["normal", "vip", "screen", "take_message", "block"]
_NOTES_MAX_CHARS = 600
_NOTES_WARN_CHARS = 500


# ---------------------------------------------------------------------------
# Helper — name search
# ---------------------------------------------------------------------------

def _find_by_name(roster: RosterProvider, name: str) -> list[Contact]:
    """Return contacts whose display_name contains `name` (case-insensitive)."""
    needle = name.strip().lower()
    if not needle:
        return []
    return [c for c in roster.all() if needle in c.display_name.lower()]


def _format_contact(c: Contact) -> str:
    return f"{c.display_name} at {c.phone_e164}"


def _disambiguate(matches: list[Contact]) -> str:
    options = "; or ".join(_format_contact(c) for c in matches[:3])
    return f"I found a few contacts with that name. Do you mean {options}?"


def _not_found(name: str) -> str:
    return f"I don't have a contact named {name}."


# ---------------------------------------------------------------------------
# Shared pending-action state
# ---------------------------------------------------------------------------

class _PendingState:
    """Mutable holder for a staged mutating action shared across skill instances."""

    def __init__(self) -> None:
        self._pending: tuple[str, Callable[[], str]] | None = None

    def stage(self, confirmation_prompt: str, execute: Callable[[], str]) -> str:
        self._pending = (confirmation_prompt, execute)
        return confirmation_prompt

    def confirm(self) -> str:
        if self._pending is None:
            return "Nothing to confirm."
        _, fn = self._pending
        self._pending = None
        return fn()

    def cancel(self) -> str:
        self._pending = None
        return "Okay — cancelled."

    @property
    def has_pending(self) -> bool:
        return self._pending is not None


# ---------------------------------------------------------------------------
# Individual skills
# ---------------------------------------------------------------------------

class AddContactSkill:
    """Add a new contact to the roster."""

    name = "roster_add_contact"
    description = (
        "Add a new contact to the roster with a display name, phone number, "
        "and optional handling rule."
    )
    params: ClassVar[list[SkillParam]] = [
        SkillParam(
            name="display_name",
            type="string",
            description="Full name of the new contact.",
        ),
        SkillParam(
            name="phone_e164",
            type="string",
            description="Phone number in E.164 format, e.g. +15555550100.",
        ),
        SkillParam(
            name="handling_rule",
            type="string",
            description="How to handle calls from this contact.",
            required=False,
            default="normal",
            enum=_HANDLING_RULES,
        ),
    ]

    def __init__(self, roster: RosterProvider, pending: _PendingState) -> None:
        self._roster = roster
        self._pending = pending

    def run(
        self,
        display_name: str = "",
        phone_e164: str = "",
        handling_rule: str = "normal",
        **_: object,
    ) -> str:
        if not display_name:
            return "I need a name to add a contact."
        if not phone_e164:
            return f"What's {display_name}'s phone number?"
        rule = handling_rule if handling_rule in _HANDLING_RULES else "normal"
        prompt = (
            f"Add {display_name} at {phone_e164} with {rule} handling. Is that right?"
        )
        return self._pending.stage(
            prompt,
            lambda: _execute_add(self._roster, display_name, phone_e164, rule),
        )


def _execute_add(
    roster: RosterProvider, display_name: str, phone_e164: str, rule: str
) -> str:
    contact = roster.add(display_name, phone_e164, handling_rule=rule)
    return f"Done — I've added {contact.display_name} to your contacts."


class EditHandlingRuleSkill:
    """Change the handling rule for an existing contact."""

    name = "roster_edit_rule"
    description = "Change how Iris handles calls from a contact (normal, vip, screen, take_message, block)."
    params: ClassVar[list[SkillParam]] = [
        SkillParam(
            name="contact_name",
            type="string",
            description="Name of the contact to edit.",
        ),
        SkillParam(
            name="handling_rule",
            type="string",
            description="New handling rule.",
            enum=_HANDLING_RULES,
        ),
    ]

    def __init__(self, roster: RosterProvider, pending: _PendingState) -> None:
        self._roster = roster
        self._pending = pending

    def run(
        self,
        contact_name: str = "",
        handling_rule: str = "normal",
        **_: object,
    ) -> str:
        matches = _find_by_name(self._roster, contact_name)
        if not matches:
            return _not_found(contact_name)
        if len(matches) > 1:
            return _disambiguate(matches)
        contact = matches[0]
        rule = handling_rule if handling_rule in _HANDLING_RULES else "normal"
        prompt = f"Change {contact.display_name}'s handling to {rule}. Is that right?"
        return self._pending.stage(
            prompt,
            lambda cid=contact.id: _execute_edit_rule(self._roster, cid, rule, contact.display_name),
        )


def _execute_edit_rule(
    roster: RosterProvider, contact_id: int, rule: str, display_name: str
) -> str:
    roster.update(contact_id, handling_rule=rule)
    return f"Done — {display_name}'s handling is now set to {rule}."


class AddNoteSkill:
    """Append text to a contact's relationship notes."""

    name = "roster_add_note"
    description = "Append a note to a contact's relationship notes."
    params: ClassVar[list[SkillParam]] = [
        SkillParam(
            name="contact_name",
            type="string",
            description="Name of the contact.",
        ),
        SkillParam(
            name="note_text",
            type="string",
            description="Text to append.",
        ),
    ]

    def __init__(self, roster: RosterProvider, pending: _PendingState) -> None:
        self._roster = roster
        self._pending = pending

    def run(
        self,
        contact_name: str = "",
        note_text: str = "",
        **_: object,
    ) -> str:
        if not note_text:
            return "What would you like to add to the note?"
        matches = _find_by_name(self._roster, contact_name)
        if not matches:
            return _not_found(contact_name)
        if len(matches) > 1:
            return _disambiguate(matches)
        contact = matches[0]
        existing = contact.relationship_notes or ""
        combined = (f"{existing}\n{note_text}" if existing else note_text).strip()
        if len(combined) > _NOTES_MAX_CHARS:
            combined = combined[:_NOTES_MAX_CHARS]
        warning = (
            " Note: that'll be getting close to the 600-character limit."
            if len(combined) >= _NOTES_WARN_CHARS
            else ""
        )
        preview = note_text[:60] + "…" if len(note_text) > 60 else note_text
        prompt = f"Add to {contact.display_name}'s notes: \"{preview}\".{warning} Is that right?"
        return self._pending.stage(
            prompt,
            lambda cid=contact.id: _execute_update_notes(
                self._roster, cid, combined, contact.display_name, "added to"
            ),
        )


class UpdateNoteSkill:
    """Replace a contact's relationship notes entirely."""

    name = "roster_update_note"
    description = "Replace a contact's relationship notes entirely."
    params: ClassVar[list[SkillParam]] = [
        SkillParam(
            name="contact_name",
            type="string",
            description="Name of the contact.",
        ),
        SkillParam(
            name="note_text",
            type="string",
            description="New note text (replaces existing notes).",
        ),
    ]

    def __init__(self, roster: RosterProvider, pending: _PendingState) -> None:
        self._roster = roster
        self._pending = pending

    def run(
        self,
        contact_name: str = "",
        note_text: str = "",
        **_: object,
    ) -> str:
        if not note_text:
            return "What should the new note say?"
        matches = _find_by_name(self._roster, contact_name)
        if not matches:
            return _not_found(contact_name)
        if len(matches) > 1:
            return _disambiguate(matches)
        contact = matches[0]
        trimmed = note_text[:_NOTES_MAX_CHARS]
        warning = (
            " That's approaching the 600-character limit, so I'll trim it slightly."
            if len(note_text) > _NOTES_MAX_CHARS
            else ""
        )
        preview = trimmed[:60] + "…" if len(trimmed) > 60 else trimmed
        prompt = (
            f"Replace {contact.display_name}'s notes with: \"{preview}\".{warning} Is that right?"
        )
        return self._pending.stage(
            prompt,
            lambda cid=contact.id: _execute_update_notes(
                self._roster, cid, trimmed, contact.display_name, "updated"
            ),
        )


def _execute_update_notes(
    roster: RosterProvider, contact_id: int, notes: str, display_name: str, verb: str
) -> str:
    roster.update(contact_id, relationship_notes=notes)
    return f"Done — I've {verb} {display_name}'s notes."


class RemoveContactSkill:
    """Remove a contact from the roster permanently."""

    name = "roster_remove_contact"
    description = "Permanently remove a contact from the roster."
    params: ClassVar[list[SkillParam]] = [
        SkillParam(
            name="contact_name",
            type="string",
            description="Name of the contact to remove.",
        ),
    ]

    def __init__(self, roster: RosterProvider, pending: _PendingState) -> None:
        self._roster = roster
        self._pending = pending

    def run(self, contact_name: str = "", **_: object) -> str:
        matches = _find_by_name(self._roster, contact_name)
        if not matches:
            return _not_found(contact_name)
        if len(matches) > 1:
            return _disambiguate(matches)
        contact = matches[0]
        prompt = f"Remove {contact.display_name} from your contacts. Are you sure?"
        return self._pending.stage(
            prompt,
            lambda cid=contact.id: _execute_remove(self._roster, cid, contact.display_name),
        )


def _execute_remove(
    roster: RosterProvider, contact_id: int, display_name: str
) -> str:
    roster.delete(contact_id)
    return f"Done — {display_name} has been removed from your contacts."


class ConfirmRosterSkill:
    """Execute the pending roster action after user confirms."""

    name = "roster_confirm"
    description = "Confirm and execute the last staged roster change."
    params: ClassVar[list[SkillParam]] = []

    def __init__(self, pending: _PendingState) -> None:
        self._pending = pending

    def run(self, **_: object) -> str:
        return self._pending.confirm()


class CancelRosterSkill:
    """Cancel the pending roster action."""

    name = "roster_cancel"
    description = "Cancel the last staged roster change."
    params: ClassVar[list[SkillParam]] = []

    def __init__(self, pending: _PendingState) -> None:
        self._pending = pending

    def run(self, **_: object) -> str:
        return self._pending.cancel()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

class RosterVoiceSkills:
    """Factory that wires all roster skills to a shared RosterProvider and
    pending-state holder.

    Usage::

        rv = RosterVoiceSkills(roster_store)
        for skill in rv.skills():
            registry.register(skill)
    """

    def __init__(self, roster: RosterProvider) -> None:
        self._roster = roster
        self._pending = _PendingState()

    def skills(self) -> list[Skill]:
        p = self._pending
        r = self._roster
        return [
            AddContactSkill(r, p),
            EditHandlingRuleSkill(r, p),
            AddNoteSkill(r, p),
            UpdateNoteSkill(r, p),
            RemoveContactSkill(r, p),
            ConfirmRosterSkill(p),
            CancelRosterSkill(p),
        ]

    @property
    def pending(self) -> _PendingState:
        return self._pending
