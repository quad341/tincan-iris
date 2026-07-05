"""PostCallRecapGenerator — gating, filtering, ordering (ti-ah76a / ti-6a1y3).

Covers: api_key gating, missing-call-card early return, confirmed-or-confidence
filtering of facts/action items, empty-after-filter short-circuit, the
enricher_thread.join()-before-store-read ordering guarantee, exception safety
around the LLM call, and the structural "no transcript in scope" invariant
that is what actually enforces "restate, don't invent" (ti-ve84d, AF1).
"""
from __future__ import annotations

import inspect
import threading
import time
from unittest.mock import MagicMock, patch

from iris.capture.recap import OutcomeSummary, PostCallRecapGenerator


def _card(facts=None, action_items=None):
    return {"facts": facts or [], "action_items": action_items or []}


def _fact(fact_type="case_id", normalized_value="V", confirmed=False, confidence=0.5):
    return {
        "fact_type": fact_type, "normalized_value": normalized_value,
        "confirmed": confirmed, "confidence": confidence,
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


def _make_generator(*, store=None, enricher_thread=None, api=None, cfg=None, **kwargs):
    return PostCallRecapGenerator(
        session_id="s1",
        store=store if store is not None else MagicMock(),
        enricher_thread=enricher_thread if enricher_thread is not None else _finished_thread(),
        api=api if api is not None else MagicMock(),
        cfg=cfg if cfg is not None else MagicMock(anthropic_api_key="test-key"),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# 1. api_key gating
# ---------------------------------------------------------------------------

def test_run_skips_when_no_api_key_configured(monkeypatch):
    monkeypatch.delenv("IRIS_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    store = MagicMock()
    api = MagicMock()
    gen = _make_generator(store=store, api=api, cfg=MagicMock(spec=[]))

    gen.run()

    store.get_call_card.assert_not_called()
    api.broadcast.assert_not_called()


# ---------------------------------------------------------------------------
# 2. missing call card
# ---------------------------------------------------------------------------

def test_run_returns_early_when_call_card_missing():
    store = MagicMock()
    store.get_call_card.return_value = {}
    api = MagicMock()
    gen = _make_generator(store=store, api=api)

    gen.run()  # must not raise

    api.broadcast.assert_not_called()
    store.set_outcome_summary.assert_not_called()


# ---------------------------------------------------------------------------
# 3. confidence-threshold filtering
# ---------------------------------------------------------------------------

@patch("anthropic.Anthropic")
@patch("instructor.from_anthropic")
def test_run_filters_facts_and_items_by_confirmed_or_confidence(
    mock_from_anthropic, _mock_anthropic_cls,
):
    mock_client = MagicMock()
    mock_from_anthropic.return_value = mock_client
    mock_client.chat.completions.create.return_value = OutcomeSummary(text="ok")

    facts = [
        _fact(normalized_value="fact-confirmed-low", confirmed=True, confidence=0.1),
        _fact(normalized_value="fact-unconfirmed-high", confirmed=False, confidence=0.95),
        _fact(normalized_value="fact-unconfirmed-low", confirmed=False, confidence=0.1),
        _fact(normalized_value="fact-confirmed-high", confirmed=True, confidence=0.95),
    ]
    items = [
        _item(description="item-confirmed-low", confirmed=True, confidence=0.1),
        _item(description="item-unconfirmed-high", confirmed=False, confidence=0.95),
        _item(description="item-unconfirmed-low", confirmed=False, confidence=0.1),
        _item(description="item-confirmed-high", confirmed=True, confidence=0.95),
    ]
    store = MagicMock()
    store.get_call_card.return_value = _card(facts=facts, action_items=items)
    gen = _make_generator(store=store, confidence_threshold=0.8)

    gen.run()

    prompt = mock_client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
    assert "fact-confirmed-low" in prompt
    assert "fact-unconfirmed-high" in prompt
    assert "fact-unconfirmed-low" not in prompt
    assert "fact-confirmed-high" in prompt
    assert "item-confirmed-low" in prompt
    assert "item-unconfirmed-high" in prompt
    assert "item-unconfirmed-low" not in prompt
    assert "item-confirmed-high" in prompt


# ---------------------------------------------------------------------------
# 4. empty-after-filter short-circuit
# ---------------------------------------------------------------------------

def test_run_returns_before_calling_llm_when_both_lists_empty_after_filter():
    facts = [_fact(confirmed=False, confidence=0.1)]
    items = [_item(confirmed=False, confidence=0.1)]
    store = MagicMock()
    store.get_call_card.return_value = _card(facts=facts, action_items=items)
    api = MagicMock()
    gen = _make_generator(store=store, api=api, confidence_threshold=0.8)

    with patch("instructor.from_anthropic") as mock_from_anthropic:
        gen.run()

    mock_from_anthropic.assert_not_called()
    store.set_outcome_summary.assert_not_called()
    api.broadcast.assert_not_called()


# ---------------------------------------------------------------------------
# 5. enricher_thread.join() ordering
# ---------------------------------------------------------------------------

def test_run_waits_for_enricher_thread_before_reading_store():
    order: list[str] = []

    class _SlowEnricherThread(threading.Thread):
        def run(self) -> None:
            time.sleep(0.05)
            order.append("enricher-done")

    enricher_thread = _SlowEnricherThread()
    enricher_thread.start()

    def _get_call_card(session_id):
        order.append("store-read")
        return {}

    store = MagicMock()
    store.get_call_card.side_effect = _get_call_card
    gen = _make_generator(store=store, enricher_thread=enricher_thread)

    gen.run()
    enricher_thread.join()

    assert order == ["enricher-done", "store-read"]


# ---------------------------------------------------------------------------
# 6. exception safety around the LLM call
# ---------------------------------------------------------------------------

def test_run_swallows_llm_timeout_and_does_not_store_or_broadcast():
    store = MagicMock()
    store.get_call_card.return_value = _card(facts=[_fact(confirmed=True)])
    api = MagicMock()
    gen = _make_generator(store=store, api=api)

    with patch.object(gen, "_call_llm", side_effect=TimeoutError("llm timed out")):
        gen.run()  # must not raise

    store.set_outcome_summary.assert_not_called()
    api.broadcast.assert_not_called()


def test_run_swallows_generic_llm_exception_and_does_not_store_or_broadcast():
    store = MagicMock()
    store.get_call_card.return_value = _card(facts=[_fact(confirmed=True)])
    api = MagicMock()
    gen = _make_generator(store=store, api=api)

    with patch.object(gen, "_call_llm", side_effect=RuntimeError("boom")):
        gen.run()  # must not raise

    store.set_outcome_summary.assert_not_called()
    api.broadcast.assert_not_called()


def test_run_stores_and_broadcasts_on_successful_recap():
    store = MagicMock()
    store.get_call_card.return_value = _card(facts=[_fact(confirmed=True)])
    api = MagicMock()
    gen = _make_generator(store=store, api=api)

    with patch.object(gen, "_call_llm", return_value="Alice called about case AB123."):
        gen.run()

    store.set_outcome_summary.assert_called_once_with("s1", "Alice called about case AB123.")
    api.broadcast.assert_called_once_with(
        {"event": "call_card_recap_ready", "session_id": "s1"},
    )


# ---------------------------------------------------------------------------
# 7. transcript exclusion -- structural, not just behavioral. A regression that
# threads a transcript back into this module would be exactly the kind of
# change that turns "restate" into "invent" (ti-ve84d AF1); this asserts the
# invariant directly against the source rather than any one prompt's content.
# ---------------------------------------------------------------------------

def test_recap_module_never_references_transcript():
    # The module docstring explains the exclusion in prose (and legitimately
    # says "transcript") -- what must never reference it is the actual code:
    # the constructor, run(), and the prompt-building _call_llm().
    for member in (
        PostCallRecapGenerator.__init__,
        PostCallRecapGenerator.run,
        PostCallRecapGenerator._call_llm,
    ):
        source = inspect.getsource(member)
        assert "transcript" not in source.lower(), member.__name__
