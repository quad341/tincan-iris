"""Tests for IrisMode, ModeManager, ScopeManifest, and Brain punt routing (ti-6qsb.2).

These tests FAIL until the builder implements iris/mode.py, iris/scope.py,
and the punt path in iris/brain.py.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from iris.mode import IrisMode, ModeManager
from iris.scope import ScopeManifest


# ---------------------------------------------------------------------------
# IrisMode transitions + ModeManager callbacks
# ---------------------------------------------------------------------------

def test_mode_manager_initial_mode_is_out_of_call():
    mm = ModeManager()
    assert mm.mode is IrisMode.OUT_OF_CALL


def test_mode_manager_transition_fires_callback():
    mm = ModeManager()
    fired = []
    mm.on_mode_change(lambda new: fired.append(new))
    mm.set_mode(IrisMode.IN_CALL)
    assert fired == [IrisMode.IN_CALL]


def test_mode_manager_multiple_callbacks_all_fired():
    mm = ModeManager()
    results = []
    mm.on_mode_change(lambda n: results.append(("cb1", n)))
    mm.on_mode_change(lambda n: results.append(("cb2", n)))
    mm.set_mode(IrisMode.IN_CALL)
    assert len(results) == 2
    assert ("cb1", IrisMode.IN_CALL) in results
    assert ("cb2", IrisMode.IN_CALL) in results


def test_mode_manager_no_callback_on_same_mode():
    mm = ModeManager()
    fired = []
    mm.on_mode_change(lambda o, n: fired.append(n))
    mm.set_mode(IrisMode.OUT_OF_CALL)  # same as initial
    assert fired == []


def test_mode_manager_set_in_call_then_back():
    mm = ModeManager()
    mm.set_mode(IrisMode.IN_CALL)
    assert mm.mode is IrisMode.IN_CALL
    mm.set_mode(IrisMode.OUT_OF_CALL)
    assert mm.mode is IrisMode.OUT_OF_CALL


# ---------------------------------------------------------------------------
# ScopeManifest.what_i_do()
# Builder must change return type from str to domain-grouped dict[str, list[str]]
# ---------------------------------------------------------------------------

def test_what_i_do_returns_non_empty_dict():
    sm = ScopeManifest()
    result = sm.what_i_do()
    assert isinstance(result, dict), "what_i_do() must return a domain-grouped dict"
    assert len(result) > 0


def test_what_i_do_is_domain_grouped():
    sm = ScopeManifest()
    result = sm.what_i_do()
    # Each value should be a non-empty list/iterable of capability strings
    for domain, capabilities in result.items():
        assert domain  # non-empty domain key
        assert capabilities  # non-empty capability list


def test_what_i_do_includes_messages_domain():
    sm = ScopeManifest()
    result = sm.what_i_do()
    domains = {k.lower() for k in result}
    assert any("message" in d or "call" in d for d in domains)


def test_what_i_do_includes_calendar_domain():
    sm = ScopeManifest()
    result = sm.what_i_do()
    domains = {k.lower() for k in result}
    assert any("calendar" in d or "schedule" in d or "event" in d or "time" in d
               for d in domains)


# ---------------------------------------------------------------------------
# ScopeManifest.is_explicit_model_request()
# ---------------------------------------------------------------------------

def test_is_explicit_model_request_matches_ask_haiku():
    sm = ScopeManifest()
    assert sm.is_explicit_model_request("ask Haiku about the weather") is True


def test_is_explicit_model_request_matches_ask_qwen():
    sm = ScopeManifest()
    assert sm.is_explicit_model_request("ask Qwen what is two plus two") is True


def test_is_explicit_model_request_matches_search():
    sm = ScopeManifest()
    assert sm.is_explicit_model_request("search for coffee shops near me") is True


def test_is_explicit_model_request_case_insensitive():
    sm = ScopeManifest()
    assert sm.is_explicit_model_request("ASK HAIKU about cats") is True


def test_is_explicit_model_request_does_not_match_normal_query():
    sm = ScopeManifest()
    assert sm.is_explicit_model_request("what time is it") is False


def test_is_explicit_model_request_does_not_match_message_check():
    sm = ScopeManifest()
    assert sm.is_explicit_model_request("do I have any messages") is False


def test_is_explicit_model_request_does_not_match_call_back():
    sm = ScopeManifest()
    assert sm.is_explicit_model_request("call Bob back") is False


# ---------------------------------------------------------------------------
# Brain routes scope queries to ScopeManifest without calling Qwen
# ---------------------------------------------------------------------------

def test_brain_what_can_you_do_does_not_call_tier1():
    from iris.brain import Brain
    from iris.config import Config

    b = Brain(Config())
    b.tier1 = MagicMock()
    b.tier2 = MagicMock()

    with patch("iris.brain.run_with_masking", side_effect=lambda work, **_: work()):
        b.respond("what can you do")

    b.tier1.handle.assert_not_called()


def test_brain_help_query_returns_scope_manifest_content():
    from iris.brain import Brain
    from iris.config import Config

    b = Brain(Config())
    b.tier1 = MagicMock()
    b.tier2 = MagicMock()

    with patch("iris.brain.run_with_masking", side_effect=lambda work, **_: work()):
        reply = b.respond("what can you do")

    # Response should list domains, not delegate to Qwen
    assert reply.text  # non-empty
    b.tier1.handle.assert_not_called()


# ---------------------------------------------------------------------------
# Punt routing — HomeApp appends punt offer for off-scope queries
# The punt offer text must be accessible so HomeApp can append it.
# Builder must expose punt_offer(text) on ScopeManifest or a sibling method.
# ---------------------------------------------------------------------------

def test_punt_text_mentions_ask_haiku():
    """ScopeManifest (or HomeApp helper) provides a punt offer text."""
    sm = ScopeManifest()
    # Builder adds punt_offer(text) -> str
    punt = sm.punt_offer("what's the weather today")
    assert "ask" in punt.lower()
    assert "haiku" in punt.lower() or "model" in punt.lower()


def test_punt_text_not_empty_for_off_scope():
    sm = ScopeManifest()
    punt = sm.punt_offer("random off-scope question")
    assert punt.strip()


def test_punt_not_appended_for_explicit_model_request():
    """When the user already asked an explicit model request, no punt is needed."""
    sm = ScopeManifest()
    punt = sm.punt_offer("ask Haiku about Paris")
    # punt_offer returns empty string for explicit requests
    assert not punt
