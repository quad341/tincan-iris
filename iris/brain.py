"""Brain — route a turn through the cheapest viable lane, timed end to end."""
from __future__ import annotations

from dataclasses import dataclass

from .config import DEFAULT, Config
from .lanes import Tier0Rules, Tier1Qwen, Tier2RawHaiku
from .latency import Timeline
from .skills import SkillRegistry, default_registry


@dataclass
class Reply:
    text: str
    lane: str
    timeline: Timeline
    skill: str | None = None


class Brain:
    """Tiered router. v0 wires Tier 0 (rules) -> Tier 1 (local Qwen).

    Tier 2 (raw Haiku, text-only) is constructed but not yet invoked; routing
    to it lands with its driver. Actions never leave the local tiers — they run
    as direct-API skill adapters (see ``docs/adr/0001``).
    """

    def __init__(self, cfg: Config = DEFAULT, skills: SkillRegistry | None = None) -> None:
        self.cfg = cfg
        self.skills = skills or default_registry()
        self.tier0 = Tier0Rules(self.skills)
        self.tier1 = Tier1Qwen(cfg)
        self.tier2 = Tier2RawHaiku(cfg)

    def respond(self, text: str) -> Reply:
        tl = Timeline()

        # Tier 0 — deterministic rules (sub-millisecond).
        r0 = self.tier0.handle(text)
        tl.mark("tier0")
        if r0 is not None:
            return Reply(r0.text, r0.lane, tl, r0.skill)

        # Tier 1 — local Qwen (warm). The workhorse and skill orchestrator.
        r1 = self.tier1.handle(text)
        tl.mark("tier1-qwen")
        return Reply(r1.text, r1.lane, tl, r1.skill)
