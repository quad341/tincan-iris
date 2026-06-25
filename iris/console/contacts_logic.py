"""Pure-logic helpers for the Contacts panel — no Textual imports.

Extracted so tests can import and validate them without the optional
textual dependency.
"""
from __future__ import annotations

_NOTES_MAX: int = 600
_NOTES_WARN: int = 500

_HANDLING_RULES: list[str] = [
    "ring_through",
    "ring_with_announcement",
    "screen",
    "take_message",
    "ignore",
]


def rule_badge(rule: str) -> str:
    """Return Rich markup for a handling-rule badge."""
    _map = {
        "ring_with_announcement": "[b magenta]ANNOUNCE[/]",
        "take_message":           "[b blue]MSG[/]",
        "screen":                 "[b yellow]SCREEN[/]",
        "ignore":                 "[b red]IGNORE[/]",
        "ring_through":           "ring through",
    }
    return _map.get(rule, rule)


VERB_DESCRIPTION: dict[str, str] = {
    "ring_with_announcement": "Iris announced caller by voice. Phone is ringing — Iris has NOT answered.",
    "ring_through":           "Phone is ringing. Iris has NOT answered.",
    "screen":                 "Iris answered and is screening the caller.",
    "take_message":           "Iris answered and is taking a message.",
}


def char_counter_text(n: int) -> str:
    """Return counter markup with optional near-limit warning."""
    if n >= _NOTES_MAX:
        return f"[b red]{n}/{_NOTES_MAX} — LIMIT REACHED[/]"
    if n >= _NOTES_WARN:
        return f"[b yellow]{n}/{_NOTES_MAX} — getting long[/]"
    return f"{n}/{_NOTES_MAX}"
