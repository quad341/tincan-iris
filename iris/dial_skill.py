"""Outgoing dial skills — ti-vai5.3.

Three skills for the iris outgoing-dial flow, mirroring the roster_skill.py
two-phase confirmation pattern:

  Phase 1 — DialSkill.run() resolves a roster contact by name and stages a
             pending dial, returning a spoken confirmation prompt.

  Phase 2 — ConfirmDialSkill.run() fires Calls.Dial() over D-Bus and waits
             up to 15 seconds for a CallConnected signal. Returns None on
             success (call audio takes over) or a spoken failure message.
             CancelDialSkill.run() clears the staged state without dialing.

All three skills are operator_only — the permission gate (Brain/Authorizer)
is the primary trust boundary; the speaker guard inside DialSkill.run() is
belt-and-suspenders.
"""
from __future__ import annotations

import threading

from .call_control import TincanCallControl
from .roster import RosterProvider
from .roster_skill import _find_by_name, _not_found
from .skills import SkillParam

_DIAL_TIMEOUT_S: float = 15.0


class _DialState:
    """Mutable holder for a staged outgoing-call action shared across skill instances."""

    def __init__(self) -> None:
        self._contact_name: str = ""
        self._number: str = ""

    def stage(self, contact_name: str, number: str) -> None:
        self._contact_name = contact_name
        self._number = number

    def pop(self) -> tuple[str, str]:
        name, number = self._contact_name, self._number
        self.clear()
        return name, number

    def clear(self) -> None:
        self._contact_name = ""
        self._number = ""

    @property
    def has_pending(self) -> bool:
        return bool(self._number)


class DialSkill:
    """Resolve a roster contact by name and stage an outgoing call for confirmation."""

    name = "dial_contact"
    description = "Call a contact from the roster by name. Operator-only."
    operator_only = True
    params: list[SkillParam] = [
        SkillParam(
            name="contact_name",
            type="string",
            description="Name of the contact to call.",
        ),
        SkillParam(
            name="speaker",
            type="string",
            description="Who invoked this skill (auto-injected by the lane).",
            required=False,
            default="operator",
        ),
    ]

    def __init__(self, roster: RosterProvider, pending: _DialState) -> None:
        self._roster = roster
        self._pending = pending

    def run(self, contact_name: str = "", speaker: str = "", **_: object) -> str | None:
        if speaker == "far":
            return None  # belt-and-suspenders; gate is Brain/Authorizer
        matches = _find_by_name(self._roster, contact_name)
        if not matches:
            return _not_found(contact_name)
        if len(matches) > 1:
            n = len(matches)
            options = " or ".join(c.display_name for c in matches[:3])
            return (
                f"I found {n} contacts named {contact_name} — {options}? "
                f"Which would you like?"
            )
        contact = matches[0]
        self._pending.stage(contact.display_name, contact.phone_e164)
        return f"Calling {contact.display_name} at {contact.phone_e164}. Shall I dial?"


class ConfirmDialSkill:
    """Execute the staged outgoing call; wait up to 15 s for CallConnected."""

    name = "dial_confirm"
    description = "Confirm and place the staged outgoing call."
    operator_only = True
    params: list[SkillParam] = []

    def __init__(
        self,
        ctrl: TincanCallControl,
        pending: _DialState,
        connected: threading.Event,
    ) -> None:
        self._ctrl = ctrl
        self._pending = pending
        self._connected = connected

    def run(self, **_: object) -> str | None:
        if not self._pending.has_pending:
            return "Nothing to confirm."
        _, number = self._pending.pop()
        self._connected.clear()
        error = self._ctrl.dial(number)
        if error:
            return "I couldn't connect the call."
        if self._connected.wait(timeout=_DIAL_TIMEOUT_S):
            return None  # connected — call audio takes over
        return "I couldn't connect the call."


class CancelDialSkill:
    """Clear the staged outgoing call without dialing."""

    name = "dial_cancel"
    description = "Cancel the staged outgoing call without dialing."
    operator_only = True
    params: list[SkillParam] = []

    def __init__(self, pending: _DialState) -> None:
        self._pending = pending

    def run(self, **_: object) -> str:
        self._pending.clear()
        return "OK, skipping that."


class DialVoiceSkills:
    """Factory wiring the dial skill trio to a TincanCallControl and a roster.

    Intercepts ctrl.emit to detect the CallConnected signal so ConfirmDialSkill
    can unblock its 15-second wait without external plumbing.

    Usage::

        dv = DialVoiceSkills(ctrl, roster_store)
        for skill in dv.skills():
            registry.register(skill)
    """

    def __init__(self, ctrl: TincanCallControl, roster: RosterProvider) -> None:
        self._ctrl = ctrl
        self._roster = roster
        self._pending = _DialState()
        self._connected = threading.Event()

        _orig_emit = ctrl.emit

        def _intercept(ev: tuple) -> None:  # noqa: ANN001
            _orig_emit(ev)
            if ev and ev[0] == "call_connected":
                self._connected.set()

        ctrl.emit = _intercept

    def skills(self) -> list:
        return [
            DialSkill(self._roster, self._pending),
            ConfirmDialSkill(self._ctrl, self._pending, self._connected),
            CancelDialSkill(self._pending),
        ]
