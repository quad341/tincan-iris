"""Unit tests for PostCallEnricher (ti-pkt2r.1.1).

ask_structured is patched at the enricher module boundary so these tests
exercise PostCallEnricher's own orchestration -- FR6 transcript filtering,
status marking, and fact/action-item writeback -- without a real cloud
session.

Documented contract:
  PostCallEnricher(*, session_id, store, transcript_store, api, cfg, cloud)
    .run()
      - skips silently if cloud is None
      - skips silently if transcript_store.is_empty()
      - FR6: the extraction prompt includes ONLY operator-speaker turns;
        far-party turns are excluded entirely (interim trust-gate policy)
      - on ask_structured() returning None: mark_enrichment_done(status=2),
        no broadcast
      - on any exception (including cloud.ask() raising via ask_structured):
        mark_enrichment_done(status=2), no broadcast, exception does not
        escape run()
      - on success: add_fact per new fact (source_layer=3),
        upsert_enriched_action_item per item, mark_enrichment_done(status=1),
        api.broadcast({'event': 'call_card_enriched', 'session_id': ...})
      - an unrecognized fact_type in the LLM response falls back to
        FactType.NAME
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from iris.capture.enricher import EnrichmentSchema, PostCallEnricher
from iris.capture.schemas import FactType
from iris.capture.transcript import TranscriptStore

SESSION = "sess-abc123"
_UNSET = object()


def _store(facts=None):
    m = MagicMock()
    m.get_call_card.return_value = {"facts": facts or []}
    return m


def _ts(*turns):
    """turns: iterable of (text, speaker) pairs, appended in order."""
    ts = TranscriptStore()
    for i, (text, speaker) in enumerate(turns):
        ts.append(text, speaker, float(i))
    return ts


def _enricher(*, store=None, transcript_store=None, api=None, cfg=None, cloud=_UNSET):
    return PostCallEnricher(
        session_id=SESSION,
        store=store if store is not None else _store(),
        transcript_store=transcript_store if transcript_store is not None else _ts(("hi", "operator")),
        api=api if api is not None else MagicMock(),
        cfg=cfg if cfg is not None else MagicMock(),
        cloud=MagicMock() if cloud is _UNSET else cloud,
    )


# ---------------------------------------------------------------------------
# early skips
# ---------------------------------------------------------------------------

def test_run_skips_when_cloud_is_none():
    store = _store()
    enricher = _enricher(store=store, cloud=None)

    enricher.run()

    store.get_call_card.assert_not_called()
    store.mark_enrichment_done.assert_not_called()


def test_run_skips_when_transcript_empty():
    store = _store()
    enricher = _enricher(store=store, transcript_store=TranscriptStore())

    enricher.run()

    store.get_call_card.assert_not_called()
    store.mark_enrichment_done.assert_not_called()


# ---------------------------------------------------------------------------
# FR6: operator-only transcript filtering
# ---------------------------------------------------------------------------

@patch("iris.capture.enricher.ask_structured")
def test_fr6_excludes_far_party_turns_from_prompt(mock_ask_structured):
    mock_ask_structured.return_value = None  # content of the response is irrelevant here
    transcript_store = _ts(
        ("my secret operator line", "operator"),
        ("far party confidential info", "far"),
    )
    enricher = _enricher(transcript_store=transcript_store)

    enricher.run()

    prompt = mock_ask_structured.call_args[0][1]
    assert "my secret operator line" in prompt
    assert "far party confidential info" not in prompt


@patch("iris.capture.enricher.ask_structured")
def test_fr6_includes_operator_turns_only_even_when_far_is_majority(mock_ask_structured):
    mock_ask_structured.return_value = None
    transcript_store = _ts(
        ("far line one", "far"),
        ("operator line", "operator"),
        ("far line two", "far"),
    )
    enricher = _enricher(transcript_store=transcript_store)

    enricher.run()

    prompt = mock_ask_structured.call_args[0][1]
    assert "operator line" in prompt
    assert "far line one" not in prompt
    assert "far line two" not in prompt


@patch("iris.capture.enricher.ask_structured")
def test_fr6_all_far_turns_yields_empty_operator_transcript_block(mock_ask_structured):
    mock_ask_structured.return_value = None
    transcript_store = _ts(("far only line", "far"))
    enricher = _enricher(transcript_store=transcript_store)

    enricher.run()

    prompt = mock_ask_structured.call_args[0][1]
    assert "far only line" not in prompt


# ---------------------------------------------------------------------------
# status marking
# ---------------------------------------------------------------------------

@patch("iris.capture.enricher.ask_structured")
def test_marks_status_2_when_ask_structured_returns_none(mock_ask_structured):
    mock_ask_structured.return_value = None
    store = _store()
    api = MagicMock()
    enricher = _enricher(store=store, api=api)

    enricher.run()

    store.mark_enrichment_done.assert_called_once_with(SESSION, status=2)
    api.broadcast.assert_not_called()


@patch("iris.capture.enricher.ask_structured")
def test_marks_status_2_and_does_not_raise_when_cloud_ask_errors(mock_ask_structured):
    mock_ask_structured.side_effect = RuntimeError("session not ready")
    store = _store()
    api = MagicMock()
    enricher = _enricher(store=store, api=api)

    enricher.run()  # must not raise -- PostCallEnricher.run() is a thread entrypoint

    store.mark_enrichment_done.assert_called_once_with(SESSION, status=2)
    api.broadcast.assert_not_called()


@patch("iris.capture.enricher.ask_structured")
def test_marks_status_2_when_get_call_card_raises(mock_ask_structured):
    store = _store()
    store.get_call_card.side_effect = RuntimeError("db gone")
    api = MagicMock()
    enricher = _enricher(store=store, api=api)

    enricher.run()

    store.mark_enrichment_done.assert_called_once_with(SESSION, status=2)
    api.broadcast.assert_not_called()
    mock_ask_structured.assert_not_called()


# ---------------------------------------------------------------------------
# success path
# ---------------------------------------------------------------------------

@patch("iris.capture.enricher.ask_structured")
def test_success_adds_facts_upserts_items_marks_status_1_and_broadcasts(mock_ask_structured):
    result = EnrichmentSchema(
        new_facts=[{
            "fact_type": "email", "raw_text": "a@b.com", "normalized_value": "a@b.com",
            "transcript_turn_id": 1, "confidence": 0.9,
        }],
        enriched_items=[{
            "description": "call back", "owner": "operator", "due_date": "2026-07-10",
            "transcript_turn_id": 1, "confidence": 0.85,
        }],
    )
    mock_ask_structured.return_value = result
    store = _store()
    api = MagicMock()
    enricher = _enricher(store=store, api=api)

    enricher.run()

    assert store.add_fact.call_count == 1
    fact = store.add_fact.call_args[0][0]
    assert fact.session_id == SESSION
    assert fact.fact_type == FactType.EMAIL
    assert fact.raw_text == "a@b.com"
    assert fact.normalized_value == "a@b.com"
    assert fact.transcript_turn_id == 1
    assert fact.confidence == 0.9
    assert fact.source_layer == 3
    assert fact.critical is False

    store.upsert_enriched_action_item.assert_called_once_with(
        session_id=SESSION, turn_id=1, description="call back",
        owner="operator", due_date="2026-07-10", confidence=0.85,
    )
    store.mark_enrichment_done.assert_called_once_with(SESSION, status=1)
    api.broadcast.assert_called_once_with(
        {"event": "call_card_enriched", "session_id": SESSION}
    )


@patch("iris.capture.enricher.ask_structured")
def test_unrecognized_fact_type_falls_back_to_name(mock_ask_structured):
    result = EnrichmentSchema(
        new_facts=[{
            "fact_type": "not_a_real_type", "raw_text": "x", "normalized_value": "x",
            "transcript_turn_id": 1, "confidence": 0.5,
        }],
        enriched_items=[],
    )
    mock_ask_structured.return_value = result
    store = _store()
    enricher = _enricher(store=store)

    enricher.run()

    fact = store.add_fact.call_args[0][0]
    assert fact.fact_type == FactType.NAME


@patch("iris.capture.enricher.ask_structured")
def test_success_with_no_new_facts_or_items_still_marks_status_1_and_broadcasts(mock_ask_structured):
    mock_ask_structured.return_value = EnrichmentSchema(new_facts=[], enriched_items=[])
    store = _store()
    api = MagicMock()
    enricher = _enricher(store=store, api=api)

    enricher.run()

    store.add_fact.assert_not_called()
    store.upsert_enriched_action_item.assert_not_called()
    store.mark_enrichment_done.assert_called_once_with(SESSION, status=1)
    api.broadcast.assert_called_once_with(
        {"event": "call_card_enriched", "session_id": SESSION}
    )
