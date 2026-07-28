"""Pure-logic tests for contacts panel helpers — no Textual required.

These run in CI regardless of whether textual is installed.
"""
from __future__ import annotations

from iris.console.contacts_logic import (
    _NOTES_MAX,
    _NOTES_WARN,
    char_counter_text,
    rule_badge,
)

# ---------------------------------------------------------------------------
# rule_badge
# ---------------------------------------------------------------------------

def test_rule_badge_ring_with_announcement():
    badge = rule_badge("ring_with_announcement")
    assert "ANNOUNCE" in badge
    assert "magenta" in badge.lower()


def test_rule_badge_take_message():
    badge = rule_badge("take_message")
    assert "MSG" in badge
    assert "blue" in badge.lower()


def test_rule_badge_screen():
    badge = rule_badge("screen")
    assert "SCREEN" in badge
    assert "yellow" in badge.lower()


def test_rule_badge_ignore():
    badge = rule_badge("ignore")
    assert "IGNORE" in badge
    assert "red" in badge.lower()


def test_rule_badge_ring_through():
    badge = rule_badge("ring_through")
    assert badge == "ring through"


def test_rule_badge_unknown_passthrough():
    assert rule_badge("totally_unknown") == "totally_unknown"


# ---------------------------------------------------------------------------
# char_counter_text
# ---------------------------------------------------------------------------

def test_char_counter_under_warn():
    text = char_counter_text(100)
    assert "100/600" in text
    assert "yellow" not in text.lower()
    assert "red" not in text.lower()


def test_char_counter_at_warn_threshold():
    text = char_counter_text(_NOTES_WARN)
    assert "yellow" in text.lower()
    assert "long" in text.lower()


def test_char_counter_above_warn():
    text = char_counter_text(_NOTES_WARN + 10)
    assert "yellow" in text.lower()


def test_char_counter_at_limit():
    text = char_counter_text(_NOTES_MAX)
    assert "red" in text.lower()
    assert "LIMIT" in text


def test_char_counter_over_limit():
    text = char_counter_text(_NOTES_MAX + 50)
    assert "red" in text.lower()


def test_char_counter_zero():
    text = char_counter_text(0)
    assert "0/600" in text
