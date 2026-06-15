"""Call-level trust model — DEMO vs FULL mode for the far party.

The far party (call downlink) is DEMO by default: they get Tier0 deterministic
commands and Tier1 local-LLM knowledge, but cloud escalation (Tier2) is blocked
and future auth'd skill integrations (calendar, email) must gate on trust mode.
The operator is always FULL. The operator can grant FULL to the far party for the
current call via a voice command on the operator mic; this flag auto-resets on
hangup so the default is restored per call.
"""
from __future__ import annotations

from enum import Enum


class TrustMode(str, Enum):
    DEMO = "demo"   # Tier0 + Tier1 local knowledge; cloud and auth'd skills blocked
    FULL = "full"   # all tiers, all skills; operator default
