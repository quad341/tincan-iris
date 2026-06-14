"""Tests for wake-word addressing."""
from __future__ import annotations

from iris.addressing import address


def test_strips_wake_word_and_punctuation():
    assert address("Iris, what time is it?") == "what time is it?"
    assert address("hey iris introduce yourself") == "introduce yourself"
    assert address("ok Iris - stop") == "stop"


def test_case_insensitive():
    assert address("IRIS stop") == "stop"


def test_bare_hail_returns_empty_string():
    assert address("Iris") == ""
    assert address("hey iris") == ""


def test_not_addressed_returns_none():
    assert address("what time is it") is None
    assert address("tell her something") is None
    assert address("") is None


def test_stray_iris_midsentence_does_not_trigger():
    assert address("I told Iris about it") is None
