"""Tests for PreferencesStore and the Brain prefs hook."""
from __future__ import annotations


import pytest

from iris.prefs import PreferencesStore


@pytest.fixture
def store(tmp_path):
    return PreferencesStore(tmp_path / "prefs.json")


# --- PreferencesStore ---

def test_set_and_get(store):
    store.set("contact:mom", "tone", "warm")
    assert store.get("contact:mom", "tone") == "warm"


def test_get_default(store):
    assert store.get("contact:nobody", "tone", "neutral") == "neutral"


def test_get_default_empty_string(store):
    assert store.get("contact:nobody", "tone") == ""


def test_get_all_empty(store):
    assert store.get_all("contact:nobody") == {}


def test_get_all_returns_copy(store):
    store.set("ctx", "k", "v")
    d = store.get_all("ctx")
    d["k"] = "CHANGED"
    assert store.get("ctx", "k") == "v"


def test_set_multiple_keys(store):
    store.set("ctx", "tone", "casual")
    store.set("ctx", "formality", "informal")
    prefs = store.get_all("ctx")
    assert prefs == {"tone": "casual", "formality": "informal"}


def test_set_overwrites_existing(store):
    store.set("ctx", "tone", "formal")
    store.set("ctx", "tone", "casual")
    assert store.get("ctx", "tone") == "casual"


def test_delete_key(store):
    store.set("ctx", "tone", "warm")
    assert store.delete("ctx", "tone") is True
    assert store.get("ctx", "tone") == ""


def test_delete_last_key_removes_context(store):
    store.set("ctx", "tone", "warm")
    store.delete("ctx", "tone")
    assert "ctx" not in store.contexts()


def test_delete_missing_key_returns_false(store):
    assert store.delete("ctx", "nosuchkey") is False


def test_hint_empty_when_no_prefs(store):
    assert store.hint("ctx") == ""


def test_hint_formats_key_value_pairs(store):
    store.set("ctx", "tone", "warm")
    store.set("ctx", "formality", "informal")
    hint = store.hint("ctx")
    assert "tone: warm" in hint
    assert "formality: informal" in hint


def test_contexts_lists_known_contexts(store):
    store.set("alpha", "k", "v")
    store.set("beta", "k", "v")
    assert set(store.contexts()) == {"alpha", "beta"}


def test_persists_across_instances(tmp_path):
    path = tmp_path / "p.json"
    s1 = PreferencesStore(path)
    s1.set("ctx", "tone", "warm")
    s2 = PreferencesStore(path)
    assert s2.get("ctx", "tone") == "warm"


# --- Brain prefs hook ---

from iris.brain import Brain  # noqa: E402
from iris.config import Config  # noqa: E402
from iris.skills import SkillRegistry  # noqa: E402


def _brain_no_net(tmp_path):
    """Brain with empty skill registry and injected tmp prefs — no network."""
    prefs = PreferencesStore(tmp_path / "prefs.json")
    brain = Brain(
        cfg=Config(),
        skills=SkillRegistry(),   # empty — no Qwen needed for tier0 tests
        prefs=prefs,
    )
    return brain, prefs


def test_set_pref_writes_to_store(tmp_path):
    brain, prefs = _brain_no_net(tmp_path)
    brain.call_context = "contact:mom"
    brain.set_pref("tone", "casual")
    assert prefs.get("contact:mom", "tone") == "casual"


def test_set_pref_explicit_context(tmp_path):
    brain, prefs = _brain_no_net(tmp_path)
    brain.set_pref("tone", "formal", context="contact:work")
    assert prefs.get("contact:work", "tone") == "formal"


def test_set_pref_noop_without_context(tmp_path):
    brain, prefs = _brain_no_net(tmp_path)
    brain.set_pref("tone", "warm")  # call_context not set
    assert prefs.contexts() == []


def test_respond_threads_hint_to_tier1(tmp_path):
    """Brain passes the prefs hint to Tier1Qwen when a call context is active."""
    prefs = PreferencesStore(tmp_path / "p.json")
    prefs.set("contact:mom", "tone", "warm")
    brain = Brain(cfg=Config(), skills=SkillRegistry(), prefs=prefs)
    brain.call_context = "contact:mom"

    captured: list = []

    def fake_handle(text, *, allow_skills=True, context_hint="", speaker=""):
        captured.append(context_hint)
        from iris.lanes import LaneResult
        return LaneResult("ok", "tier1-qwen")

    brain.tier1.handle = fake_handle
    brain.respond("say something")
    assert captured and "tone: warm" in captured[0]
