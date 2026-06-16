"""Pure-logic helpers for the Contacts panel — no Textual imports.

Extracted so tests can import and validate them without the optional
textual dependency.
"""
from __future__ import annotations

_NOTES_MAX: int = 600
_NOTES_WARN: int = 500

_HANDLING_RULES: list[str] = ["normal", "vip", "screen", "take_message", "block"]


def rule_badge(rule: str) -> str:
    """Return Rich markup for a handling-rule badge."""
    _map = {
        "vip": "[b magenta]VIP[/]",
        "take_message": "[b blue]MSG[/]",
        "screen": "[b yellow]SCREEN[/]",
        "block": "[b red]BLOCK[/]",
        "normal": "normal",
    }
    return _map.get(rule, rule)


def char_counter_text(n: int) -> str:
    """Return counter markup with optional near-limit warning."""
    if n >= _NOTES_MAX:
        return f"[b red]{n}/{_NOTES_MAX} — LIMIT REACHED[/]"
    if n >= _NOTES_WARN:
        return f"[b yellow]{n}/{_NOTES_MAX} — getting long[/]"
    return f"{n}/{_NOTES_MAX}"
