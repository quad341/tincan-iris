"""Skills — self-authored direct-API adapters, orchestrated by the local model.

DESIGN (see ``docs/adr/0001``): a skill is an action implemented against a
service's *direct* API — Google Calendar REST, IMAP/SMTP, tincan's D-Bus
interface, and so on. We deliberately do **not** run MCP servers: no
marketplace / supply-chain surface, no extra network hop, and the cloud model
never touches tools. The warm local model decides which skill to call.

The two skills here are trivial demos so the brain has something to dispatch
to before the real (auth'd) integrations land.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable


@dataclass
class SkillParam:
    """A single parameter a skill accepts — used to build the dispatch grammar and prompt."""
    name: str
    type: Literal["string", "integer", "number", "boolean"]
    description: str
    required: bool = True
    default: object = None       # only meaningful when required=False
    enum: list[str] | None = field(default=None)  # constrained string choices


@runtime_checkable
class Skill(Protocol):
    name: str
    description: str
    params: list[SkillParam]    # empty list = skill takes no args
    # operator_only marks a privileged skill that must NEVER be offered to,
    # or run for, the far party — even at FULL trust. The registry filters these
    # out of the dispatch grammar/manifest for any speaker other than the
    # operator (mic channel), and the lane refuses to run one for a non-operator
    # speaker as a second line of defence. Optional: skills that don't set it are
    # treated as operator_only=False (available to whoever the trust gate allows).
    operator_only: bool

    def run(self, **kwargs: object) -> str:
        ...


def is_operator_only(skill: object) -> bool:
    """True if ``skill`` is marked operator/mic-channel only.

    Tolerant of skills that predate the attribute (defaults to ``False``)."""
    return bool(getattr(skill, "operator_only", False))


class TimeSkill:
    name = "time"
    description = "Tell the current local time."
    params: list[SkillParam] = []

    def run(self, **kwargs: object) -> str:
        return _dt.datetime.now().strftime("It's %-I:%M %p.")


class EchoSkill:
    name = "echo"
    description = "Repeat the given text (a trivial demo skill)."
    params: list[SkillParam] = [
        SkillParam(name="text", type="string", description="Text to echo back."),
    ]

    def run(self, text: str = "", **kwargs: object) -> str:
        return text


class SkillRegistry:
    """A tiny name -> skill registry. Real skills register an intent + handler."""

    def __init__(self, skills: list[Skill] | None = None) -> None:
        self._skills: dict[str, Skill] = {}
        self.grammar_dirty: bool = False  # set True on register; Tier1Qwen rebuilds grammar
        for s in skills or []:
            self.register(s)

    def register(self, skill: Skill) -> None:
        self._skills[skill.name] = skill
        self.grammar_dirty = True

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def _visible_to(self, speaker: str) -> list[Skill]:
        """Skills the given speaker may see/dispatch.

        ``speaker=""`` (the default everywhere this isn't threaded yet) returns
        every skill — unchanged behaviour. Any non-operator speaker (e.g.
        ``"far"``) has operator_only skills filtered out, so a privileged action
        is never even offered to the far party."""
        if not speaker or speaker == "operator":
            return list(self._skills.values())
        return [s for s in self._skills.values() if not is_operator_only(s)]

    def names(self, speaker: str = "") -> list[str]:
        """Registered skill names, optionally scoped to ``speaker`` (see ``_visible_to``)."""
        return [s.name for s in self._visible_to(speaker)]

    def manifest(self, speaker: str = "") -> list[dict]:
        """Return [{name, description, params}] for the registered skills.

        Used by Tier1Qwen to build the dispatch grammar and inject into the system
        prompt. ``params`` is a list of param dicts so the caller can serialize
        without further dataclass introspection. ``speaker`` scopes the result so
        operator_only skills are hidden from the far party (see ``_visible_to``).
        """
        return [
            {
                "name": s.name,
                "description": s.description,
                "params": [
                    {
                        "name": p.name,
                        "type": p.type,
                        "description": p.description,
                        "required": p.required,
                        "default": p.default,
                        "enum": p.enum,
                    }
                    for p in s.params
                ],
            }
            for s in self._visible_to(speaker)
        ]


def default_registry() -> SkillRegistry:
    return SkillRegistry([TimeSkill(), EchoSkill()])
