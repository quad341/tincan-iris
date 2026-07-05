"""Unit tests for PostCallRecapGenerator (ti-pkt2r.1.1).

ask_structured is patched at the recap module boundary so these tests
exercise PostCallRecapGenerator's own orchestration -- join ordering,
confidence-threshold gating, the empty-after-filter short-circuit, and the
structural "no raw transcript in the prompt" guarantee -- without a real
cloud session.

Documented contract:
  PostCallRecapGenerator(*, session_id, store, enricher_thread, api, cfg,
                          cloud, confidence_threshold=0.8)
    .run()
      - ALWAYS joins enricher_thread first, before reading the call card
      - skips silently (after the join) if cloud is None
      - skips silently if the call card is missing/empty
      - keeps only facts/action items where confirmed is true or
        confidence >= confidence_threshold
      - no-ops (no store write, no broadcast, no LLM call at all) when both
        filtered lists are empty
      - the LLM prompt is built ONLY from the filtered facts'/items'
        fact_type+normalized_value / description+owner+due_date fields --
        nothing else about a fact or item, and no raw transcript (this class
        has no transcript_store at all), ever reaches the prompt
      - on ask_structured() returning None, or any exception: no store
        write, no broadcast, no exception escapes run()
      - on success: store.set_outcome_summary(session_id, text),
        api.broadcast({'event': 'call_card_recap_ready', 'session_id': ...})
"""
from __future__ import annotations

import inspect
import threading
from unittest.mock import MagicMock, patch

from iris.capture.recap import OutcomeSummary, PostCallRecapGenerator

SESSION = "s1"
_UNSET = object()


def _card(facts=None, action_items=None):
    return {"facts": facts or [], "action_items": action_items or []}


def _fact(fact_type="case_id", normalized_value="V", confirmed=False, confidence=0.5,
          raw_text="RAW-SHOULD-NOT-LEAK"):
    return {
        "fact_type": fact_type, "normalized_value": normalized_value,
        "confirmed": confirmed, "confidence": confidence, "raw_text": raw_text,
    }


def _item(description="call back", owner="far", due_date=None, confirmed=False, confidence=0.5):
    return {
        "description": description, "owner": owner, "due_date": due_date,
        "confirmed": confirmed, "confidence": confidence,
    }


def _finished_thread():
    """A real Thread that already ran to completion -- .join() returns immediately."""
    t = threading.Thread(target=lambda: None)
    t.start()
    t.join()
    return t


def _generator(*, store=None, enricher_thread=None, api=None, cfg=None, cloud=_UNSET, **kwargs):
    if store is None:
        store = MagicMock()
        store.get_call_card.return_value = _card()
    return PostCallRecapGenerator(
        session_id=SESSION,
        store=store,
        enricher_thread=enricher_thread if enricher_thread is not None else _finished_thread(),
        api=api if api is not None else MagicMock(),
        cfg=cfg if cfg is not None else MagicMock(),
        cloud=MagicMock() if cloud is _UNSET else cloud,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# join-before-read ordering
# ---------------------------------------------------------------------------

def test_run_always_joins_enricher_thread_before_reading_call_card():
    manager = MagicMock()
    enricher_thread = manager.enricher_thread
    store = manager.store
    store.get_call_card.return_value = _card()
    generator = _generator(store=store, enricher_thread=enricher_thread)

    generator.run()

    names = [c[0] for c in manager.mock_calls]
    assert names == ["enricher_thread.join", "store.get_call_card"]


def test_run_joins_enricher_thread_even_when_cloud_is_none():
    enricher_thread = MagicMock()
    generator = _generator(enricher_thread=enricher_thread, cloud=None)

    generator.run()

    enricher_thread.join.assert_called_once_with()


# ---------------------------------------------------------------------------
# early skips (after the join)
# ---------------------------------------------------------------------------

def test_run_skips_reading_call_card_when_cloud_is_none():
    store = MagicMock()
    generator = _generator(store=store, cloud=None)

    generator.run()

    store.get_call_card.assert_not_called()


def test_run_returns_when_call_card_missing():
    store = MagicMock()
    store.get_call_card.return_value = {}
    api = MagicMock()
    generator = _generator(store=store, api=api)

    generator.run()

    api.broadcast.assert_not_called()
    store.set_outcome_summary.assert_not_called()


# ---------------------------------------------------------------------------
# confidence-threshold gating
# ---------------------------------------------------------------------------

@patch("iris.capture.recap.ask_structured")
def test_confirmed_fact_included_regardless_of_confidence(mock_ask_structured):
    mock_ask_structured.return_value = OutcomeSummary(text="recap")
    store = MagicMock()
    store.get_call_card.return_value = _card(
        facts=[_fact(normalized_value="LOW-CONF-CONFIRMED", confirmed=True, confidence=0.1)],
    )
    generator = _generator(store=store)

    generator.run()

    prompt = mock_ask_structured.call_args[0][1]
    assert "LOW-CONF-CONFIRMED" in prompt


@patch("iris.capture.recap.ask_structured")
def test_unconfirmed_high_confidence_fact_included(mock_ask_structured):
    mock_ask_structured.return_value = OutcomeSummary(text="recap")
    store = MagicMock()
    store.get_call_card.return_value = _card(
        facts=[_fact(normalized_value="HIGH-CONF-UNCONFIRMED", confirmed=False, confidence=0.95)],
    )
    generator = _generator(store=store)

    generator.run()

    prompt = mock_ask_structured.call_args[0][1]
    assert "HIGH-CONF-UNCONFIRMED" in prompt


@patch("iris.capture.recap.ask_structured")
def test_unconfirmed_low_confidence_fact_excluded(mock_ask_structured):
    mock_ask_structured.return_value = OutcomeSummary(text="recap")
    store = MagicMock()
    store.get_call_card.return_value = _card(
        facts=[
            _fact(normalized_value="EXCLUDED-VALUE", confirmed=False, confidence=0.1),
            _fact(normalized_value="INCLUDED-VALUE", confirmed=True, confidence=0.1),
        ],
    )
    generator = _generator(store=store)

    generator.run()

    prompt = mock_ask_structured.call_args[0][1]
    assert "INCLUDED-VALUE" in prompt
    assert "EXCLUDED-VALUE" not in prompt


@patch("iris.capture.recap.ask_structured")
def test_confidence_threshold_is_configurable(mock_ask_structured):
    mock_ask_structured.return_value = OutcomeSummary(text="recap")
    store = MagicMock()
    store.get_call_card.return_value = _card(
        facts=[_fact(normalized_value="MID-CONF", confirmed=False, confidence=0.6)],
    )
    generator = _generator(store=store, confidence_threshold=0.5)

    generator.run()

    prompt = mock_ask_structured.call_args[0][1]
    assert "MID-CONF" in prompt


@patch("iris.capture.recap.ask_structured")
def test_action_items_are_gated_the_same_way_as_facts(mock_ask_structured):
    mock_ask_structured.return_value = OutcomeSummary(text="recap")
    store = MagicMock()
    store.get_call_card.return_value = _card(
        action_items=[
            _item(description="EXCLUDED-ITEM", confirmed=False, confidence=0.1),
            _item(description="INCLUDED-ITEM", confirmed=True, confidence=0.1),
        ],
    )
    generator = _generator(store=store)

    generator.run()

    prompt = mock_ask_structured.call_args[0][1]
    assert "INCLUDED-ITEM" in prompt
    assert "EXCLUDED-ITEM" not in prompt


@patch("iris.capture.recap.ask_structured")
def test_noop_when_both_filtered_lists_empty(mock_ask_structured):
    store = MagicMock()
    api = MagicMock()
    store.get_call_card.return_value = _card(
        facts=[_fact(confirmed=False, confidence=0.1)],
        action_items=[_item(confirmed=False, confidence=0.1)],
    )
    generator = _generator(store=store, api=api)

    generator.run()

    mock_ask_structured.assert_not_called()
    store.set_outcome_summary.assert_not_called()
    api.broadcast.assert_not_called()


# ---------------------------------------------------------------------------
# "restate, don't invent": prompt is built ONLY from the gated fields
# ---------------------------------------------------------------------------

@patch("iris.capture.recap.ask_structured")
def test_prompt_never_contains_fact_raw_text_or_other_ungated_fields(mock_ask_structured):
    mock_ask_structured.return_value = OutcomeSummary(text="recap")
    store = MagicMock()
    store.get_call_card.return_value = _card(
        facts=[_fact(
            fact_type="case_id", normalized_value="CASE-999", confirmed=True,
            raw_text="TRANSCRIPT-SHAPED-RAW-TEXT-SHOULD-NOT-LEAK",
        )],
    )
    generator = _generator(store=store)

    generator.run()

    prompt = mock_ask_structured.call_args[0][1]
    assert "CASE-999" in prompt
    assert "TRANSCRIPT-SHAPED-RAW-TEXT-SHOULD-NOT-LEAK" not in prompt


def test_constructor_has_no_transcript_parameter_at_all():
    """PostCallRecapGenerator takes no transcript_store/transcript -- the raw
    transcript is structurally unreachable from this class, which is what
    actually enforces 'restate, don't invent' (ti-ve84d, AF1), independent
    of any prompt-construction logic that could change later."""
    params = inspect.signature(PostCallRecapGenerator.__init__).parameters
    assert not any("transcript" in name for name in params)


# ---------------------------------------------------------------------------
# success / failure handling of the LLM call
# ---------------------------------------------------------------------------

@patch("iris.capture.recap.ask_structured")
def test_success_sets_outcome_summary_and_broadcasts(mock_ask_structured):
    mock_ask_structured.return_value = OutcomeSummary(text="Operator will follow up Friday.")
    store = MagicMock()
    api = MagicMock()
    store.get_call_card.return_value = _card(facts=[_fact(confirmed=True)])
    generator = _generator(store=store, api=api)

    generator.run()

    store.set_outcome_summary.assert_called_once_with(SESSION, "Operator will follow up Friday.")
    api.broadcast.assert_called_once_with(
        {"event": "call_card_recap_ready", "session_id": SESSION}
    )


@patch("iris.capture.recap.ask_structured")
def test_ask_structured_returns_none_skips_without_broadcast(mock_ask_structured):
    mock_ask_structured.return_value = None
    store = MagicMock()
    api = MagicMock()
    store.get_call_card.return_value = _card(facts=[_fact(confirmed=True)])
    generator = _generator(store=store, api=api)

    generator.run()

    store.set_outcome_summary.assert_not_called()
    api.broadcast.assert_not_called()


@patch("iris.capture.recap.ask_structured")
def test_exception_during_llm_call_does_not_raise_or_broadcast(mock_ask_structured):
    mock_ask_structured.side_effect = RuntimeError("session not ready")
    store = MagicMock()
    api = MagicMock()
    store.get_call_card.return_value = _card(facts=[_fact(confirmed=True)])
    generator = _generator(store=store, api=api)

    generator.run()  # must not raise -- PostCallRecapGenerator.run() is a thread entrypoint

    store.set_outcome_summary.assert_not_called()
    api.broadcast.assert_not_called()
