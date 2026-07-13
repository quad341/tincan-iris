"""CaptureSession hallucination gating (ti-3p688.5, covers ti-3p688.3).

CaptureSession._on_utterance is the ASR/transcript-ingestion boundary --
upstream of both L1CaptureProcessor and the later PostCallEnricher (per
ti-3p688.3's own description). These tests pin the observable contract from
the acceptance criteria: a segment with low ASR confidence / high no-speech
probability must not produce a CapturedFact or ActionItem, while a confident
segment still does.

Real TranscriptStore + L1CaptureProcessor are used (not mocked), so a passing
suite means actual extraction was actually prevented, not just that a mock
wasn't called. Fixtures below were verified against the current, unmodified
processor (e.g. "the 8th" from speaker "far" really does produce a DATE fact
today, normalized_value="2026-08-13" -- that's the reported bug) so a gated
result is a genuine regression guard, not an accident of the extractor never
matching in the first place.

_on_utterance's no_speech_prob/avg_logprob kwargs do not exist yet (ti-3p688.3
is unbuilt) -- every test below fails with a TypeError until the builder adds
them.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

from iris.capture.processor import L1CaptureProcessor
from iris.capture.session import CaptureSession
from iris.capture.transcript import TranscriptStore

_TODAY = date(2026, 7, 13)


def _make_session() -> CaptureSession:
    sess = CaptureSession(
        session_id="s1",
        transcript_store=TranscriptStore(),
        processor=L1CaptureProcessor(now=_TODAY),
        store=MagicMock(),
        on_fact=MagicMock(),
        on_action_item=MagicMock(),
    )
    sess._processor.session_id = "s1"
    return sess


# ---------------------------------------------------------------------------
# the named incident -- call-2a178293's fabricated "the 8th"
# ---------------------------------------------------------------------------

def test_the_8th_hallucination_fixture_produces_no_fact():
    sess = _make_session()

    sess._on_utterance("the 8th", "far", 0.0, no_speech_prob=0.12, avg_logprob=-1.8)

    sess._store.add_fact.assert_not_called()
    sess._on_fact.assert_not_called()


def test_the_8th_with_confident_signal_still_produces_fact():
    # Control: the SAME text with a genuinely confident signal must still pass
    # through -- the gate targets confidence, not the phrase itself.
    sess = _make_session()

    sess._on_utterance("the 8th", "far", 0.0, no_speech_prob=0.05, avg_logprob=-0.2)

    sess._store.add_fact.assert_called_once()
    sess._on_fact.assert_called_once()


# ---------------------------------------------------------------------------
# high no_speech_prob axis
# ---------------------------------------------------------------------------

def test_high_no_speech_prob_segment_produces_no_fact():
    sess = _make_session()

    sess._on_utterance(
        "call me back at 415-555-0100", "far", 0.0, no_speech_prob=0.9, avg_logprob=-0.1
    )

    sess._store.add_fact.assert_not_called()
    sess._on_fact.assert_not_called()


# ---------------------------------------------------------------------------
# poor avg_logprob axis (deceptively low no_speech_prob)
# ---------------------------------------------------------------------------

def test_poor_avg_logprob_segment_produces_no_fact_or_action_item():
    # This text alone yields both a DATE fact and an ActionItem when confident
    # (see test_confident_action_item_still_produces_action_item below) --
    # bad avg_logprob must suppress both, not just one.
    sess = _make_session()

    sess._on_utterance(
        "I'll call you back on the 8th", "far", 0.0, no_speech_prob=0.1, avg_logprob=-1.5
    )

    sess._store.add_fact.assert_not_called()
    sess._on_fact.assert_not_called()
    sess._store.add_action_item.assert_not_called()
    sess._on_action_item.assert_not_called()


# ---------------------------------------------------------------------------
# control -- confident segments still flow through normally
# ---------------------------------------------------------------------------

def test_confident_segment_still_produces_fact():
    sess = _make_session()

    sess._on_utterance(
        "call me back at 415-555-0100", "far", 0.0, no_speech_prob=0.02, avg_logprob=-0.15
    )

    sess._store.add_fact.assert_called_once()
    sess._on_fact.assert_called_once()


def test_confident_action_item_still_produces_action_item():
    sess = _make_session()

    sess._on_utterance(
        "I'll call you back on the 8th", "far", 0.0, no_speech_prob=0.02, avg_logprob=-0.15
    )

    sess._store.add_action_item.assert_called_once()
    sess._on_action_item.assert_called_once()
