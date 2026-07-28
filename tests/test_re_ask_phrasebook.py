"""Tests for iris/re_ask_phrasebook.py — ti-rcn9.1 / ti-rcn9.2 acceptance criteria.

Covers EN pattern set, ES pattern set, long-utterance guard, and
supported_languages() helper.
"""
from __future__ import annotations

import pytest

from iris.re_ask_phrasebook import is_re_ask, supported_languages

# --- EN happy-path -----------------------------------------------------------

@pytest.mark.parametrize("text", [
    "What?",
    "Sorry?",
    "Could you repeat that?",
    "I didn't hear that",
    "Say that again",
    "Excuse me",
    "Hm",
])
def test_en_re_ask_phrases(text):
    assert is_re_ask(text, lang="en") is True


def test_en_non_re_ask():
    assert is_re_ask("Tell me more about the contract terms", lang="en") is False


# --- ES happy-path -----------------------------------------------------------

@pytest.mark.parametrize("text", [
    "¿Qué?",
    "Perdón",
    "¿Puede repetir eso?",
    "No escuché",
    "Eh",
])
def test_es_re_ask_phrases(text):
    assert is_re_ask(text, lang="es") is True


def test_es_non_re_ask():
    assert is_re_ask("Cuéntame más sobre los términos del contrato", lang="es") is False


# --- Long-utterance guard (7+ words never match anchored patterns) -----------

@pytest.mark.parametrize("text", [
    "Could you please say that one more time for me",
    "Sorry I did not quite catch what you just said",
    "What was it that you were trying to tell me again",
])
def test_long_utterances_are_not_re_ask(text):
    assert is_re_ask(text) is False


# --- Default lang is 'en' ----------------------------------------------------

def test_default_lang_is_en():
    assert is_re_ask("What?") is True
    assert is_re_ask("Tell me more about the contract terms") is False


# --- supported_languages() ---------------------------------------------------

def test_supported_languages_contains_en_and_es():
    langs = supported_languages()
    assert isinstance(langs, frozenset)
    assert "en" in langs
    assert "es" in langs
