"""ScopeManifest — what Iris can do, and whether a query is an explicit model request."""
from __future__ import annotations

import re

_EXPLICIT_MODEL_RE = re.compile(
    r"\bask\s+(?:haiku|qwen|the\s+model|the\s+ai|claude)\b"
    r"|\buse\s+(?:haiku|the\s+model|the\s+cloud)\b"
    r"|\bsearch\s+(?:for|the\s+web)\b",
    re.IGNORECASE,
)

_PUNT_OFFER = (
    "That is a bit outside what I am built for. "
    "Want to ask the model? Try: ask Haiku about <topic>"
)

_DOMAINS: dict[str, list[str]] = {
    "Calls & messages": [
        "Answer incoming calls, screen callers, take voice messages",
        "Look up contacts by name or phone number",
        "Read back missed messages",
    ],
    "Time & calendar": [
        "Tell the time and date",
        "Look up calendar events",
    ],
    "Email": [
        "Read unread emails aloud",
        "Send email by voice (with spoken preview + confirmation)",
        "Archive or flag messages",
    ],
    "Notes & preferences": [
        "Save and recall per-caller notes",
        "Remember caller preferences",
    ],
    "Web": [
        "Search the web and summarize results",
    ],
    "General": [
        "Answer questions via the local model (Qwen)",
        'Escalate to the cloud: say "ask Haiku about <topic>"',
    ],
}


class ScopeManifest:
    @staticmethod
    def what_i_do() -> dict[str, list[str]]:
        """Domain-grouped map of Iris capabilities."""
        return _DOMAINS

    @staticmethod
    def is_explicit_model_request(text: str) -> bool:
        return bool(_EXPLICIT_MODEL_RE.search(text))

    @staticmethod
    def punt_offer(text: str) -> str:
        """Return punt text if query is off-scope; empty string if already an explicit model request."""
        if ScopeManifest.is_explicit_model_request(text):
            return ""
        return _PUNT_OFFER
