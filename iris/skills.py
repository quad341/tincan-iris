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
from typing import Protocol, runtime_checkable


@runtime_checkable
class Skill(Protocol):
    name: str
    description: str

    def run(self, **kwargs: object) -> str:
        ...


class TimeSkill:
    name = "time"
    description = "Tell the current local time."

    def run(self, **kwargs: object) -> str:
        return _dt.datetime.now().strftime("It's %-I:%M %p.")


class EchoSkill:
    name = "echo"
    description = "Repeat the given text (a trivial demo skill)."

    def run(self, text: str = "", **kwargs: object) -> str:
        return text


class SkillRegistry:
    """A tiny name -> skill registry. Real skills register an intent + handler."""

    def __init__(self, skills: list[Skill] | None = None) -> None:
        self._skills: dict[str, Skill] = {}
        for s in skills or []:
            self.register(s)

    def register(self, skill: Skill) -> None:
        self._skills[skill.name] = skill

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def names(self) -> list[str]:
        return list(self._skills)


def default_registry() -> SkillRegistry:
    return SkillRegistry([TimeSkill(), EchoSkill()])
