"""Wake-word addressing — decide if speech was meant for Iris.

In always-on / call mode the mic feeds Iris continuously, so she must act only
when *addressed* ("Iris, …"), not on every word of the conversation. This is
beyond VAD: VAD finds speech; addressing decides whether it was for her. See the
supervised-co-pilot memory.
"""
from __future__ import annotations

import re

# A prefix (hey/ok/okay/hi/hello) + "iris" is REQUIRED. That phrase doesn't occur
# in natural speech, so WHEREVER it appears it's an intended invocation — we scan
# the whole utterance for it (``search``), not just the start. This fixes the
# fragile turn-timing where STT prepends filler ("um", "so anyway") or the tail of
# the previous phrase and a strict start-anchor silently dropped the command.
# Everything after the wake phrase is the command. The ``\b`` keeps "they"/"this"
# from matching "hey"/"hi"; a bare "Iris" (no prefix) still never triggers. The
# dial skill's two-phase "shall I dial?" backstops the rare narrated invocation.
_ADDRESS = re.compile(
    r"\b(?:hey|ok|okay|hi|hello)[\s,]+iris\b[\s,.:;!?-]*(.*)",
    re.IGNORECASE,
)


def address(text: str) -> str | None:
    """If ``text`` is addressed to Iris (a required prefix + "Iris", e.g.
    "hey Iris …"), return the command with the wake word stripped; otherwise
    return None — including a bare "Iris" with no prefix (not for her)."""
    m = _ADDRESS.search(text or "")
    if m is None:
        return None
    return m.group(1).strip()
