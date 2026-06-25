"""Live smoke: qwen actually dispatches natural language to a registered skill.

The dispatch test skips when no qwen server answers on the configured base URL,
so CI (no model) passes; on a box with llama.cpp up it verifies the real path.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from iris.config import Config
from iris.lanes import Tier1Qwen
from iris.skills import SkillParam, SkillRegistry


def _brain():
    from iris.brain import Brain
    return Brain()


def test_is_reachable_returns_bool_even_when_down():
    # must never raise — HomeApp relies on this to gate input
    assert isinstance(_brain().is_reachable(), bool)


def test_qwen_dispatches_language_to_a_skill():
    b = _brain()
    if not b.is_reachable():
        pytest.skip("qwen server not reachable on the configured base URL")
    r = b.respond("take a note: buy milk tomorrow")
    assert r.text  # produced a reply
    # the note phrasing should route to a skill, not chat-only
    assert r.skill is not None or r.lane.startswith("tier1")


# ---------------------------------------------------------------------------
# Multi-arg dispatch (no live qwen — _complete is patched)
#
# Regression: a multi-arg skill (calendar free/busy needs start + end) used to
# crash with "missing required keyword-only arguments" because the grammar
# allowed only one arg and the prompt taught neither the params nor the date.
# ---------------------------------------------------------------------------

class _BookSkill:
    """A strict two-arg skill (no ``**kwargs``) — proves args reach run() and
    that unknown keys are filtered before the call."""

    name = "book"
    description = "Book a time slot."
    params = [
        SkillParam(name="start", type="string", description="ISO 8601 start"),
        SkillParam(name="end", type="string", description="ISO 8601 end"),
    ]

    def __init__(self) -> None:
        self.called_with = None

    def run(self, *, start, end):       # strict signature — no **kwargs
        self.called_with = {"start": start, "end": end}
        return f"booked {start}/{end}"


def _tier_with_book():
    skill = _BookSkill()
    return Tier1Qwen(Config(), skills=SkillRegistry([skill])), skill


def test_dispatch_grammar_allows_multiple_args():
    tier, _ = _tier_with_book()
    # args object now permits repeated key/value pairs, not just one
    assert '( ws "," ws str-kv )*' in tier._build_grammar()


def test_dispatch_prompt_lists_params_and_current_time():
    import datetime as _dt
    tier, _ = _tier_with_book()
    prompt = tier._dispatch_prompt("am I free at 3pm?")
    assert "start" in prompt and "end" in prompt        # params are taught
    assert "Right now it is" in prompt                  # current datetime injected
    assert str(_dt.datetime.now().year) in prompt


def test_handle_proposes_skill_with_filtered_args():
    """The lane PROPOSES — it does NOT execute. The daemon runs it (ADR-0005 §4).
    Skill execution + the gate live in test_permission_gate.py."""
    tier, skill = _tier_with_book()
    raw = '{"skill":"book","args":{"start":"2026-06-19T15:00:00","end":"2026-06-19T16:00:00"}}'
    with patch.object(tier, "_complete", return_value=raw):
        r = tier.handle("am I free at 3pm?")
    assert skill.called_with is None                    # the lane must NOT run it
    assert r.proposal is not None
    assert r.proposal.skill == "book"
    assert r.proposal.args == {"start": "2026-06-19T15:00:00", "end": "2026-06-19T16:00:00"}


def test_handle_proposal_drops_unknown_args():
    tier, skill = _tier_with_book()
    raw = '{"skill":"book","args":{"start":"S","end":"E","bogus":"x"}}'
    with patch.object(tier, "_complete", return_value=raw):
        r = tier.handle("book it")
    assert skill.called_with is None
    assert r.proposal.args == {"start": "S", "end": "E"}    # unknown key filtered out


def test_handle_no_skill_falls_through_to_chat():
    tier, _ = _tier_with_book()
    with patch.object(tier, "_complete",
                      side_effect=['{"skill":"none","args":{}}', "just chatting"]):
        r = tier.handle("hello there")
    assert r.proposal is None
    assert r.text == "just chatting"


# ---------------------------------------------------------------------------
# ti-dp7p — chitchat/Q&A must fall through to 'none'; EchoSkill removed from
# default registry; dispatch prompt must carry action-vs-conversation bias.
# ---------------------------------------------------------------------------

import json as _json

from iris.skills import TimeSkill, default_registry


def _time_tier() -> "Tier1Qwen":
    return Tier1Qwen(Config(), skills=SkillRegistry([TimeSkill()]))


def test_echo_not_in_default_registry():
    """EchoSkill must not appear in the default registry (demo-only, not production)."""
    assert "echo" not in default_registry().names()


def test_dispatch_prompt_has_chitchat_bias():
    """Dispatch prompt must include an action-vs-conversation instruction and chitchat examples."""
    prompt = _time_tier()._dispatch_prompt("how are you?")
    lowered = prompt.lower()
    assert "action" in lowered or "command" in lowered or "conversation" in lowered or "chitchat" in lowered
    # at least one chitchat-→-none few-shot example must be present
    assert "none" in prompt and (
        "how are you" in lowered or "fun fact" in lowered or "otter" in lowered
    )


@pytest.mark.parametrize("utterance", [
    "how are you doing today?",
    "tell me a fun fact about otters",
    "what do you think about jazz",
    "do you like dogs",
])
def test_chitchat_dispatches_to_none(utterance):
    """Chitchat/Q&A utterances must route to 'none' → fall through to chat reply."""
    tier = _time_tier()
    chat_reply = "That sounds fun!"
    with patch.object(tier, "_complete", side_effect=[
        '{"skill":"none","args":{}}', chat_reply
    ]):
        r = tier.handle(utterance)
    assert r.proposal is None
    assert r.text == chat_reply


@pytest.mark.parametrize("utterance,expected_skill", [
    ("what time is it", "time"),
])
def test_command_dispatches_to_correct_skill(utterance, expected_skill):
    """Explicit action utterances must route to the matching skill."""
    tier = _time_tier()
    raw = _json.dumps({"skill": expected_skill, "args": {}})
    with patch.object(tier, "_complete", return_value=raw):
        r = tier.handle(utterance)
    assert r.proposal is not None
    assert r.proposal.skill == expected_skill
