"""Brain — route a turn through the cheapest viable lane, timed end to end."""
from __future__ import annotations

import re
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from .config import DEFAULT, Config
from .lanes import LaneResult, Tier0Rules, Tier1Qwen, Tier2RawHaiku
from .latency import Timeline
from .masking import run_with_masking
from .notes import NotesStore
from .prefs import PreferencesStore
from .skills import SkillRegistry, default_registry
from .trust import TrustMode


@dataclass
class Reply:
    text: str
    lane: str
    timeline: Timeline
    skill: str | None = None
    speaker: str = ""  # "operator" | "far" | "" — who spoke; set by brain.respond(speaker=)


class Brain:
    """Tiered router with latency masking, a hard fallback, and a local stop.

    Explicit escalation ("ask Haiku about X") routes to Tier 2 (raw text).
    Otherwise the cheapest viable lane wins: Tier 0 rules -> Tier 1 local Qwen.
    Slow lanes (1 and 2) get masked: ``on_filler(i)`` fires (and repeats) while
    they lag; the user can Ctrl-C to stop instantly ("Okay — stopping."); and if
    a lane blows the deadline it falls back to a graceful spoken line instead of
    dead air. Actions never leave the local tiers (see ``docs/adr/0001``).
    """

    # "ask Haiku about <X>" / "ask Haiku <X>" — optional leading wake word.
    _ASK_HAIKU = re.compile(r"(?:iris[,\s]+)?ask haiku(?:\s+about)?\s+(.+)", re.IGNORECASE)

    def __init__(self, cfg: Config = DEFAULT, skills: SkillRegistry | None = None,
                 notes_store: NotesStore | None = None,
                 prefs: PreferencesStore | None = None) -> None:
        self.cfg = cfg
        self.prefs = prefs or PreferencesStore()
        self.call_context: str = ""   # set to a contact ID before each call
        self.memory_hint: str = ""    # L3 vector recall hint from MemoryManager.call_start()
        self.context_hint: str = ""   # supplementary context hint (caller-level notes etc.)
        if skills is None:
            self.skills = default_registry()
            # Optional/offline lanes (notes, roster, web search, email when
            # configured); each registers only when its dependency is present, so
            # qwen — and the HomeApp that drives this Brain — get exactly the
            # skills that work.
            from .skill_wiring import optional_skills
            for s in optional_skills(notes_store=notes_store):
                self.skills.register(s)
        else:
            self.skills = skills
        self.tier0 = Tier0Rules(self.skills)
        self.tier1 = Tier1Qwen(cfg, skills=self.skills)
        self.tier2 = Tier2RawHaiku(cfg)

    def is_reachable(self) -> bool:
        """True if the local qwen server (Tier-1 backend) is responding.

        Probes the configured ``qwen_base_url`` /health (llama.cpp-compatible).
        The HomeApp uses this to decide whether to accept input.
        """
        try:
            with urllib.request.urlopen(self.cfg.qwen_base_url + "/health", timeout=2) as resp:
                return 200 <= getattr(resp, "status", 200) < 300
        except (urllib.error.URLError, OSError):
            return False

    def _masked(
        self,
        work: Callable[[], LaneResult],
        lane: str,
        on_filler: Callable[[int], None] | None,
    ) -> LaneResult:
        """Run a lane with repeating fillers, a Ctrl-C stop, and a deadline fallback."""
        fallback = LaneResult(self.cfg.lane_timeout_reply, f"{lane}(timeout)")
        interrupted = LaneResult("Okay — stopping.", f"{lane}(stopped)")
        result = run_with_masking(
            work,
            first_filler_s=self.cfg.first_filler_s,
            repeat_filler_s=self.cfg.repeat_filler_s,
            deadline_s=self.cfg.lane_deadline_s,
            on_filler=on_filler,
            fallback=fallback,
            interrupted=interrupted,
        )
        return result if result is not None else fallback

    def respond(
        self,
        text: str,
        *,
        speaker: str = "",
        far_trust: TrustMode = TrustMode.FULL,
        op_trust: TrustMode = TrustMode.FULL,
        on_filler: Callable[[int], None] | None = None,
    ) -> Reply:
        tl = Timeline()
        demo_mode = speaker == "far" and far_trust is TrustMode.DEMO

        # Explicit escalation — "ask Haiku about X" -> Tier 2 (raw text, slow).
        # Blocked in DEMO mode: the far party cannot reach the cloud tier.
        m = self._ASK_HAIKU.match(text.strip())
        if m and self.cfg.haiku_enabled and not demo_mode:
            try:
                r2 = self._masked(lambda: self.tier2.handle(m.group(1).strip()), "tier2-haiku", on_filler)
                tl.mark("tier2-haiku")
                return Reply(r2.text, r2.lane, tl, speaker=speaker)
            except Exception as exc:  # noqa: BLE001 — degrade gracefully, don't crash
                tl.mark("tier2-haiku(failed)")
                return Reply(f"(couldn't reach Haiku: {exc})", "tier2-haiku", tl, speaker=speaker)
        if m and demo_mode:
            tl.mark("tier2-haiku(blocked-demo)")
            return Reply(
                "Sorry — I can only help with that once the operator grants full access.",
                "tier2-haiku(blocked-demo)", tl, speaker=speaker,
            )

        # Tier 0 — deterministic local commands (sub-millisecond, never slow).
        r0 = self.tier0.handle(text)
        tl.mark("tier0")
        if r0 is not None:
            return Reply(r0.text, r0.lane, tl, r0.skill, speaker=speaker)

        # Tier 1 — local Qwen (warm). Masked + deadline-bounded for the busy box.
        hint = self.prefs.hint(self.call_context) if self.call_context else ""
        try:
            r1 = self._masked(
                lambda: self.tier1.handle(text, allow_skills=not demo_mode, context_hint=hint),
                "tier1-qwen", on_filler,
            )
            tl.mark("tier1-qwen")
            return Reply(r1.text, r1.lane, tl, r1.skill, speaker=speaker)
        except Exception as exc:  # noqa: BLE001 — local model hiccup: degrade, don't crash
            tl.mark("tier1-qwen(failed)")
            return Reply(f"(the local model didn't answer: {exc})", "tier1-qwen", tl, speaker=speaker)

    def set_pref(self, key: str, value: str, *, context: str | None = None) -> None:
        """Write a caller preference.  Falls back to ``self.call_context`` when no
        explicit context is given; no-op if neither is set."""
        ctx = context or self.call_context
        if not ctx:
            return
        self.prefs.set(ctx, key, value)

    def close(self) -> None:
        """Tear down any warm sessions (e.g. the Tier-2 Claude TUI)."""
        self.tier2.close()
