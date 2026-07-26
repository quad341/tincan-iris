"""Unit tests for PostCallEnricher and iris.capture.transcript.TranscriptStore (ti-rnlqo.5.5).

All PostCallEnricher tests patch _call_llm so no real Anthropic API key or audio
hardware is required.  TranscriptStore tests use the live class.

These tests are written BEFORE the code lands on the build branch; they will fail
(ImportError / AttributeError) until iris/capture/enricher.py and
iris/capture/transcript.py are present.

Documented contract (PostCallEnricher):
  PostCallEnricher(*, session_id, store, transcript_store, api, cfg)
    .run()
      - skips silently if cfg.anthropic_api_key is falsy (and no IRIS_ANTHROPIC_API_KEY env var)
      - skips silently if transcript_store.is_empty()
      - on success: store.upsert_enriched_fact, store.upsert_enriched_action_item,
        store.mark_enrichment_done(session_id, status=1),
        api.broadcast({'event': 'call_card_enriched', 'session_id': ...})
      - on concurrent.futures.TimeoutError or any Exception:
        store.mark_enrichment_done(session_id, status=2), no broadcast

Documented contract (TranscriptStore — in-memory, iris.capture.transcript):
  TranscriptStore()
    .append(text, speaker, offset_s) -> int  # sequential turn_id starting at 1
    .get_turns()                             # returns a copy; mutations don't affect store
    .is_empty() -> bool
"""
from __future__ import annotations

import concurrent.futures
from unittest.mock import MagicMock, patch


from iris.capture.enricher import (
    ActionItemExtract,
    EnrichmentSchema,
    FactExtract,
    PostCallEnricher,
)
from iris.capture.transcript import TranscriptStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SESSION = "sess-abc123"


def _store():
    m = MagicMock()
    m.get_call_card.return_value = {"facts": [], "action_items": []}
    return m


def _cfg(api_key="sk-test"):
    cfg = MagicMock()
    cfg.anthropic_api_key = api_key
    cfg.call_card.anthropic_api_key = api_key
    return cfg


def _ts(turns: int = 2) -> TranscriptStore:
    ts = TranscriptStore()
    for i in range(turns):
        speaker = "operator" if i % 2 == 0 else "far"
        ts.append(f"utterance {i}", speaker, float(i))
    return ts


def _enricher(*, api_key="sk-test", store=None, transcript_store=None, api=None):
    return PostCallEnricher(
        session_id=SESSION,
        store=store or _store(),
        transcript_store=transcript_store or _ts(),
        api=api or MagicMock(),
        cfg=_cfg(api_key),
    )


def _success_schema() -> EnrichmentSchema:
    return EnrichmentSchema(
        new_facts=[
            FactExtract(
                fact_type="phone",
                raw_text="call 415-555-9999",
                normalized_value="+14155559999",
                transcript_turn_id=1,
                confidence=0.85,
            )
        ],
        enriched_items=[
            ActionItemExtract(
                description="Call them back Tuesday",
                owner="operator",
                due_date="2026-07-01",
                transcript_turn_ids=[2],
                confidence=0.9,
            )
        ],
    )


# ---------------------------------------------------------------------------
# PostCallEnricher: no-api-key guard
# ---------------------------------------------------------------------------


def test_no_api_key_skips_enrichment(monkeypatch):
    """cfg.anthropic_api_key is falsy → run() returns without touching store or api."""
    monkeypatch.delenv("IRIS_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    store = _store()
    api = MagicMock()
    enricher = _enricher(api_key="", store=store, api=api)

    enricher.run()

    store.upsert_enriched_fact.assert_not_called()
    store.upsert_enriched_action_item.assert_not_called()
    store.mark_enrichment_done.assert_not_called()
    api.broadcast.assert_not_called()


# ---------------------------------------------------------------------------
# PostCallEnricher: empty-transcript guard
# ---------------------------------------------------------------------------


def test_empty_transcript_skips_enrichment():
    """Empty TranscriptStore → run() returns without calling the LLM or modifying the store."""
    store = _store()
    api = MagicMock()
    enricher = _enricher(store=store, transcript_store=TranscriptStore(), api=api)

    with patch.object(PostCallEnricher, "_call_llm") as mock_llm:
        enricher.run()
        mock_llm.assert_not_called()

    store.upsert_enriched_fact.assert_not_called()
    store.upsert_enriched_action_item.assert_not_called()
    store.mark_enrichment_done.assert_not_called()
    api.broadcast.assert_not_called()


# ---------------------------------------------------------------------------
# PostCallEnricher: success path
# ---------------------------------------------------------------------------


def test_success_path():
    """2 transcript turns, schema yields 1 fact + 1 action item → full store update + broadcast."""
    store = _store()
    api = MagicMock()
    enricher = _enricher(store=store, api=api)

    with patch.object(PostCallEnricher, "_call_llm", return_value=_success_schema()):
        enricher.run()

    store.upsert_enriched_fact.assert_called_once_with(
        session_id=SESSION,
        fact_type="phone",
        raw_text="call 415-555-9999",
        normalized_value="+14155559999",
        transcript_turn_id=1,
        confidence=0.85,
    )

    store.upsert_enriched_action_item.assert_called_once()
    store.mark_enrichment_done.assert_called_once_with(SESSION, status=1)
    api.broadcast.assert_called_once_with(
        {"event": "call_card_enriched", "session_id": SESSION}
    )


# ---------------------------------------------------------------------------
# PostCallEnricher: failure paths
# ---------------------------------------------------------------------------


def test_timeout_marks_failed():
    """TimeoutError from _call_llm → mark_enrichment_done(status=2), no broadcast."""
    store = _store()
    api = MagicMock()
    enricher = _enricher(store=store, api=api)

    with patch.object(
        PostCallEnricher, "_call_llm", side_effect=concurrent.futures.TimeoutError
    ):
        enricher.run()

    store.mark_enrichment_done.assert_called_once_with(SESSION, status=2)
    api.broadcast.assert_not_called()


def test_validation_failure_marks_failed():
    """Exception (e.g. InstructorRetryException) from _call_llm → status=2, no broadcast."""
    store = _store()
    api = MagicMock()
    enricher = _enricher(store=store, api=api)

    with patch.object(
        PostCallEnricher,
        "_call_llm",
        side_effect=Exception("instructor retry exhausted after 3 attempts"),
    ):
        enricher.run()

    store.mark_enrichment_done.assert_called_once_with(SESSION, status=2)
    api.broadcast.assert_not_called()


# ---------------------------------------------------------------------------
# TranscriptStore: in-memory contract
# ---------------------------------------------------------------------------


def test_transcript_append_sequential_ids():
    """append() assigns turn_ids starting at 1 and incrementing by 1."""
    ts = TranscriptStore()
    id1 = ts.append("hello", "operator", 0.0)
    id2 = ts.append("world", "far", 1.0)
    assert id1 == 1
    assert id2 == 2


def test_transcript_get_turns_returns_copy():
    """get_turns() returns a snapshot; mutating the list does not affect the store."""
    ts = TranscriptStore()
    ts.append("hey", "operator", 0.0)
    turns = ts.get_turns()
    turns.clear()
    assert len(ts.get_turns()) == 1


def test_transcript_is_empty():
    """is_empty() is True before any append, False after."""
    ts = TranscriptStore()
    assert ts.is_empty() is True
    ts.append("first", "far", 0.5)
    assert ts.is_empty() is False
