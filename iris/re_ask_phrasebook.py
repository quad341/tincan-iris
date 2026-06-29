"""Tier-0 re-ask phrase detection.

Matches common far-party utterances that signal the caller did not catch the
last thing Iris said (e.g. "What?", "Could you repeat that?", "Pardon?").
Used by Brain.respond() to set Reply.re_ask=True and trigger cadence slow-mode.

Language support (BCP-47):
  en — v1 (ti-rcn9.1)
  es — v1 (ti-rcn9.2)

To add a language: add an entry to _PATTERNS with a compiled Pattern.
Brain.respond() will use the pattern for Brain._locked_language, falling back
to English. When Config.language_set lands (ti-140k), Brain.__init__() can
pre-filter to the configured set.
"""
from __future__ import annotations

import re

_PATTERNS: dict[str, re.Pattern[str]] = {
    "en": re.compile(
        r"^(?:"
        r"what(?:\s+(?:did\s+you\s+say|was\s+that|do\s+you\s+mean))?"
        r"|sorry"
        r"|pardon(?:\s+me)?"
        r"|(?:could|can)\s+you\s+(?:please\s+)?repeat\s+that"
        r"|i\s+(?:didn't|did\s+not)\s+(?:hear|catch)\s+(?:that|you)"
        r"|(?:say|come)\s+(?:that\s+)?again"
        r"|(?:hm+|huh)"
        r"|repeat\s+that"
        r"|excuse\s+me"
        r")[\s?!.]*$",
        re.IGNORECASE,
    ),
    "es": re.compile(
        r"^(?:"
        r"(?:¿\s*)?(?:qué|que)(?:\s+(?:dijo(?:\s+usted)?|dijiste|fue\s+eso))?"
        r"|(?:¿\s*)?cómo(?:\s+dice)?"
        r"|perd[oó]n(?:e(?:\s+me)?)?"
        r"|disculpe?(?:\s+me)?"
        r"|(?:¿\s*)?(?:puede|podr[ií]a|pod[eé]s|puedes)\s+repetir\s+(?:eso|lo\s+que\s+dijo)?"
        r"|no\s+(?:escuché|oí|entendí|lo\s+oí)"
        r"|repita\s+(?:eso|por\s+favor)?"
        r"|(?:eh+|mm+|hmm+)"
        r")[\s?!.]*$",
        re.IGNORECASE,
    ),
}

_FALLBACK = _PATTERNS["en"]


def is_re_ask(text: str, lang: str = "en") -> bool:
    """Return True when *text* matches a known re-ask phrase for *lang*.

    Falls back to English if the requested language has no pattern yet.
    """
    pattern = _PATTERNS.get(lang, _FALLBACK)
    return bool(pattern.match(text.strip()))


def supported_languages() -> frozenset[str]:
    """Return the set of BCP-47 language tags with phrasebook entries."""
    return frozenset(_PATTERNS)
