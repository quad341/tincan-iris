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


def test_wake_word_anywhere_triggers():
    # The prefix ("hey/ok/hi" + iris) doesn't occur in natural speech, so wherever
    # it appears it's an invocation — even after filler or deep in an utterance
    # (ti-nir1). Everything after the wake phrase is the command.
    assert address("um, hey iris, introduce yourself") == "introduce yourself"
    assert address("so anyway hey iris call mom") == "call mom"
    assert address("uh hey Iris stop") == "stop"
    assert address("and then I said hey iris call mom") == "call mom"


def test_prefix_substring_does_not_falsely_trigger():
    # \b word-boundary guard: "they"/"this" must not match "hey"/"hi".
    assert address("they iris around all day") is None
    assert address("this iris is pretty") is None
