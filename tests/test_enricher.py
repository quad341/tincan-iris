"""PostCallEnricher fact dedup / cue-context / action-item collapse (ti-3p688.4).

Covers ti-3p688.1 (done on this branch: CallCardStore.upsert_enriched_fact
dedupes by (fact_type, normalized_value), refreshing raw_text so a bare L1
match gains L3 cue-context, and never overwrites an already-confirmed row in
place -- see the ti-f34mq review of commit 3bb4da5, addressed in 36b7a99) and
ti-3p688.2 (NOT yet built: action-item extraction tightening). Tests run at
the PostCallEnricher._apply_result seam -- a real CallCardStore(":memory:")
wired through a real PostCallEnricher, calling _apply_result directly with a
constructed EnrichmentSchema -- so a passing test means the store actually
collapsed/preserved rows, not that a mock was called. This skips only the
LLM call itself (_call_llm), which _apply_result never touches.

test_repeated_action_item_mentions_collapse_to_one_clarified_item is TDD-ahead
and is EXPECTED TO FAIL today: CallCardStore.upsert_enriched_action_item's
dedup key is (session_id, transcript_turn_id, source_layer=1), which only
matches a rephrased mention landing on the *same* transcript turn as the
original L1 item. A near-duplicate mention from a later turn -- the realistic
case ti-3p688.2 exists to fix -- currently falls through to a fresh INSERT
instead of collapsing. This pins the target contract for the builder; it is
not a bug in this test.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from iris.capture.enricher import ActionItemExtract, EnrichmentSchema, FactExtract, PostCallEnricher
from iris.capture.schemas import ActionItem, CapturedFact, FactType
from iris.capture.store import CallCardStore


@pytest.fixture
def store():
    return CallCardStore(":memory:")


def _enricher(store, session_id: str = "sess-1") -> PostCallEnricher:
    return PostCallEnricher(
        session_id=session_id,
        store=store,
        transcript_store=MagicMock(),
        api=MagicMock(),
        cfg=MagicMock(),
    )


# ---------------------------------------------------------------------------
# ti-3p688.1 -- fact dedup by (fact_type, normalized_value) + cue-context
# ---------------------------------------------------------------------------

def test_l1_date_fact_gains_cue_context_and_does_not_duplicate(store):
    store.load_or_create("sess-1", "+15550000")
    store.add_fact(CapturedFact(
        id="f1", session_id="sess-1", fact_type=FactType.DATE,
        raw_text="the 8th", normalized_value="2026-08-08",
        critical=False, confidence=0.6, confirmed=None,
        transcript_turn_id=3, transcript_offset_s=10.0, speaker="far",
        source_layer=1,
    ))

    enricher = _enricher(store)
    enricher._apply_result("sess-1", EnrichmentSchema(
        new_facts=[FactExtract(
            fact_type="date", raw_text="follow-up call scheduled for the 8th",
            normalized_value="2026-08-08", transcript_turn_id=7, confidence=0.9,
        )],
        enriched_items=[],
    ))

    facts = store.get_call_card("sess-1")["facts"]
    assert len(facts) == 1
    assert facts[0]["raw_text"] == "follow-up call scheduled for the 8th"
    assert facts[0]["normalized_value"] == "2026-08-08"


def test_two_duplicate_facts_in_same_enrichment_pass_collapse(store):
    # No prior L1 fact seeded -- both entries arrive from the same LLM pass.
    store.load_or_create("sess-1", "+15550000")

    enricher = _enricher(store)
    enricher._apply_result("sess-1", EnrichmentSchema(
        new_facts=[
            FactExtract(fact_type="date", raw_text="mentioned the 8th",
                        normalized_value="2026-08-08", transcript_turn_id=5, confidence=0.7),
            FactExtract(fact_type="date", raw_text="follow-up call scheduled for the 8th",
                        normalized_value="2026-08-08", transcript_turn_id=7, confidence=0.9),
        ],
        enriched_items=[],
    ))

    facts = store.get_call_card("sess-1")["facts"]
    assert len(facts) == 1
    # Second entry's UPDATE lands on the first entry's fresh INSERT.
    assert facts[0]["raw_text"] == "follow-up call scheduled for the 8th"


def test_distinct_normalized_values_do_not_collapse(store):
    store.load_or_create("sess-1", "+15550000")

    enricher = _enricher(store)
    enricher._apply_result("sess-1", EnrichmentSchema(
        new_facts=[
            FactExtract(fact_type="date", raw_text="the 8th",
                        normalized_value="2026-08-08", transcript_turn_id=5, confidence=0.9),
            FactExtract(fact_type="date", raw_text="the 12th",
                        normalized_value="2026-08-12", transcript_turn_id=9, confidence=0.9),
        ],
        enriched_items=[],
    ))

    facts = store.get_call_card("sess-1")["facts"]
    assert len(facts) == 2
    assert {f["normalized_value"] for f in facts} == {"2026-08-08", "2026-08-12"}


# ---------------------------------------------------------------------------
# ti-3p688.1 reviewer follow-up (ti-f34mq on commit 3bb4da5) -- a confirmed
# fact is the durable-writeback gate (call_card_host.finalize_writeback) and
# must never be silently rewritten by a later enrichment pass.
# ---------------------------------------------------------------------------

def test_confirmed_fact_not_overwritten_by_later_enrichment(store):
    store.load_or_create("sess-1", "+15550000")
    store.add_fact(CapturedFact(
        id="f1", session_id="sess-1", fact_type=FactType.DATE,
        raw_text="the 8th", normalized_value="2026-08-08",
        critical=False, confidence=0.6, confirmed=True,
        transcript_turn_id=3, transcript_offset_s=10.0, speaker="far",
        source_layer=1,
    ))

    enricher = _enricher(store)
    enricher._apply_result("sess-1", EnrichmentSchema(
        new_facts=[FactExtract(
            fact_type="date", raw_text="follow-up call scheduled for the 8th",
            normalized_value="2026-08-08", transcript_turn_id=7, confidence=0.9,
        )],
        enriched_items=[],
    ))

    facts = store.get_call_card("sess-1")["facts"]
    assert len(facts) == 2

    original = next(f for f in facts if f["id"] == "f1")
    assert original["raw_text"] == "the 8th"
    assert original["confirmed"] == 1

    added = next(f for f in facts if f["id"] != "f1")
    assert added["source_layer"] == 3
    assert added["confirmed"] is None
    assert added["raw_text"] == "follow-up call scheduled for the 8th"


# ---------------------------------------------------------------------------
# ti-3p688.2 -- action-item extraction tightening (NOT YET BUILT)
# ---------------------------------------------------------------------------

def test_repeated_action_item_mentions_collapse_to_one_clarified_item(store):
    store.load_or_create("sess-1", "+15550000")
    store.add_action_item(ActionItem(
        id="a1", session_id="sess-1", description="I'll call back",
        trigger="I will", owner="operator", due_date=None,
        confidence=0.6, confirmed=None,
        transcript_turn_id=5, transcript_offset_s=20.0, speaker="operator",
        source_layer=1,
    ))

    enricher = _enricher(store)
    enricher._apply_result("sess-1", EnrichmentSchema(
        new_facts=[],
        enriched_items=[ActionItemExtract(
            description="Call back Tuesday", owner="operator",
            due_date="2026-07-14", transcript_turn_id=40, confidence=0.9,
        )],
    ))

    # EXPECTED TO FAIL today: upsert_enriched_action_item's dedup key is
    # (session_id, transcript_turn_id, source_layer=1); turn_id=40 doesn't
    # match the turn_id=5 L1 row, so this falls through to an INSERT instead
    # of collapsing onto the same task -- exactly the gap ti-3p688.2 exists
    # to close.
    items = store.get_call_card("sess-1")["action_items"]
    assert len(items) == 1
