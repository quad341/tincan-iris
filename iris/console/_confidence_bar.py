"""Confidence bar renderer — no Textual dependency, importable standalone."""
from __future__ import annotations

_BAR_WIDTH = 10


def render_confidence_bar(confidence: float) -> str:
    """Render a rounded-integer confidence bar with bucket colour.

    Buckets (operator decision 2026-06-30): >=85% green, 60-84% amber, <60% red.
    """
    pct = round(confidence * 100)
    filled = round(pct * _BAR_WIDTH / 100)
    bar = "▓" * filled + "░" * (_BAR_WIDTH - filled)
    if pct >= 85:
        color = "green"
    elif pct >= 60:
        color = "#f59e0b"
    else:
        color = "red"
    return f"[{color}]{pct}% {bar}[/{color}]"
