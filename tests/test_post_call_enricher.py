"""Unit tests for PostCallEnricher and iris.capture.transcript.TranscriptStore (ti-rnlqo.5.5).

All PostCallEnricher tests patch _call_llm so no real Anthropic API key or audio
hardware is required.  TranscriptStore tests use the live class.

These tests are written BEFORE the code lands on the build branch; they will fail
(ImportError / AttributeError) until iris/capture/enricher.py and
iris/capture/transcript.py are present.

Documented contract (PostCallEnricher):
  PostCallEnricher(*, session_id, store, transcript_store, api, cfg)
    .run()
      - skips silently, before any other check, if _cloud_enrichment_enabled(cfg)
        is False -- explicit opt-in, independent of haiku_enabled (ti-f6lkw.2)
      - skips silently if cfg.anthropic_api_key is falsy (and no IRIS_ANTHROPIC_API_KEY env var)
      - skips silently if transcript_store.is_empty()
      - on success: store.add_fact (source_layer=3), store.upsert_enriched_action_item,
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
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from iris.capture.enricher import (
    ActionItemExtract,
    EnrichmentSchema,
    FactExtract,
    PostCallEnricher,
    _cloud_enrichment_enabled,
)
from iris.capture.transcript import TranscriptStore
from iris.config import Config


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


def _enricher(*, api_key="sk-test", store=None, transcript_store=None, api=None, cfg=None):
    return PostCallEnricher(
        session_id=SESSION,
        store=store or _store(),
        transcript_store=transcript_store or _ts(),
        api=api or MagicMock(),
        cfg=cfg if cfg is not None else _cfg(api_key),
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
                transcript_turn_id=2,
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

    store.add_fact.assert_not_called()
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

    store.add_fact.assert_not_called()
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

    store.add_fact.assert_called_once()
    added_fact = store.add_fact.call_args[0][0]
    assert added_fact.source_layer == 3

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
# _cloud_enrichment_enabled(): explicit cloud-enrichment opt-in (ti-f6lkw.2)
# ---------------------------------------------------------------------------


def test_cloud_enrichment_enabled_true_directly_on_cfg():
    """cfg.call_card_cloud_enrichment_enabled truthy -> True."""
    cfg = SimpleNamespace(call_card_cloud_enrichment_enabled=True)
    assert _cloud_enrichment_enabled(cfg) is True


def test_cloud_enrichment_enabled_true_via_call_card_fallback():
    """Attr absent on cfg directly, present + truthy on cfg.call_card -> True."""
    cfg = SimpleNamespace(call_card=SimpleNamespace(call_card_cloud_enrichment_enabled=True))
    assert _cloud_enrichment_enabled(cfg) is True


def test_cloud_enrichment_enabled_false_when_flag_absent_everywhere():
    """cfg has neither the flag nor a .call_card attribute -> fails closed."""
    cfg = SimpleNamespace()
    assert _cloud_enrichment_enabled(cfg) is False


def test_cloud_enrichment_enabled_false_when_call_card_present_but_flag_absent():
    """cfg.call_card exists but doesn't carry the flag either -> fails closed."""
    cfg = SimpleNamespace(call_card=SimpleNamespace())
    assert _cloud_enrichment_enabled(cfg) is False


def test_cloud_enrichment_direct_false_shortcircuits_call_card_fallback():
    """Explicit False directly on cfg wins even if cfg.call_card has it True.

    _cloud_enrichment_enabled returns on the first attribute access that
    succeeds, regardless of truthiness -- unlike _api_key() it does not
    cascade to the call_card fallback when the direct attribute is merely
    falsy. A refactor that made it cascade would silently re-enable cloud
    egress a caller had explicitly turned off.
    """
    cfg = SimpleNamespace(
        call_card_cloud_enrichment_enabled=False,
        call_card=SimpleNamespace(call_card_cloud_enrichment_enabled=True),
    )
    assert _cloud_enrichment_enabled(cfg) is False


# ---------------------------------------------------------------------------
# PostCallEnricher.run(): cloud-enrichment opt-in gate (ti-f6lkw.2)
# ---------------------------------------------------------------------------


def test_cloud_enrichment_disabled_skips_before_api_key_check():
    """Flag False -> run() returns before _api_key, the LLM, or the transcript."""
    store = _store()
    api = MagicMock()
    transcript_store = MagicMock()
    enricher = _enricher(
        cfg=SimpleNamespace(call_card_cloud_enrichment_enabled=False),
        store=store,
        transcript_store=transcript_store,
        api=api,
    )

    with patch("iris.capture.enricher._api_key") as mock_api_key, \
            patch.object(PostCallEnricher, "_call_llm") as mock_llm:
        enricher.run()
        mock_api_key.assert_not_called()
        mock_llm.assert_not_called()

    transcript_store.is_empty.assert_not_called()
    transcript_store.get_turns.assert_not_called()
    store.add_fact.assert_not_called()
    store.upsert_enriched_action_item.assert_not_called()
    store.mark_enrichment_done.assert_not_called()
    api.broadcast.assert_not_called()


def test_cloud_enrichment_disabled_by_default_on_real_config():
    """A fresh, untouched Config() (default False) skips enrichment end-to-end."""
    store = _store()
    api = MagicMock()
    enricher = _enricher(cfg=Config(), store=store, api=api)

    with patch.object(PostCallEnricher, "_call_llm") as mock_llm:
        enricher.run()
        mock_llm.assert_not_called()

    store.mark_enrichment_done.assert_not_called()
    api.broadcast.assert_not_called()


def test_cloud_enrichment_independent_of_haiku_enabled():
    """haiku_enabled=True (the live in-call tier) must not leak into this flag.

    Config().haiku_enabled defaults to True; call_card_cloud_enrichment_enabled
    defaults to False independently -- enabling one must never enable the other.
    """
    cfg = Config(haiku_enabled=True)
    assert cfg.call_card_cloud_enrichment_enabled is False

    store = _store()
    api = MagicMock()
    enricher = _enricher(cfg=cfg, store=store, api=api)

    with patch.object(PostCallEnricher, "_call_llm") as mock_llm:
        enricher.run()
        mock_llm.assert_not_called()

    store.mark_enrichment_done.assert_not_called()
    api.broadcast.assert_not_called()


def test_cloud_enrichment_enabled_reaches_api_key_guard(monkeypatch):
    """Flag True -> passes the new gate through to the pre-existing api-key guard."""
    monkeypatch.delenv("IRIS_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    store = _store()
    api = MagicMock()
    cfg = Config(call_card_cloud_enrichment_enabled=True)
    enricher = _enricher(cfg=cfg, store=store, api=api)

    with patch("iris.capture.enricher._api_key", return_value="") as mock_api_key:
        enricher.run()
        mock_api_key.assert_called_once()

    store.mark_enrichment_done.assert_not_called()
    api.broadcast.assert_not_called()


# ---------------------------------------------------------------------------
# Config: call_card_cloud_enrichment_enabled default (ti-f6lkw.2)
# ---------------------------------------------------------------------------


def test_config_cloud_enrichment_defaults_false():
    """A fresh Config() has cloud enrichment off by default (no-cloud posture)."""
    assert Config().call_card_cloud_enrichment_enabled is False


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
