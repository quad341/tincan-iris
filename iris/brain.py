"""Brain — route a turn through the cheapest viable lane, timed end to end."""
from __future__ import annotations

import re
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from .config import DEFAULT, Config
from .authz import Authorizer, AuthzContext
from .lanes import LaneResult, SkillProposal, Tier0Rules, Tier1Qwen, Tier2RawHaiku, _reply_text
from .latency import Timeline
from .masking import run_with_masking
from .notes import NotesStore
from .prefs import PreferencesStore
from .re_ask_phrasebook import is_re_ask
from .skills import SkillRegistry, default_registry, is_operator_only, supports_streaming
from .trust import TrustMode


@dataclass
class Reply:
    text: str
    lane: str
    timeline: Timeline
    skill: str | None = None
    speaker: str = ""  # "operator" | "far" | "" — who spoke; set by brain.respond(speaker=)
    re_ask: bool = False  # True when far party signalled they didn't catch the last utterance


@dataclass
class StreamChunk:
    """One speakable piece of a streamed turn. The conductor synth+plays each as it
    arrives, so the first sentence reaches the uplink without waiting for the rest.

    ``respond`` returns one ``Reply``; ``respond_stream`` yields these. Tier-0 and
    non-streaming skills yield a single ``final`` chunk; chat and streaming skills
    yield several. ``denied`` marks the gate's refusal line (no skill ran)."""
    text: str
    lane: str = ""
    skill: str | None = None
    final: bool = False     # last chunk of this turn
    denied: bool = False    # permission gate denied the proposed skill — nothing executed


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
                 prefs: PreferencesStore | None = None,
                 ctrl: object = None) -> None:
        self.cfg = cfg
        self.prefs = prefs or PreferencesStore()
        self.call_context: str = ""   # set to a contact ID before each call
        self.memory_hint: str = ""    # L3 vector recall hint from MemoryManager.call_start()
        self.context_hint: str = ""   # supplementary context hint (caller-level notes etc.)
        self._locked_language: str = "en"  # updated when PresentationProfile is locked
        if skills is None:
            self.skills = default_registry()
            # Optional/offline lanes (notes, roster, web search, email when
            # configured); each registers only when its dependency is present, so
            # qwen — and the HomeApp that drives this Brain — get exactly the
            # skills that work.
            from .skill_wiring import optional_skills
            for s in optional_skills(notes_store=notes_store, ctrl=ctrl):
                self.skills.register(s)
        else:
            self.skills = skills
        self.tier0 = Tier0Rules(self.skills)
        self.tier1 = Tier1Qwen(cfg, skills=self.skills)
        self.tier2 = Tier2RawHaiku(cfg)
        self.authz = Authorizer()   # daemon-owned permission gate (ADR-0005)

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

        # Tier-0 re-ask detection: far party only; length guard ≤6 words.
        re_ask = (
            speaker == "far"
            and len(text.split()) <= 6
            and is_re_ask(text, lang=self._locked_language)
        )

        # Explicit escalation — "ask Haiku about X" -> Tier 2 (raw text, slow).
        # Blocked in DEMO mode: the far party cannot reach the cloud tier.
        m = self._ASK_HAIKU.match(text.strip())
        if m and self.cfg.haiku_enabled and not demo_mode:
            try:
                r2 = self._masked(lambda: self.tier2.handle(m.group(1).strip()), "tier2-haiku", on_filler)
                tl.mark("tier2-haiku")
                return Reply(r2.text, r2.lane, tl, speaker=speaker, re_ask=re_ask)
            except Exception as exc:  # noqa: BLE001 — degrade gracefully, don't crash
                tl.mark("tier2-haiku(failed)")
                return Reply(f"(couldn't reach Haiku: {exc})", "tier2-haiku", tl, speaker=speaker, re_ask=re_ask)
        if m and demo_mode:
            tl.mark("tier2-haiku(blocked-demo)")
            return Reply(
                "Sorry — I can only help with that once the operator grants full access.",
                "tier2-haiku(blocked-demo)", tl, speaker=speaker, re_ask=re_ask,
            )

        # Tier 0 — deterministic local commands (sub-millisecond, never slow).
        r0 = self.tier0.handle(text)
        tl.mark("tier0")
        if r0 is not None:
            return Reply(r0.text, r0.lane, tl, r0.skill, speaker=speaker, re_ask=re_ask)

        # Tier 1 — local Qwen (warm). Masked + deadline-bounded for the busy box.
        hint = self.prefs.hint(self.call_context) if self.call_context else ""
        try:
            r1 = self._masked(
                lambda: self._dispatch(text, speaker=speaker, hint=hint, demo_mode=demo_mode),
                "tier1-qwen", on_filler,
            )
            tl.mark("tier1-qwen")
            return Reply(r1.text, r1.lane, tl, r1.skill, speaker=speaker, re_ask=re_ask)
        except Exception as exc:  # noqa: BLE001 — local model hiccup: degrade, don't crash
            tl.mark("tier1-qwen(failed)")
            return Reply(f"(the local model didn't answer: {exc})", "tier1-qwen", tl, speaker=speaker, re_ask=re_ask)

    def respond_stream(
        self,
        text: str,
        *,
        speaker: str = "",
        far_trust: TrustMode = TrustMode.FULL,
        op_trust: TrustMode = TrustMode.FULL,
    ) -> Iterator[StreamChunk]:
        """Streaming sibling of ``respond``: yield speakable chunks as they're ready.

        Same routing and — critically — the SAME one-time propose→authorize→execute
        gate (ADR-0005) as ``respond``. A streaming skill's ``run_stream`` is consumed
        only *after* authorize allows it, so the trust boundary is unchanged; only the
        output shape (a stream of chunks vs one blob) differs. Prototype path: Tier-2
        ("ask Haiku") and latency-masking are not yet wired here — see respond()."""
        demo_mode = speaker == "far" and far_trust is TrustMode.DEMO

        # Tier 0 — deterministic local commands; always a single complete chunk.
        r0 = self.tier0.handle(text)
        if r0 is not None:
            yield StreamChunk(r0.text, r0.lane, r0.skill, final=True)
            return

        # Tier 1 — the grammar dispatch IS the routing decision (internal JSON; not
        # spoken, so it cannot stream). Skills are offered only on FULL-trust turns.
        proposal = None if demo_mode else self.tier1.dispatch(text, speaker=speaker)
        if proposal is None:
            # Chat path — stream the reply sentence-by-sentence (low time-to-first-audio).
            hint = self.prefs.hint(self.call_context) if self.call_context else ""
            try:
                for piece in self.tier1.chat_stream(text, hint):
                    yield StreamChunk(piece, self.tier1.name)
            except Exception as exc:  # noqa: BLE001 — degrade, don't crash
                yield StreamChunk(f"(the local model didn't answer: {exc})", self.tier1.name, final=True)
                return
            yield StreamChunk("", self.tier1.name, final=True)
            return

        # Skill path — propose → authorize → execute, streaming the output.
        yield from self._stream_proposal(proposal, speaker)

    def _stream_proposal(self, proposal: SkillProposal, speaker: str) -> Iterator[StreamChunk]:
        """Authorize the proposed skill **once**, then stream (or complete) its output.

        The trust boundary for the streaming path (ADR-0005 §4): the gate fires
        *before any chunk is produced*; on denial the skill never runs and only a
        refusal line is spoken. Mirrors ``_dispatch`` — same authorize call, same
        denial phrasing — so streaming can't reach a skill the non-streaming path
        wouldn't."""
        lane = self.tier1.name
        skill = self.skills.get(proposal.skill)
        if skill is None:
            yield StreamChunk("Sorry — I can't do that right now.", lane, proposal.skill, final=True)
            return
        ctx = AuthzContext(is_operator=self._resolve_is_operator(speaker))
        if not self.authz.authorize(skill, ctx).allowed:
            phrase = self._denial_phrase(skill, speaker)
            yield StreamChunk(phrase or "", lane, proposal.skill, final=True, denied=True)
            return
        # Authorized. Stream the output if the skill supports it; else one complete chunk.
        try:
            if supports_streaming(skill):
                for piece in skill.run_stream(**proposal.args):
                    yield StreamChunk(_reply_text(piece), lane, proposal.skill)
                yield StreamChunk("", lane, proposal.skill, final=True)
            else:
                yield StreamChunk(_reply_text(skill.run(**proposal.args)), lane, proposal.skill, final=True)
        except TypeError:
            # proposed a skill without a required arg — ask, don't error out (matches _dispatch)
            yield StreamChunk(
                "Sorry — I didn't catch the details for that. Could you say it another way?",
                lane, proposal.skill, final=True,
            )

    def _resolve_is_operator(self, speaker: str) -> bool:
        """Resolve the principal **default-closed**: the speaker is the operator
        only when we're sure. A far speaker is never the operator; an *unknown*
        speaker is the operator only outside a call (where the operator is the
        sole party) — inside a call, default closed (treat as far)."""
        if speaker == "operator":
            return True
        if speaker == "far":
            return False
        return not self.call_context   # speaker == "": operator iff not in a call

    def _denial_phrase(self, skill: object, speaker: str) -> str | None:
        """Return the Iris response when the permission gate denies a skill.

        Returns None for scenario 2 with no active call (silence — don't
        confirm Iris heard an unrecognized voice outside a call context).
        See design doc ti-6pwl.1 for phrase rationale and voice guidelines.
        """
        if is_operator_only(skill):
            if speaker == "far":
                # Scenario 1: far party requests an operator_only skill
                name = self.cfg.operator_name or "the operator"
                return f"That's something I can only do at {name}'s request."
            if speaker not in {"operator", "far"}:
                # Scenario 2: unrecognized speaker requests a privileged skill
                if self.call_context:
                    return "I need the operator to confirm that one."
                return None  # silence outside a call — don't confirm an unrecognized voice was heard
            # Scenario 3 (future): operator assurance too low — phrase locked now; not yet triggered
            # TODO: wire when assurance gate lands (ADR-0005 v2)
            return "I'm not set up to do that right now."
        # Scenario 4: generic catch-all
        return "Sorry, I can't help with that one."

    def _dispatch(
        self, text: str, *, speaker: str, hint: str, demo_mode: bool,
    ) -> LaneResult:
        """Propose → authorize → execute (ADR-0005 §4). The lane proposes a skill;
        the daemon gate authorizes it; only then is it run. The model is never the
        trust boundary, so a coaxed model can't get past a proposal."""
        lr = self.tier1.handle(
            text, allow_skills=not demo_mode, context_hint=hint, speaker=speaker,
        )
        if lr.proposal is None:
            return lr  # chat / no-skill — already a final result
        skill = self.skills.get(lr.proposal.skill)
        if skill is None:
            return LaneResult("Sorry — I can't do that right now.", lr.lane, skill=lr.proposal.skill)
        ctx = AuthzContext(is_operator=self._resolve_is_operator(speaker))
        if not self.authz.authorize(skill, ctx).allowed:
            phrase = self._denial_phrase(skill, speaker)
            return LaneResult(phrase or "", lr.lane, skill=lr.proposal.skill)
        try:
            result = skill.run(**lr.proposal.args)
        except TypeError:
            # proposed a skill without a required arg — ask, don't error out
            return LaneResult(
                "Sorry — I didn't catch the details for that. Could you say it another way?",
                lr.lane, skill=lr.proposal.skill,
            )
        return LaneResult(_reply_text(result), lr.lane, skill=lr.proposal.skill)

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
