"""Conversation context — window + gist tiers for a single call.

Two-tier in-process memory:

  Window   deque(maxlen=12) — most recent ≤12 turns, exact text.
  Gist     Qwen-compressed summary of evicted turns; async, non-blocking.

``ConversationContext.lookup(query)`` searches window then gist and returns a
``LookupResult`` with a tier-appropriate prefix and a full ranked match list.

Reply prefixes — verbatim, PM-locked:
  WINDOW_PREFIX  = "From earlier in the call:"
  GIST_PREFIX    = "According to my notes from earlier:"
  NO_MATCH_REPLY = "I don't have that in my notes — could you ask her to repeat it?"

Gist hedging: when a gist match contains digit numbers, written amounts,
proper names, or alphanumeric codes, ``LookupResult.hedged`` is True and
"— you may want to confirm that." is appended to the reply.

Privacy notice: ``PRIVACY_NOTICE`` is emitted via the ``emit`` callback once on
the first ``add()`` call as ``("context", "privacy_notice", PRIVACY_NOTICE)``.
"""
from __future__ import annotations

import re
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

WINDOW_PREFIX = "From earlier in the call:"
GIST_PREFIX = "According to my notes from earlier:"
PRIVACY_NOTICE = "Context memory: local only."
NO_MATCH_REPLY = "I don't have that in my notes — could you ask her to repeat it?"

# High-precision fields: digit numbers, written amounts, proper names, codes.
_HEDGE_PATTERN = re.compile(
    r"\b\d[\d.,]*\b"                           # digit numbers (42, $80,000)
    r"|\b(?:"                                   # written-out amounts:
    r"zero|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|"
    r"eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|"
    r"eighty|ninety|hundred|thousand|million|billion|"
    r"dollars?|cents?|pounds?"
    r")\b"
    r"|\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b"   # proper names (Sarah Johnson)
    r"|\b[A-Z]{2,}[-]?\d+\b"                   # codes (RL-4492, ABC123)
    r"|\b\d{4,}\b",                             # long standalone numbers
)

_STOP_WORDS = frozenset({
    "a", "an", "the", "is", "it", "at", "what", "was", "did", "you",
    "mean", "about", "how", "which", "that", "there", "and", "or",
    "but", "of", "in", "on", "to", "for", "with", "he", "she", "we",
    "they", "i", "be", "been", "are", "were",
})


@dataclass(frozen=True)
class ContextTurn:
    """One exchange in the conversation. ``speaker`` is immutable after creation."""
    speaker: str
    text: str


@dataclass
class LookupMatch:
    text: str
    speaker: str
    tier: Literal["window", "gist"]
    score: float


@dataclass
class LookupResult:
    """Return value of ``ConversationContext.lookup()``."""
    tier: Literal["window", "gist", "none"]
    reply: str
    matches: list[LookupMatch]
    hedged: bool = False


def _score(query: str, text: str) -> float:
    q_words = {w for w in query.lower().split() if w not in _STOP_WORDS}
    t_words = set(text.lower().split())
    if not q_words:
        return 0.0
    return len(q_words & t_words) / len(q_words)


class ConversationContext:
    """Rolling window + async gist — in-process memory for one call.

    Parameters
    ----------
    compress:
        Optional callable ``(prompt: str) -> str`` called on a background thread
        when turns age out of the window. ``None`` disables gist compression.
    emit:
        Optional callback for console events. Receives tuples:
        ``("context", "privacy_notice", PRIVACY_NOTICE)`` on first add;
        ``("context", "gist_updated", new_gist)`` after each compression.
    """

    WINDOW_MAXLEN = 12

    def __init__(
        self,
        compress: Callable[[str], str] | None = None,
        emit: Callable | None = None,
    ) -> None:
        self._window: deque[ContextTurn] = deque(maxlen=self.WINDOW_MAXLEN)
        self._gist: str = ""
        self._gist_lock = threading.Lock()
        self._gist_active: bool = False
        self._compress = compress
        self._emit = emit or (lambda *_: None)
        self._privacy_fired: bool = False

    # --- public API ---

    def add(self, speaker: str, text: str, *,
            timestamp: float | None = None) -> None:
        """Record a turn.  Fires the privacy notice on first call."""
        if not self._privacy_fired:
            self._emit(("context", "privacy_notice", PRIVACY_NOTICE))
            self._privacy_fired = True

        evicted: ContextTurn | None = None
        if len(self._window) >= self.WINDOW_MAXLEN:
            evicted = self._window[0]

        self._window.append(ContextTurn(speaker=speaker, text=text))

        if evicted is not None and self._compress is not None:
            threading.Thread(
                target=self._compress_turn, args=(evicted,),
                daemon=True, name="iris-gist",
            ).start()

    def lookup(self, query: str) -> LookupResult:
        """Find the most relevant context for ``query``.

        Tier order: window → gist → no-match.
        Verbal reply (``LookupResult.reply``) caps at 2 options (joined by "; ").
        ``LookupResult.matches`` carries the full ranked list for console annotation.
        """
        # --- window ---
        scored: list[tuple[float, ContextTurn]] = []
        for turn in reversed(self._window):
            s = _score(query, turn.text)
            if s > 0:
                scored.append((s, turn))
        scored.sort(key=lambda x: x[0], reverse=True)

        if scored:
            matches = [
                LookupMatch(t.text, t.speaker, "window", s)
                for s, t in scored
            ]
            top2 = [t for _, t in scored[:2]]
            verbal_body = "; ".join(t.text for t in top2)
            return LookupResult(
                tier="window",
                reply=f"{WINDOW_PREFIX} {verbal_body}",
                matches=matches,
            )

        # --- gist ---
        with self._gist_lock:
            gist = self._gist
            gist_active = self._gist_active

        if gist_active and gist and _score(query, gist) > 0:
            hedged = bool(_HEDGE_PATTERN.search(gist))
            reply = f"{GIST_PREFIX} {gist}"
            if hedged:
                reply += " — you may want to confirm that."
            return LookupResult(
                tier="gist",
                reply=reply,
                matches=[LookupMatch(gist, "iris", "gist", _score(query, gist))],
                hedged=hedged,
            )

        return LookupResult(tier="none", reply=NO_MATCH_REPLY, matches=[])

    # --- properties ---

    @property
    def window_size(self) -> int:
        return len(self._window)

    @property
    def gist_active(self) -> bool:
        with self._gist_lock:
            return self._gist_active

    @property
    def gist(self) -> str:
        with self._gist_lock:
            return self._gist

    # --- background gist compression ---

    def _compress_turn(self, evicted: ContextTurn) -> None:
        with self._gist_lock:
            current = self._gist
        prompt = (
            f"Summarize a phone call so far. "
            f"Current summary: {current!r}. "
            f"New turn to incorporate — {evicted.speaker}: {evicted.text!r}. "
            f"Write an updated summary (one or two sentences, under 80 words)."
        )
        try:
            new_gist = self._compress(prompt)
        except Exception:  # noqa: BLE001
            return
        with self._gist_lock:
            self._gist = new_gist
            self._gist_active = True
        self._emit(("context", "gist_updated", new_gist))
