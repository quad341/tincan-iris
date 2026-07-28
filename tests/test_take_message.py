"""Tests for TakeMessageFlow — the scripted take-message call dialogue (ti-r4mu).

Uses stubs for TTS, STT, capture, play, hang_up, and emit so no audio hardware
or real processes are needed.
"""
from __future__ import annotations

import pathlib
import tempfile

from iris.take_message import TakeMessageFlow

# ---------------------------------------------------------------------------
# Test harness helpers
# ---------------------------------------------------------------------------

class _FakeTTS:
    def __init__(self) -> None:
        self.spoken: list[str] = []

    def synth(self, text: str) -> str:
        self.spoken.append(text)
        return "/tmp/tts.wav"


class _FakeSTT:
    def __init__(self, answers: list[str]):
        self._q: list[str] = list(answers)

    def transcribe(self, wav_path: str) -> str:
        return self._q.pop(0) if self._q else ""


def _flow(
    *,
    stt_answers: list[str],
    contact_name: str = "Alice",
    disclosure_wav: str | None = None,
) -> tuple[TakeMessageFlow, _FakeTTS, list[tuple]]:
    """Build a TakeMessageFlow with stubs; returns (flow, tts, events).

    tts.spoken records every text string synthesised by the flow.
    """
    events: list[tuple] = []
    tts = _FakeTTS()
    stt = _FakeSTT(stt_answers)

    flow = TakeMessageFlow(
        tts=tts,
        stt=stt,
        play_fn=lambda _: None,
        capture_fn=lambda _s: "/tmp/cap.wav",
        hang_up_fn=lambda: None,
        emit=events.append,
        contact_name=contact_name,
        disclosure_wav=disclosure_wav,
    )
    return flow, tts, events


# ---------------------------------------------------------------------------
# Happy-path flow
# ---------------------------------------------------------------------------

def test_full_flow_emits_done_event_and_hangs_up():
    """Complete flow → take_message_done event emitted with caller name and message."""
    hung_up: list[bool] = []
    events: list[tuple] = []
    tts = _FakeTTS()
    stt = _FakeSTT(["Bob Smith", "Please call me back at 555-1234.", "That's all."])

    flow = TakeMessageFlow(
        tts=tts,
        stt=stt,
        play_fn=lambda _: None,
        capture_fn=lambda _s: "/tmp/cap.wav",
        hang_up_fn=lambda: hung_up.append(True),
        emit=events.append,
        contact_name="Alice",
    )
    flow.run()

    ev = next((e for e in events if e[0] == "take_message_done"), None)
    assert ev is not None
    kind, caller_name, full_message, contact, *_rest = ev
    assert caller_name == "Bob Smith"
    assert "555-1234" in full_message
    assert "That's all" in full_message  # addition appended
    assert contact == "Alice"
    assert len(hung_up) == 1


def test_flow_emits_take_message_done_event():
    """take_message_done event is always emitted, even with empty replies."""
    flow, tts, events = _flow(
        stt_answers=["", "", ""],  # all silence
        contact_name="Bob",
    )
    flow.run()
    assert any(ev[0] == "take_message_done" for ev in events)


def test_caller_name_fallback_when_silent():
    """Empty STT for caller name → falls back to 'the caller'."""
    flow, tts, events = _flow(
        stt_answers=["", "Take a message please.", ""],
        contact_name="Carol",
    )
    flow.run()
    ev = next(ev for ev in events if ev[0] == "take_message_done")
    assert ev[1] == "the caller"


def test_contact_name_in_confirmation():
    """The confirmation phrase includes the contact's display name."""
    flow, tts, events = _flow(
        stt_answers=["Dave", "Call me back.", ""],
        contact_name="Alice",
    )
    flow.run()
    # "Got it — I'll make sure Alice gets this message" in synthesised text
    confirmation_spoken = any(
        "Alice" in text and "gets this message" in text
        for text in tts.spoken
    )
    assert confirmation_spoken


def test_addition_appended_to_message():
    """Non-empty 'anything else' answer is appended to the message transcript."""
    flow, tts, events = _flow(
        stt_answers=["Sam", "Call me back.", "My number is 555-9999."],
        contact_name="Carol",
    )
    flow.run()
    ev = next(ev for ev in events if ev[0] == "take_message_done")
    full_message = ev[2]
    assert "Call me back" in full_message
    assert "555-9999" in full_message


def test_empty_addition_not_appended():
    """Empty 'anything else' does not modify the message transcript."""
    flow, tts, events = _flow(
        stt_answers=["Sam", "Just call me back.", ""],
        contact_name="Carol",
    )
    flow.run()
    ev = next(ev for ev in events if ev[0] == "take_message_done")
    assert ev[2] == "Just call me back."


def test_hang_up_called_at_end():
    """hang_up_fn is always called at the end of the flow."""
    hung_up: list[bool] = []
    tts = _FakeTTS()
    stt = _FakeSTT(["Alice", "Leave a message.", ""])

    flow = TakeMessageFlow(
        tts=tts,
        stt=stt,
        play_fn=lambda _: None,
        capture_fn=lambda _s: "/tmp/x.wav",
        hang_up_fn=lambda: hung_up.append(True),
        emit=lambda _: None,
        contact_name="Bob",
    )
    flow.run()
    assert len(hung_up) == 1


def test_hang_up_called_even_on_crash():
    """hang_up_fn is called even when TTS raises an exception."""
    hung_up: list[bool] = []

    class CrashingTTS:
        def synth(self, text: str) -> str:
            raise RuntimeError("TTS offline")

    flow = TakeMessageFlow(
        tts=CrashingTTS(),
        stt=_FakeSTT([]),
        play_fn=lambda _: None,
        capture_fn=lambda _s: "/tmp/x.wav",
        hang_up_fn=lambda: hung_up.append(True),
        emit=lambda _: None,
        contact_name="Bob",
    )
    flow.run()
    assert len(hung_up) == 1


def test_disclosure_wav_played_when_exists():
    """When disclosure_wav path exists, play_fn is called with it first."""
    played: list[str] = []
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        disc_path = f.name

    tts = _FakeTTS()
    stt = _FakeSTT(["Sam", "Take a message.", ""])

    flow = TakeMessageFlow(
        tts=tts,
        stt=stt,
        play_fn=lambda wav: played.append(wav),
        capture_fn=lambda _s: "/tmp/cap.wav",
        hang_up_fn=lambda: None,
        emit=lambda _: None,
        contact_name="Dave",
        disclosure_wav=disc_path,
    )
    flow.run()
    assert played[0] == disc_path
    pathlib.Path(disc_path).unlink(missing_ok=True)


def test_disclosure_via_tts_when_wav_missing():
    """When disclosure_wav path doesn't exist, inline TTS is used instead."""
    flow, tts, events = _flow(
        stt_answers=["Sam", "Leave a message.", ""],
        contact_name="Dave",
        disclosure_wav="/nonexistent/path/disclosure.wav",
    )
    flow.run()
    assert any("Iris" in t for t in tts.spoken)


def test_three_capture_calls_per_turn():
    """run() makes exactly 3 capture calls: name, message, addition."""
    captured_times: list[float] = []
    tts = _FakeTTS()
    stt = _FakeSTT(["Name", "Message.", ""])

    flow = TakeMessageFlow(
        tts=tts,
        stt=stt,
        play_fn=lambda _: None,
        capture_fn=lambda s: captured_times.append(s) or "/tmp/x.wav",
        hang_up_fn=lambda: None,
        emit=lambda _: None,
        contact_name="Eve",
    )
    flow.run()
    assert len(captured_times) == 3


def test_retry_when_first_message_empty():
    """Empty message triggers a retry prompt and a second capture."""
    captured_times: list[float] = []
    tts = _FakeTTS()
    # first message empty → retry → addition
    stt = _FakeSTT(["Alice", "", "Please ring me.", ""])

    flow = TakeMessageFlow(
        tts=tts,
        stt=stt,
        play_fn=lambda _: None,
        capture_fn=lambda s: captured_times.append(s) or "/tmp/x.wav",
        hang_up_fn=lambda: None,
        emit=lambda _: None,
        contact_name="Bob",
    )
    flow.run()
    # name + first_msg + retry_msg + addition = 4 captures
    assert len(captured_times) == 4


def test_goodbye_phrase_always_synthesised():
    """'Thanks for calling. Goodbye.' is always synthesised at the end."""
    flow, tts, events = _flow(
        stt_answers=["Mike", "Call me.", ""],
        contact_name="Grace",
    )
    flow.run()
    assert any("Goodbye" in t for t in tts.spoken)
