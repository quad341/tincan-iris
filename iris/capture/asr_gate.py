"""ASR hallucination gate — ti-3p688.3.

Whisper hallucinates on silence/noise, and can be deceptively confident about
it: a hallucinated segment often has a LOW no_speech_prob (the model is sure
it heard *something*) while its avg_logprob is poor (the model isn't sure
WHAT). The existing whole-utterance no_speech_prob gate in
iris/audio/_whisper_stream.py (threshold 0.6) misses exactly this case — see
call-2a178293, where a fabricated "the 8th" reached fact extraction despite
that gate.
"""
from __future__ import annotations

NO_SPEECH_THRESHOLD = 0.6
LOGPROB_THRESHOLD = -1.0


def is_hallucinated_segment(
    text: str, no_speech_prob: float, avg_logprob: float | None = None
) -> bool:
    """True if *text* looks like a Whisper hallucination rather than real speech."""
    if not text or not text.strip():
        return True
    if no_speech_prob > NO_SPEECH_THRESHOLD:
        return True
    return bool(avg_logprob is not None and avg_logprob < LOGPROB_THRESHOLD)
