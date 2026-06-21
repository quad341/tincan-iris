"""Wake-word addressing — decide if speech was meant for Iris.

In always-on / call mode the mic feeds Iris continuously, so she must act only
when *addressed* ("Iris, …"), not on every word of the conversation. This is
beyond VAD: VAD finds speech; addressing decides whether it was for her. See the
supervised-co-pilot memory.
"""
from __future__ import annotations

import re

# "hey Iris …" / "ok Iris …" / "hi Iris …" at the start, then the command. A
# prefix (hey/ok/okay/hi/hello) is REQUIRED, so a bare "Iris" — or "iris" spoken
# mid-conversation ("I told Iris …", "ask Iris about it") — does NOT trigger her.
# Tolerant of the comma/pause after the name.
_ADDRESS = re.compile(
    r"^\s*(?:hey|ok|okay|hi|hello)\s+iris\b[\s,.:;!?-]*(.*)", re.IGNORECASE
)


def address(text: str) -> str | None:
    """If ``text`` is addressed to Iris (a required prefix + "Iris", e.g.
    "hey Iris …"), return the command with the wake word stripped; otherwise
    return None — including a bare "Iris" with no prefix (not for her)."""
    m = _ADDRESS.match(text or "")
    if m is None:
        return None
    return m.group(1).strip()
