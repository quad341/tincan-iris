"""Unit tests for the ASR hallucination gate (ti-3p688.5, covers ti-3p688.3).

Whisper hallucinates on silence/noise -- and can be deceptively confident
about it: a hallucinated segment often has LOW no_speech_prob (the model is
sure it heard *something*) while its avg_logprob is poor (the model isn't
sure WHAT). The existing whole-utterance-average no_speech_prob gate in
iris/audio/_whisper_stream.py (threshold 0.6) misses exactly this case -- see
call-2a178293, where a fabricated "the 8th" reached fact extraction despite
that gate. These tests pin the per-segment predicate that must catch it.

iris.capture.asr_gate does not exist yet (ti-3p688.3 is unbuilt) -- every test
below fails on import until the builder adds it.
"""
from __future__ import annotations

from iris.capture.asr_gate import is_hallucinated_segment


# ---------------------------------------------------------------------------
# no_speech_prob axis (matches the existing _whisper_stream.py precedent: a
# whole-utterance average > 0.6 is already dropped there; this pins the same
# threshold for a single segment's own value)
# ---------------------------------------------------------------------------

def test_high_no_speech_prob_is_gated():
    assert is_hallucinated_segment("Thank you.", no_speech_prob=0.85, avg_logprob=-0.2) is True


def test_no_speech_prob_at_threshold_is_not_gated():
    # _whisper_stream.py's own check is strict `>`, so exactly-at-threshold passes.
    assert is_hallucinated_segment("okay", no_speech_prob=0.6, avg_logprob=-0.2) is False


def test_no_speech_prob_just_above_threshold_is_gated():
    assert is_hallucinated_segment("okay", no_speech_prob=0.61, avg_logprob=-0.2) is True


# ---------------------------------------------------------------------------
# avg_logprob axis -- the signal the existing whole-utterance gate is missing
# ---------------------------------------------------------------------------

def test_low_no_speech_prob_but_poor_logprob_is_gated():
    # The deceptive case: the model is "sure" it heard speech (no_speech_prob
    # low) but isn't confident what it transcribed (avg_logprob poor). This is
    # what let "the 8th" slip past the existing average-no_speech-only gate.
    assert is_hallucinated_segment("the 8th", no_speech_prob=0.12, avg_logprob=-1.6) is True


def test_avg_logprob_at_threshold_is_not_gated():
    assert is_hallucinated_segment("the 8th", no_speech_prob=0.12, avg_logprob=-1.0) is False


def test_avg_logprob_just_below_threshold_is_gated():
    assert is_hallucinated_segment("the 8th", no_speech_prob=0.12, avg_logprob=-1.01) is True


def test_missing_avg_logprob_falls_back_to_no_speech_prob_only():
    assert is_hallucinated_segment("okay", no_speech_prob=0.05, avg_logprob=None) is False
    assert is_hallucinated_segment("okay", no_speech_prob=0.85, avg_logprob=None) is True


# ---------------------------------------------------------------------------
# text axis
# ---------------------------------------------------------------------------

def test_empty_text_is_gated_regardless_of_confidence():
    assert is_hallucinated_segment("", no_speech_prob=0.0, avg_logprob=-0.1) is True


def test_whitespace_only_text_is_gated():
    assert is_hallucinated_segment("   ", no_speech_prob=0.0, avg_logprob=-0.1) is True


# ---------------------------------------------------------------------------
# happy path -- confident, genuine speech is never gated
# ---------------------------------------------------------------------------

def test_confident_genuine_speech_is_not_gated():
    assert is_hallucinated_segment(
        "my account number is 88211", no_speech_prob=0.02, avg_logprob=-0.15
    ) is False


def test_short_confident_reply_is_not_gated():
    # Guards against over-aggressive gating dropping real short replies.
    assert is_hallucinated_segment("okay", no_speech_prob=0.05, avg_logprob=-0.3) is False


def test_the_8th_style_hallucination_fixture_is_gated():
    # The literal reported incident (call-2a178293): a fabricated "the 8th"
    # with deceptively low no_speech_prob. ti-3p688.3's acceptance criteria
    # names this fixture explicitly.
    assert is_hallucinated_segment("the 8th", no_speech_prob=0.12, avg_logprob=-1.8) is True
