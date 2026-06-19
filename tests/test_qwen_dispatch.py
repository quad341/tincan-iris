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


def test_dispatch_passes_multiple_args_to_skill():
    tier, skill = _tier_with_book()
    raw = '{"skill":"book","args":{"start":"2026-06-19T15:00:00","end":"2026-06-19T16:00:00"}}'
    with patch.object(tier, "_complete", return_value=raw):
        r = tier.handle("am I free at 3pm?")
    assert skill.called_with == {"start": "2026-06-19T15:00:00", "end": "2026-06-19T16:00:00"}
    assert r.skill == "book"
    assert "booked" in r.text


def test_dispatch_drops_unknown_args():
    tier, skill = _tier_with_book()
    raw = '{"skill":"book","args":{"start":"S","end":"E","bogus":"x"}}'
    with patch.object(tier, "_complete", return_value=raw):
        r = tier.handle("book it")
    # unknown key filtered -> no TypeError, skill still called with its declared params
    assert skill.called_with == {"start": "S", "end": "E"}
    assert r.skill == "book"


def test_dispatch_missing_required_arg_degrades_gracefully():
    tier, skill = _tier_with_book()
    with patch.object(tier, "_complete", return_value='{"skill":"book","args":{}}'):
        r = tier.handle("book something")
    assert skill.called_with is None                    # not run with bad args
    assert r.skill == "book"
    assert "another way" in r.text.lower() or "didn't catch" in r.text.lower()


class _TupleSkill:
    """A skill that returns (spoken_reply, console_annotation) like the calendar
    skills do — the spoken half must reach the user, the annotation must not."""

    name = "checkcal"
    description = "Check the calendar."
    params = [SkillParam(name="when", type="string", description="ISO time")]

    def run(self, *, when):
        return ("That time looks free.", f"[calendar: free/busy — {when}]")


def test_dispatch_collapses_tuple_reply_to_spoken_half():
    tier = Tier1Qwen(Config(), skills=SkillRegistry([_TupleSkill()]))
    raw = '{"skill":"checkcal","args":{"when":"2026-06-19T15:00:00"}}'
    with patch.object(tier, "_complete", return_value=raw):
        r = tier.handle("am I free at 3pm?")
    assert r.text == "That time looks free."            # annotation dropped, not spoken
    assert "[calendar" not in r.text                    # console annotation never leaks to TTS
    assert r.skill == "checkcal"
