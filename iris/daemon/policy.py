"""PolicyResolver — verb resolution + DND degrade + choice-set builder (ADR-0006).

resolve(caller_number) is the hot path: cache hit + degrade + build JSON < 500ms.

DND degrade ladder (when PostureManager.effective()["dnd"] is True):
    ring_with_announcement → ring_with_announcement  (VIP immune, never degraded)
    ring_through           → screen
    screen                 → take_message
    take_message           → take_message            (floor — degrade never produces ignore)
    ignore                 → ignore                  (contact opted out; preserve)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any

from ..roster import Contact, RosterStore
from .posture import PostureManager

_log = logging.getLogger(__name__)

_CACHE_TTL_S: float = 60.0

# Default verb for callers not on the roster.
_UNKNOWN_DEFAULT_VERB = "screen"

# DND degrade ladder: {current_verb: degraded_verb}
_DND_DEGRADE: dict[str, str] = {
    "ring_with_announcement": "ring_with_announcement",  # VIP immune
    "ring_through":           "screen",
    "screen":                 "take_message",
    "take_message":           "take_message",            # floor
    "ignore":                 "ignore",                  # preserved
}

# Standard choice-sets per verb.  Verbs with no operator interaction have no choices.
_CHOICES_STANDARD = [
    {"id": "put_through",  "label": "Put Through", "key": "1"},
    {"id": "take_message", "label": "Take Message", "key": "2"},
    {"id": "decline",      "label": "Decline",      "key": "3"},
]


def _choices_for_verb(verb: str) -> list[dict]:
    if verb in ("ring_with_announcement", "ring_through", "screen"):
        return [dict(c) for c in _CHOICES_STANDARD]
    if verb == "take_message":
        return [{"id": "put_through", "label": "Put Through", "key": "1"}]
    return []  # ignore: no operator choices


@dataclass
class ResolveResult:
    verb: str
    contact: Contact | None
    event: dict  # full incoming_call JSON ready to broadcast


class PolicyResolver:
    """Resolves caller_number → verb + choice-set.

    roster_cache is rebuilt at startup and refreshed every 60s or on roster_changed.
    Thread-safe: the cache lock is per-operation; resolve() takes a snapshot copy.
    """

    def __init__(
        self,
        roster: RosterStore,
        posture: PostureManager,
    ) -> None:
        self._roster = roster
        self._posture = posture
        self._lock = threading.Lock()
        self._cache: dict[str, Contact] = {}  # phone_e164 → Contact
        self._cache_built_at: float = 0.0
        self._warm_cache()

    def _warm_cache(self) -> None:
        contacts = self._roster.all()
        cache: dict[str, Contact] = {}
        for c in contacts:
            if c.phone_e164:
                cache[c.phone_e164] = c
        with self._lock:
            self._cache = cache
            self._cache_built_at = time.time()

    def on_roster_changed(self) -> None:
        """Invalidate + rebuild the cache (call on roster_changed events)."""
        self._warm_cache()

    def _get_contact(self, caller_number: str) -> Contact | None:
        now = time.time()
        with self._lock:
            if now - self._cache_built_at > _CACHE_TTL_S:
                # TTL expired — rebuild outside the lock to avoid blocking callers.
                do_rebuild = True
            else:
                do_rebuild = False
                contact = self._cache.get(caller_number)
        if do_rebuild:
            self._warm_cache()
            with self._lock:
                contact = self._cache.get(caller_number)
        return contact

    def resolve(self, caller_number: str, call_id: str | None = None) -> ResolveResult:
        """Resolve caller_number to verb + choice-set JSON.  call_id is auto-generated
        if not supplied.  Must complete within 500ms (NFR-01)."""
        if call_id is None:
            call_id = str(uuid.uuid4())

        contact = self._get_contact(caller_number)
        base_verb = contact.handling_rule if contact else _UNKNOWN_DEFAULT_VERB

        eff = self._posture.effective()
        verb = _DND_DEGRADE.get(base_verb, "screen") if eff["dnd"] else base_verb

        choices = _choices_for_verb(verb)

        event: dict[str, Any] = {
            "event":          "incoming_call",
            "call_id":        call_id,
            "caller_name":    contact.display_name if contact else "",
            "caller_number":  caller_number,
            "verb":           verb,
            "choices":        choices,
        }
        return ResolveResult(verb=verb, contact=contact, event=event)
