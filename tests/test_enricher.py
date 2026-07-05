"""Tests for PostCallEnricher's FR6 trust-gate transcript filter (ti-pkt2r.2).

Per iris/capture/enricher.py's module docstring: the transcript sent to the
model includes operator-speaker turns plus any far-speaker turn stamped with
full (BOTH) trust at capture time -- turns captured before the operator
granted full trust stay withheld even if the call is later elevated.

ask_structured is patched to return None (the "no valid response" early-exit
path) purely so run() completes without a real LLM call; each test inspects
the prompt string it was invoked with to verify which turns made it in.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from iris.capture.enricher import PostCallEnricher
from iris.capture.transcript import TranscriptTurn
from iris.trust import TrustMode


def _make_enricher(turns):
    store = MagicMock()
    store.get_call_card.return_value = {"facts": []}
    transcript_store = MagicMock()
    transcript_store.is_empty.return_value = not turns
    transcript_store.get_turns.return_value = turns
    enricher = PostCallEnricher(
        session_id="s1",
        store=store,
        transcript_store=transcript_store,
        api=MagicMock(),
        cfg=MagicMock(),
        cloud=MagicMock(),
    )
    return enricher


@patch("iris.capture.enricher.ask_structured")
def test_operator_turns_always_eligible_regardless_of_trust(mock_ask):
    mock_ask.return_value = None
    turns = [
        TranscriptTurn(turn_id=1, text="operator says hi", speaker="operator",
                       offset_s=0.0, trust=TrustMode.NONE),
    ]
    _make_enricher(turns).run()

    prompt = mock_ask.call_args[0][1]
    assert "operator: operator says hi" in prompt


@patch("iris.capture.enricher.ask_structured")
def test_far_turns_excluded_when_trust_none_or_local(mock_ask):
    mock_ask.return_value = None
    turns = [
        TranscriptTurn(turn_id=1, text="far unarmed", speaker="far",
                       offset_s=0.0, trust=TrustMode.NONE),
        TranscriptTurn(turn_id=2, text="far local only", speaker="far",
                       offset_s=1.0, trust=TrustMode.LOCAL),
    ]
    _make_enricher(turns).run()

    prompt = mock_ask.call_args[0][1]
    assert "far unarmed" not in prompt
    assert "far local only" not in prompt


@patch("iris.capture.enricher.ask_structured")
def test_far_turns_included_when_trust_both(mock_ask):
    mock_ask.return_value = None
    turns = [
        TranscriptTurn(turn_id=1, text="far granted", speaker="far",
                       offset_s=0.0, trust=TrustMode.BOTH),
    ]
    _make_enricher(turns).run()

    prompt = mock_ask.call_args[0][1]
    assert "far: far granted" in prompt


@patch("iris.capture.enricher.ask_structured")
def test_mixed_trust_transcript_only_operator_and_both_survive(mock_ask):
    """Regression: a call that starts unarmed and gets armed mid-call must
    still withhold the pre-grant far turns -- trust is stamped per-turn at
    capture time and never re-evaluated retroactively (ti-pkt2r.2)."""
    mock_ask.return_value = None
    turns = [
        TranscriptTurn(turn_id=1, text="op opens", speaker="operator",
                       offset_s=0.0, trust=TrustMode.NONE),
        TranscriptTurn(turn_id=2, text="far before grant", speaker="far",
                       offset_s=1.0, trust=TrustMode.NONE),
        TranscriptTurn(turn_id=3, text="op grants", speaker="operator",
                       offset_s=2.0, trust=TrustMode.BOTH),
        TranscriptTurn(turn_id=4, text="far after grant", speaker="far",
                       offset_s=3.0, trust=TrustMode.BOTH),
    ]
    _make_enricher(turns).run()

    prompt = mock_ask.call_args[0][1]
    assert "op opens" in prompt
    assert "op grants" in prompt
    assert "far after grant" in prompt
    assert "far before grant" not in prompt
