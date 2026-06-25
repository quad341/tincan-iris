"""Streaming-skill bridge — the trust property is the point of these tests.

The design claim: we can make a skill's *output* stream while the ADR-0005
permission gate stays exactly where it was — authorized **once, in the brain,
before any chunk is produced**. So the load-bearing tests assert:

  * authorize fires exactly once, *before* the skill emits its first chunk;
  * a denied skill never runs and yields only a refusal line;
  * streaming changes output shape only — routing/gate are unchanged.

Plus the mechanics (streaming skill yields many chunks, plain skill yields one)
and a regression that factoring ``Tier1Qwen.handle`` left its contract intact.
None of these need a live Qwen — dispatch/chat are injected.
"""
from __future__ import annotations

import pytest

from iris.agenda_skill import AgendaSkill
from iris.brain import Brain, StreamChunk
from iris.lanes import LaneResult, SkillProposal, Tier1Qwen
from iris.skills import SkillRegistry, TimeSkill, supports_streaming
from iris.trust import TrustMode


# --------------------------------------------------------------------------
# Spies — record ordering of (authorize, skill-runs) without a real model.
# --------------------------------------------------------------------------

class _SpyStreamingSkill:
    """An operator-only streaming skill that logs when its body runs."""
    name = "agenda"
    description = "Read the day's agenda."
    params = AgendaSkill.params
    operator_only = True

    def __init__(self, log: list) -> None:
        self._log = log
        self.run_called = False
        self.stream_called = False

    def run(self, *, day: str = "today", **_k: object) -> str:
        self.run_called = True
        self._log.append("skill_run")
        return "You have 2 things today."

    def run_stream(self, *, day: str = "today", **_k: object):
        self.stream_called = True
        self._log.append("skill_stream_start")
        yield "You've got 2 things today."
        yield "10 a.m.: call with Bob."


def _brain_with(skill, log: list | None = None) -> tuple[Brain, list]:
    """A Brain wired to exactly ``skill``, with authorize wrapped to log calls.

    Pass a shared ``log`` to interleave authorize calls with a spy skill's own
    log entries (for ordering assertions). The wrapper delegates to the *real*
    Authorizer, so the gate's allow/deny logic is genuine — we only record that
    (and when) it was consulted."""
    log = [] if log is None else log
    reg = SkillRegistry()
    reg.register(skill)
    brain = Brain(skills=reg)
    real_authorize = brain.authz.authorize

    def spy_authorize(s, ctx):
        log.append("authorize")
        return real_authorize(s, ctx)

    brain.authz.authorize = spy_authorize  # type: ignore[method-assign]
    return brain, log


# --------------------------------------------------------------------------
# The trust property
# --------------------------------------------------------------------------

def test_gate_authorizes_once_before_first_chunk():
    log: list = []
    skill = _SpyStreamingSkill(log)
    brain, log = _brain_with(skill, log)          # ONE shared log: authorize + skill body
    gen = brain._stream_proposal(SkillProposal("agenda", {"day": "today"}), "operator")

    first = next(gen)  # pull only the first chunk

    # By the time the first chunk exists, authorize has already run — and the skill
    # body started strictly *after* it. This is the whole claim.
    assert log == ["authorize", "skill_stream_start"]
    assert first.text and not first.denied
    rest = list(gen)
    assert log.count("authorize") == 1          # authorized once for the whole stream
    assert skill.stream_called and not skill.run_called
    assert rest[-1].final is True               # stream terminates with a final marker


def test_denied_skill_never_runs_and_yields_only_refusal():
    skill = _SpyStreamingSkill([])
    brain, log = _brain_with(skill)
    # Far party + operator-only skill -> the real Authorizer denies.
    chunks = list(brain._stream_proposal(SkillProposal("agenda", {}), "far"))

    assert log == ["authorize"]                 # gate consulted...
    assert not skill.stream_called and not skill.run_called   # ...and the skill NEVER ran
    assert len(chunks) == 1
    assert chunks[0].denied is True and chunks[0].final is True
    assert chunks[0].text                       # far + operator-only -> a spoken refusal


def test_denied_before_any_chunk_even_when_pulled_lazily():
    skill = _SpyStreamingSkill([])
    brain, _ = _brain_with(skill)
    gen = brain._stream_proposal(SkillProposal("agenda", {}), "far")
    first = next(gen)
    assert first.denied and not skill.stream_called   # nothing streamed past the gate


# --------------------------------------------------------------------------
# Mechanics — streaming vs complete output shape
# --------------------------------------------------------------------------

def test_supports_streaming_helper():
    assert supports_streaming(AgendaSkill()) is True
    assert supports_streaming(TimeSkill()) is False


def test_agenda_run_stream_yields_preamble_then_per_event():
    chunks = list(AgendaSkill().run_stream(day="today"))
    assert len(chunks) == 4                      # preamble + 3 demo events
    assert "3" in chunks[0]                       # "You've got 3 things today."
    assert all(c.endswith(".") for c in chunks)
    # run() is the complete-result fallback — a single line carrying every event.
    whole = AgendaSkill().run(day="today")
    assert "3 things" in whole
    assert "call with Bob" in whole and "design review" in whole


def test_streaming_skill_streams_through_brain():
    skill = _SpyStreamingSkill([])
    brain, _ = _brain_with(skill)
    chunks = [c for c in brain._stream_proposal(SkillProposal("agenda", {}), "operator") if c.text]
    assert len(chunks) >= 2                       # multiple speakable chunks
    assert chunks[0].skill == "agenda"


def test_nonstreaming_skill_yields_single_final_chunk():
    brain, _ = _brain_with(TimeSkill())           # not operator-only, not streaming
    chunks = list(brain._stream_proposal(SkillProposal("time", {}), "operator"))
    assert len(chunks) == 1
    assert chunks[0].final is True and chunks[0].skill == "time"
    assert ":" in chunks[0].text                  # "It's H:MM ..."


def test_missing_required_arg_asks_instead_of_crashing():
    class _NeedsArg:
        name = "needsarg"; description = "x"; params = []; operator_only = False
        def run(self, *, required: str, **_k: object) -> str:
            return required
    brain, _ = _brain_with(_NeedsArg())
    chunks = list(brain._stream_proposal(SkillProposal("needsarg", {}), "operator"))
    assert len(chunks) == 1 and chunks[0].final
    assert "say it another way" in chunks[0].text.lower()


# --------------------------------------------------------------------------
# respond_stream routing (dispatch/chat injected — no live model)
# --------------------------------------------------------------------------

def test_respond_stream_skill_path(monkeypatch):
    skill = _SpyStreamingSkill([])
    brain, _ = _brain_with(skill)
    monkeypatch.setattr(brain.tier0, "handle", lambda text: None)   # force past Tier-0 rules
    monkeypatch.setattr(brain.tier1, "dispatch", lambda text, *, speaker="": SkillProposal("agenda", {}))
    chunks = list(brain.respond_stream("what's on today", speaker="operator"))
    assert skill.stream_called
    assert sum(1 for c in chunks if c.text) >= 2 and chunks[-1].final


def test_respond_stream_chat_path(monkeypatch):
    brain, _ = _brain_with(AgendaSkill())
    monkeypatch.setattr(brain.tier0, "handle", lambda text: None)   # force past Tier-0 rules
    monkeypatch.setattr(brain.tier1, "dispatch", lambda text, *, speaker="": None)
    monkeypatch.setattr(brain.tier1, "chat_stream",
                        lambda text, hint="": iter(["Hi there.", "How can I help?"]))
    texts = [c.text for c in brain.respond_stream("hello", speaker="operator") if c.text]
    assert texts == ["Hi there.", "How can I help?"]


def test_respond_stream_demo_mode_skips_skills(monkeypatch):
    # Far + DEMO: skills must not even be dispatched; falls straight to chat.
    called = {"dispatch": False}
    def _dispatch(text, *, speaker=""):
        called["dispatch"] = True
        return SkillProposal("agenda", {})
    brain, _ = _brain_with(AgendaSkill())
    monkeypatch.setattr(brain.tier0, "handle", lambda text: None)   # force past Tier-0 rules
    monkeypatch.setattr(brain.tier1, "dispatch", _dispatch)
    monkeypatch.setattr(brain.tier1, "chat_stream", lambda text, hint="": iter(["chat only."]))
    list(brain.respond_stream("hi", speaker="far", far_trust=TrustMode.DEMO))
    assert called["dispatch"] is False


# --------------------------------------------------------------------------
# Regression — factoring handle() into dispatch()/chat() kept its contract
# --------------------------------------------------------------------------

def test_factored_handle_contract(monkeypatch):
    reg = SkillRegistry()
    reg.register(AgendaSkill())
    t1 = Tier1Qwen.__new__(Tier1Qwen)            # avoid __init__/network
    t1.name = "tier1-qwen"
    t1.skills = reg

    # skill hit -> proposal LaneResult; no-skill -> chat LaneResult
    monkeypatch.setattr(t1, "dispatch", lambda text, *, speaker="": SkillProposal("agenda", {"day": "today"}))
    monkeypatch.setattr(t1, "chat", lambda text, hint="": "hello there")
    hit = t1.handle("what's on today", speaker="operator")
    assert isinstance(hit, LaneResult) and hit.proposal is not None and hit.skill == "agenda"

    monkeypatch.setattr(t1, "dispatch", lambda text, *, speaker="": None)
    miss = t1.handle("just chatting", speaker="operator")
    assert miss.proposal is None and miss.text == "hello there"

    # allow_skills=False never dispatches
    monkeypatch.setattr(t1, "dispatch", lambda text, *, speaker="": (_ for _ in ()).throw(AssertionError("dispatched")))
    demo = t1.handle("anything", allow_skills=False)
    assert demo.text == "hello there" and demo.proposal is None
