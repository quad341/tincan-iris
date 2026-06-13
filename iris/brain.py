"""Brain — route a turn through the cheapest viable lane, timed end to end."""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from .config import DEFAULT, Config
from .lanes import Tier0Rules, Tier1Qwen, Tier2RawHaiku
from .latency import Timeline
from .masking import run_with_filler
from .skills import SkillRegistry, default_registry


@dataclass
class Reply:
    text: str
    lane: str
    timeline: Timeline
    skill: str | None = None


class Brain:
    """Tiered router with latency masking.

    Explicit escalation ("ask Haiku about X") routes to Tier 2 (raw text).
    Otherwise the cheapest viable lane wins: Tier 0 rules -> Tier 1 local Qwen.
    Slow lanes (1 and 2) are wrapped so that if they exceed a threshold, an
    optional ``on_filler`` fires *in parallel* — the latency mask ("umm, one
    sec") that keeps dead air off the line. Actions never leave the local tiers
    (direct-API skill adapters; see ``docs/adr/0001``).
    """

    # "ask Haiku about <X>" / "ask Haiku <X>" — optional leading wake word.
    _ASK_HAIKU = re.compile(r"(?:iris[,\s]+)?ask haiku(?:\s+about)?\s+(.+)", re.IGNORECASE)

    def __init__(self, cfg: Config = DEFAULT, skills: SkillRegistry | None = None) -> None:
        self.cfg = cfg
        self.skills = skills or default_registry()
        self.tier0 = Tier0Rules(self.skills)
        self.tier1 = Tier1Qwen(cfg)
        self.tier2 = Tier2RawHaiku(cfg)

    def respond(self, text: str, on_filler: Callable[[], None] | None = None) -> Reply:
        tl = Timeline()

        # Explicit escalation — "ask Haiku about X" -> Tier 2 (raw text, slow).
        m = self._ASK_HAIKU.match(text.strip())
        if m and self.cfg.haiku_enabled:
            try:
                r2 = run_with_filler(
                    lambda: self.tier2.handle(m.group(1).strip()),
                    self.cfg.filler_threshold_s,
                    on_filler,
                )
                tl.mark("tier2-haiku")
                return Reply(r2.text, r2.lane, tl)
            except Exception as exc:  # noqa: BLE001 — degrade gracefully, don't crash
                tl.mark("tier2-haiku(failed)")
                return Reply(f"(couldn't reach Haiku: {exc})", "tier2-haiku", tl)

        # Tier 0 — deterministic rules (sub-millisecond, never slow).
        r0 = self.tier0.handle(text)
        tl.mark("tier0")
        if r0 is not None:
            return Reply(r0.text, r0.lane, tl, r0.skill)

        # Tier 1 — local Qwen (warm). Usually fast; masked + graceful just in case.
        try:
            r1 = run_with_filler(
                lambda: self.tier1.handle(text), self.cfg.filler_threshold_s, on_filler
            )
            tl.mark("tier1-qwen")
            return Reply(r1.text, r1.lane, tl, r1.skill)
        except Exception as exc:  # noqa: BLE001 — local model hiccup: degrade, don't crash
            tl.mark("tier1-qwen(failed)")
            return Reply(f"(the local model didn't answer in time: {exc})", "tier1-qwen", tl)

    def close(self) -> None:
        """Tear down any warm sessions (e.g. the Tier-2 Claude TUI)."""
        self.tier2.close()
