"""Live smoke: qwen actually dispatches natural language to a registered skill.

The dispatch test skips when no qwen server answers on the configured base URL,
so CI (no model) passes; on a box with llama.cpp up it verifies the real path.
"""
from __future__ import annotations

import pytest


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
