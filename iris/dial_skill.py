"""dial_skill — let Iris place an outgoing call ("Iris, call mom").

One skill backed by a TincanCallControl client:

  CallContactSkill — resolve a roster contact name → phone number (reusing the
                     same RosterStore + name resolution as the roster skills),
                     then place the call via ``TincanCallControl.dial``. Iris
                     then rides the connected call as usual (the ``CallConnected``
                     signal binds the SCO audio endpoint just like an answered
                     call).

PRIVILEGE — placing a call is operator-only. ``operator_only = True`` tells the
dispatch layer never to offer this skill to, or run it for, the far party (even
at FULL trust): the grammar hides it for non-operator speakers and the lane
refuses to run it for them. As a third line of defence, ``run()`` itself takes a
``speaker`` argument (like ``WebSearchSkill``) and refuses anything but the
operator — so even a direct call from the wrong channel is denied. The far party
must NEVER be able to dial out through Iris.

Usage (inject via the brain's skill registry, once tincand is present):

    calls = TincanCallControl(emit=queue.append)
    calls.start()
    for s in configured_dial_skills(calls, roster):
        brain.skills.register(s)
"""
from __future__ import annotations

from .call_control import TincanCallControl
from .roster import RosterProvider, RosterStore
from .roster_skill import _disambiguate, _find_by_name, _not_found
from .skills import SkillParam


def _looks_like_number(value: str) -> bool:
    """True if ``value`` looks like a dialable number (E.164 or digits only).

    Mirrors the messages skill's recipient heuristic: a leading ``+`` is allowed,
    the rest must be digits."""
    v = value.strip()
    return bool(v) and v.lstrip("+").isdigit()


class CallContactSkill:
    """Place an outgoing call to a roster contact by name (or to a raw number).

    Operator/mic-channel only — see the module docstring."""

    name = "call_contact"
    description = (
        "Place an outgoing phone call to a contact by name (e.g. \"call Mom\") "
        "or to a phone number. Operator only."
    )
    # Marks this as a privileged skill: never offered to / run for the far party.
    operator_only = True
    params: list[SkillParam] = [
        SkillParam(
            name="contact",
            type="string",
            description=(
                "Contact name to call (e.g. \"Mom\"), or a phone number in "
                "E.164 format (e.g. +15555550100)."
            ),
        ),
    ]

    def __init__(self, call_control: TincanCallControl, roster: RosterProvider) -> None:
        self._calls = call_control
        self._roster = roster

    def _resolve(self, contact: str) -> tuple[str | None, str]:
        """Resolve ``contact`` to ``(number, spoken_reply_on_failure)``.

        Returns ``(number, "")`` on success. On failure ``number`` is ``None``
        and the second element is the spoken reply to give back (not-found,
        disambiguation, or missing-number)."""
        if _looks_like_number(contact):
            return contact.strip(), ""
        matches = _find_by_name(self._roster, contact)
        if not matches:
            return None, _not_found(contact)
        if len(matches) > 1:
            return None, _disambiguate(matches)
        c = matches[0]
        if not c.phone_e164:
            return None, f"I don't have a phone number for {c.display_name}."
        return c.phone_e164, ""

    def run(
        self,
        *,
        contact: str = "",
        speaker: str = "operator",
        **_kwargs: object,
    ) -> str:
        # Defence in depth: never place a call for the far party, even if this
        # skill somehow reached run() off-channel (the dispatch layer already
        # hides it for non-operator speakers).
        if speaker != "operator":
            return "Placing calls is only available to the operator."
        if not contact:
            return "Who would you like to call?"

        number, failure_reply = self._resolve(contact)
        if number is None:
            return failure_reply

        result = self._calls.dial(number)
        if result is None:
            return "Sorry — I couldn't place the call."
        return f"Calling {contact} now."


def dial_skills(call_control: TincanCallControl, roster: RosterProvider) -> list:
    """Return the dial skills backed by ``call_control`` + ``roster``."""
    return [CallContactSkill(call_control, roster)]


def configured_dial_skills(
    call_control: TincanCallControl | None = None,
    roster: RosterProvider | None = None,
) -> list:
    """Return dial skills when tincand can place calls, else ``[]``.

    Gated on tincand being available, mirroring how the messages/calendar lanes
    register only when their daemon/token is present: with no bus connected the
    call client can't dial, so offering the skill would be a dead end. Pass a
    started :class:`TincanCallControl` (``calls.start()`` already called) to
    enable the lane; ``None`` (or a client with no bus) yields ``[]``.
    """
    if call_control is None or getattr(call_control, "_bus", None) is None:
        return []
    return dial_skills(call_control, roster or RosterStore())
