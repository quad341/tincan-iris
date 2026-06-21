"""Tests for wake-word addressing."""
from __future__ import annotations

from iris.addressing import address


def test_strips_wake_word_and_punctuation():
    assert address("hey Iris, what time is it?") == "what time is it?"
    assert address("hey iris introduce yourself") == "introduce yourself"
    assert address("ok Iris - stop") == "stop"


def test_case_insensitive():
    assert address("hey IRIS stop") == "stop"


def test_prefixed_bare_hail_returns_empty_string():
    assert address("hey iris") == ""
    assert address("ok Iris") == ""


def test_bare_iris_without_prefix_does_not_trigger():
    # a prefix is required now, so a bare "Iris" is no longer addressed
    assert address("Iris") is None
    assert address("Iris, what time is it?") is None


def test_not_addressed_returns_none():
    assert address("what time is it") is None
    assert address("tell her something") is None
    assert address("") is None


def test_stray_iris_midsentence_does_not_trigger():
    assert address("I told Iris about it") is None
