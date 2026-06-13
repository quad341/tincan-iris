"""Filler phrases for masking latency.

A pool of natural pauses, picked at random with no immediate repeat, so a long
wait doesn't sound like an obvious automated loop. Printed in the REPL; spoken
in voice mode.
"""
from __future__ import annotations

import random
from collections.abc import Callable

FILLERS = [
    "umm, one sec",
    "let me think",
    "hmm, hang on",
    "just a moment",
    "give me a second",
    "let me see",
    "one moment",
    "okay, let me check",
    "hmm",
    "uh, hold on",
    "let me look into that",
    "bear with me",
    "right, let me check on that",
    "just a sec",
    "hold on a moment",
    "hmm, okay",
]


def filler_picker() -> Callable[[], str]:
    """Return a callable yielding a random filler, never the same one twice running."""
    state: dict[str, str | None] = {"last": None}

    def pick() -> str:
        choices = [f for f in FILLERS if f != state["last"]] or FILLERS
        chosen = random.choice(choices)
        state["last"] = chosen
        return chosen

    return pick
