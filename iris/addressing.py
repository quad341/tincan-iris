"""Wake-word addressing — decide if speech was meant for Iris.

In always-on / call mode the mic feeds Iris continuously, so she must act only
when *addressed* ("Iris, …"), not on every word of the conversation. This is
beyond VAD: VAD finds speech; addressing decides whether it was for her. See the
supervised-co-pilot memory.
"""
from __future__ import annotations

import re

# "Iris …" / "hey Iris …" / "ok Iris …" at the start, then the command. Tolerant
# of the comma/pause after the name. Anchored at the start so a stray "iris" mid-
# sentence ("I told Iris …") doesn't trigger her.
_ADDRESS = re.compile(
    r"^\s*(?:hey|ok|okay|hi|hello)?\s*iris\b[\s,.:;!?-]*(.*)", re.IGNORECASE
)


def address(text: str) -> str | None:
    """If ``text`` is addressed to Iris, return the command with the wake word
    stripped (a bare "Iris" returns ""); otherwise return None (not for her)."""
    m = _ADDRESS.match(text or "")
    if m is None:
        return None
    return m.group(1).strip()
