"""Data model for the L1 capture pipeline (ti-rnlqo.2.1)."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from uuid import uuid4


class FactType(str, Enum):
    PHONE      = "phone"
    CASE_ID    = "case_id"
    AMOUNT     = "amount"
    DATE       = "date"
    NAME       = "name"
    ADDRESS    = "address"
    EMAIL      = "email"
    ACCOUNT_ID = "account_id"
    MEMBER_ID  = "member_id"
    POLICY_ID  = "policy_id"


# Fact types promotable to a durable contact_fact row on writeback (ti-hb2dx).
# CASE_ID and PHONE are deliberately excluded — see the Call Card AFTER
# architecture doc (ti-ve84d) Data Model section for why.
DURABLE_FACT_TYPES: frozenset[FactType] = frozenset({
    FactType.ACCOUNT_ID,
    FactType.MEMBER_ID,
    FactType.POLICY_ID,
    FactType.ADDRESS,
    FactType.EMAIL,
})


@dataclass
class CapturedFact:
    session_id: str
    fact_type: FactType
    raw_text: str
    normalized_value: str
    transcript_turn_id: int
    transcript_offset_s: float
    speaker: str
    confidence: float
    critical: bool
    confirmed: bool | None = None
    source_layer: int = 1
    id: str = field(default_factory=lambda: uuid4().hex)
    created_at: float = field(default_factory=time.time)


@dataclass
class ActionItem:
    session_id: str
    description: str
    trigger: str
    owner: str
    transcript_turn_id: int
    transcript_offset_s: float
    speaker: str
    confidence: float
    due_date: str | None = None
    confirmed: bool | None = None
    source_layer: int = 1
    id: str = field(default_factory=lambda: uuid4().hex)
    created_at: float = field(default_factory=time.time)


ContactRoster = frozenset[str]
