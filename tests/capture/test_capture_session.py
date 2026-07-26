"""Unit tests for iris/capture/session.py — CaptureSession (ti-rnlqo.3.4).

Tests are written BEFORE the implementation lands; they will fail (red) until
iris/capture/session.py, iris/capture/store.py, iris/capture/schemas.py, and
iris/capture/transcript.py are all present.

No audio hardware required — StreamingTranscribers are created in __init__ but
tests exercise _on_utterance() directly, bypassing the audio capture threads.

Documented contract:
  CaptureSession(*, session_id, transcript_store, processor, store,
                 on_fact, on_action_item)
    ._on_utterance(text, speaker, offset_s)
        → transcript_store.append(text, speaker, offset_s) -> turn_id
        → processor.process(text, speaker, turn_id, offset_s) -> list
        → for CapturedFact results: store.add_fact(fact), on_fact(fact)
        → for ActionItem results: store.add_action_item(item), on_action_item(item)
        → exceptions from processor.process are caught, not propagated
    .stop()  → safe to call before start() (no-op on unstarted transcribers)
"""
from __future__ import annotations

from unittest.mock import MagicMock

from iris.capture.schemas import ActionItem, CapturedFact, FactType
from iris.capture.session import CaptureSession
from iris.capture.transcript import TranscriptStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fact(session_id="sess-1"):
    return CapturedFact(
        session_id=session_id,
        fact_type=FactType.PHONE,
        raw_text="call me at 415-555-1234",
        normalized_value="+14155551234",
        transcript_turn_id=1,
        transcript_offset_s=10.0,
        speaker="far",
        confidence=0.9,
        critical=True,
    )


def _make_action_item(session_id="sess-1"):
    return ActionItem(
        session_id=session_id,
        description="I'll call you back",
        trigger="I'll",
        owner="operator",
        transcript_turn_id=2,
        transcript_offset_s=20.0,
        speaker="operator",
        confidence=0.85,
    )


def _make_session(*, processor_results=None, session_id="sess-1"):
    """Return (CaptureSession, store_mock, processor_mock, transcript_store_mock,
    on_fact_calls, on_action_item_calls)."""
    transcript_store = MagicMock(spec=TranscriptStore)
    transcript_store.append.return_value = 1  # turn_id

    processor = MagicMock()
    processor.process.return_value = processor_results or []

    store = MagicMock()
    on_fact_calls: list = []
    on_ai_calls: list = []

    session = CaptureSession(
        session_id=session_id,
        transcript_store=transcript_store,
        processor=processor,
        store=store,
        on_fact=on_fact_calls.append,
        on_action_item=on_ai_calls.append,
    )
    return session, store, processor, transcript_store, on_fact_calls, on_ai_calls


# ---------------------------------------------------------------------------
# 1. _on_utterance routing: transcript_store.append called
# ---------------------------------------------------------------------------


def test_on_utterance_calls_transcript_store_append():
    """_on_utterance calls transcript_store.append(text, speaker, offset_s)."""
    session, _, _, ts, _, _ = _make_session()
    session._on_utterance("hello", "far", 5.0)
    ts.append.assert_called_once_with("hello", "far", 5.0)


# ---------------------------------------------------------------------------
# 2. _on_utterance routing: processor.process called with turn_id from append
# ---------------------------------------------------------------------------


def test_on_utterance_calls_processor_process_with_turn_id():
    """_on_utterance passes the turn_id returned by transcript_store.append to processor."""
    session, _, proc, ts, _, _ = _make_session()
    ts.append.return_value = 42  # specific turn_id
    session._on_utterance("hello", "far", 5.0)
    proc.process.assert_called_once_with("hello", "far", 42, 5.0)


# ---------------------------------------------------------------------------
# 3. _on_utterance routing: CapturedFact results dispatched to store + callback
# ---------------------------------------------------------------------------


def test_on_utterance_routes_fact_to_store_and_callback():
    """CapturedFact returned by processor goes to store.add_fact() and on_fact callback."""
    fact = _make_fact()
    session, store, _, _, on_fact_calls, _ = _make_session(processor_results=[fact])
    session._on_utterance("call me at 415-555-1234", "far", 10.0)
    store.add_fact.assert_called_once_with(fact)
    assert on_fact_calls == [fact]


# ---------------------------------------------------------------------------
# 4. _on_utterance routing: ActionItem results dispatched to store + callback
# ---------------------------------------------------------------------------


def test_on_utterance_routes_action_item_to_store_and_callback():
    """ActionItem returned by processor goes to store.add_action_item() and on_action_item callback."""
    item = _make_action_item()
    session, store, _, _, _, on_ai_calls = _make_session(processor_results=[item])
    session._on_utterance("I'll call you back", "operator", 20.0)
    store.add_action_item.assert_called_once_with(item)
    assert on_ai_calls == [item]


# ---------------------------------------------------------------------------
# 5. _on_utterance routing: mixed results (CapturedFact + ActionItem)
# ---------------------------------------------------------------------------


def test_on_utterance_routes_mixed_results():
    """Mixed processor output: both store and callbacks receive the right objects."""
    fact = _make_fact()
    item = _make_action_item()
    session, store, _, _, on_fact_calls, on_ai_calls = _make_session(
        processor_results=[fact, item]
    )
    session._on_utterance("text", "far", 0.0)
    store.add_fact.assert_called_once_with(fact)
    store.add_action_item.assert_called_once_with(item)
    assert on_fact_calls == [fact]
    assert on_ai_calls == [item]


# ---------------------------------------------------------------------------
# 6. Exception in processor.process is caught and does not propagate
# ---------------------------------------------------------------------------


def test_processor_exception_does_not_propagate():
    """If processor.process raises, _on_utterance catches it and returns normally."""
    session, _, proc, _, _, _ = _make_session()
    proc.process.side_effect = ValueError("extractor crash")
    # Must not raise
    session._on_utterance("text", "far", 0.0)


# ---------------------------------------------------------------------------
# 7. stop() before start() does not raise
# ---------------------------------------------------------------------------


def test_stop_before_start_does_not_raise():
    """Calling stop() on a session that was never started does not raise."""
    session, _, _, _, _, _ = _make_session()
    session.stop()  # StreamingTranscriber.stop() is a no-op when not started


# ---------------------------------------------------------------------------
# 8. Multiple utterances accumulate correctly
# ---------------------------------------------------------------------------


def test_multiple_utterances_each_call_transcript_and_processor():
    """Calling _on_utterance three times results in three append + process calls."""
    fact1 = _make_fact()
    fact2 = _make_fact()
    processor = MagicMock()
    processor.process.side_effect = [[fact1], [fact2], []]
    ts = MagicMock(spec=TranscriptStore)
    ts.append.side_effect = [1, 2, 3]  # turn_ids
    store = MagicMock()
    on_facts: list = []
    session = CaptureSession(
        session_id="sess-1",
        transcript_store=ts,
        processor=processor,
        store=store,
        on_fact=on_facts.append,
        on_action_item=lambda _: None,
    )
    session._on_utterance("utt1", "far", 1.0)
    session._on_utterance("utt2", "operator", 2.0)
    session._on_utterance("utt3", "far", 3.0)

    assert ts.append.call_count == 3
    assert processor.process.call_count == 3
    assert len(on_facts) == 2  # fact1 + fact2; third utterance had no results
