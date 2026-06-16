"""Tests for ScreenCallFlow and ScreenPivotFlow (ti-pwms / ti-eki3).

Uses stubs for TTS, STT, capture, play, relay, get_decision, put_through,
and hang_up — no audio hardware or real processes needed.
"""
from __future__ import annotations

import pathlib
import tempfile

import pytest

from iris.screen_call import ScreenCallFlow, ScreenPivotFlow


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
    decision: str = "take_message",
    contact_name: str = "Alice",
    caller_number: str = "+15555550101",
    disclosure_wav: str | None = None,
    relay_timeout_s: float = 20.0,
) -> tuple[ScreenCallFlow, _FakeTTS, list[str], list[tuple], list[bool], list[bool]]:
    """Build a ScreenCallFlow with stubs.

    Returns (flow, tts, relayed, events, hung_up_calls, put_through_calls).
    """
    tts = _FakeTTS()
    stt = _FakeSTT(stt_answers)
    relayed: list[str] = []
    events: list[tuple] = []
    hung_up_calls: list[bool] = []
    put_through_calls: list[bool] = []

    flow = ScreenCallFlow(
        tts=tts,
        stt=stt,
        play_fn=lambda _: None,
        capture_fn=lambda _s: "/tmp/cap.wav",
        relay_fn=lambda text: relayed.append(text),
        get_decision=lambda _timeout: decision,
        put_through_fn=lambda: put_through_calls.append(True),
        hang_up_fn=lambda: hung_up_calls.append(True),
        emit=events.append,
        contact_name=contact_name,
        caller_number=caller_number,
        disclosure_wav=disclosure_wav,
        relay_timeout_s=relay_timeout_s,
    )
    return flow, tts, relayed, events, hung_up_calls, put_through_calls


# ---------------------------------------------------------------------------
# Happy-path: operator takes message
# ---------------------------------------------------------------------------

def test_take_message_decision_emits_screen_take_message():
    """Operator says 'take_message' → emit screen_take_message event."""
    flow, tts, relayed, events, hung_up, put_through = _flow(
        stt_answers=["Bob Smith from Acme."],
        decision="take_message",
    )
    flow.run()

    ev = next((e for e in events if e[0] == "screen_take_message"), None)
    assert ev is not None
    assert "Bob Smith" in ev[1]
    assert ev[2] == "+15555550101"


def test_take_message_does_not_hang_up():
    """After emitting screen_take_message, the flow exits without hanging up.

    The console owns the call from here; hang up is the take_message flow's job.
    """
    flow, tts, relayed, events, hung_up, put_through = _flow(
        stt_answers=["It's Dave from the garage."],
        decision="take_message",
    )
    flow.run()
    assert len(hung_up) == 0


def test_take_message_does_not_call_put_through():
    flow, tts, relayed, events, hung_up, put_through = _flow(
        stt_answers=["Sam."],
        decision="take_message",
    )
    flow.run()
    assert len(put_through) == 0


# ---------------------------------------------------------------------------
# Happy-path: operator puts through
# ---------------------------------------------------------------------------

def test_put_through_calls_put_through_fn():
    """Operator says 'put_through' → put_through_fn() is called."""
    flow, tts, relayed, events, hung_up, put_through = _flow(
        stt_answers=["It's Laura calling about the contract."],
        decision="put_through",
    )
    flow.run()
    assert len(put_through) == 1


def test_put_through_emits_screen_put_through():
    flow, tts, relayed, events, hung_up, put_through = _flow(
        stt_answers=["Jane from HR."],
        decision="put_through",
    )
    flow.run()
    ev = next((e for e in events if e[0] == "screen_put_through"), None)
    assert ev is not None


def test_put_through_does_not_hang_up():
    """Putting through leaves the call connected — hang_up must NOT be called."""
    flow, tts, relayed, events, hung_up, put_through = _flow(
        stt_answers=["Tom."],
        decision="put_through",
    )
    flow.run()
    assert len(hung_up) == 0


# ---------------------------------------------------------------------------
# Happy-path: operator declines
# ---------------------------------------------------------------------------

def test_decline_says_goodbye_to_caller():
    """Operator declines → Iris says goodbye to the caller."""
    flow, tts, relayed, events, hung_up, put_through = _flow(
        stt_answers=["A telemarketer."],
        decision="decline",
    )
    flow.run()
    assert any("Goodbye" in t for t in tts.spoken)


def test_decline_hangs_up():
    flow, tts, relayed, events, hung_up, put_through = _flow(
        stt_answers=["Caller."],
        decision="decline",
    )
    flow.run()
    assert len(hung_up) == 1


def test_decline_emits_screen_declined():
    flow, tts, relayed, events, hung_up, put_through = _flow(
        stt_answers=["Unknown caller."],
        decision="decline",
    )
    flow.run()
    ev = next((e for e in events if e[0] == "screen_declined"), None)
    assert ev is not None


# ---------------------------------------------------------------------------
# Timeout → auto-pivot to take_message
# ---------------------------------------------------------------------------

def test_timeout_pivots_to_take_message():
    """Empty decision (timeout) → emit screen_take_message."""
    flow, tts, relayed, events, hung_up, put_through = _flow(
        stt_answers=["It's John."],
        decision="",  # timeout
    )
    flow.run()
    ev = next((e for e in events if e[0] == "screen_take_message"), None)
    assert ev is not None


def test_timeout_does_not_hang_up():
    flow, tts, relayed, events, hung_up, put_through = _flow(
        stt_answers=["John."],
        decision="",
    )
    flow.run()
    assert len(hung_up) == 0


# ---------------------------------------------------------------------------
# Relay to operator
# ---------------------------------------------------------------------------

def test_caller_intro_relayed_to_operator():
    """Caller intro is passed to relay_fn before waiting for decision."""
    flow, tts, relayed, events, hung_up, put_through = _flow(
        stt_answers=["It's Mike from the hardware store."],
    )
    flow.run()
    assert len(relayed) == 1
    assert "Mike" in relayed[0]


def test_relay_includes_decision_prompt():
    """Relay text always ends with the put-through/take-message question."""
    flow, tts, relayed, events, hung_up, put_through = _flow(
        stt_answers=["Janet."],
    )
    flow.run()
    assert "put them through" in relayed[0].lower() or "take a message" in relayed[0].lower()


def test_relay_truncates_long_intro_to_20_words():
    """Caller intro longer than 20 words is truncated in the relay."""
    long_intro = " ".join(f"word{i}" for i in range(30))
    flow, tts, relayed, events, hung_up, put_through = _flow(
        stt_answers=[long_intro],
    )
    flow.run()
    relay_intro = relayed[0].split(".")[0]
    word_count = len(relay_intro.split())
    assert word_count <= 21  # ≤20 words + possible trailing ellipsis token


# ---------------------------------------------------------------------------
# Silence / re-ask handling
# ---------------------------------------------------------------------------

def test_silence_triggers_reask():
    """First capture empty → re-ask with shorter window."""
    captured_windows: list[float] = []
    tts = _FakeTTS()
    stt = _FakeSTT(["", "It's Sam."])
    relayed: list[str] = []

    flow = ScreenCallFlow(
        tts=tts,
        stt=stt,
        play_fn=lambda _: None,
        capture_fn=lambda s: (captured_windows.append(s), "/tmp/cap.wav")[1],
        relay_fn=lambda t: relayed.append(t),
        get_decision=lambda _: "take_message",
        put_through_fn=lambda: None,
        hang_up_fn=lambda: None,
        emit=lambda _: None,
        contact_name="Alice",
    )
    flow.run()

    # First window (10 s) + re-ask window (5 s)
    assert len(captured_windows) == 2
    assert captured_windows[0] > captured_windows[1]  # first window is longer


def test_double_silence_hangs_up_with_farewell():
    """Two consecutive silences → Iris says farewell and hangs up."""
    hung_up: list[bool] = []
    tts = _FakeTTS()
    stt = _FakeSTT(["", ""])
    events: list[tuple] = []

    flow = ScreenCallFlow(
        tts=tts,
        stt=stt,
        play_fn=lambda _: None,
        capture_fn=lambda _s: "/tmp/cap.wav",
        relay_fn=lambda _: None,
        get_decision=lambda _: "take_message",
        put_through_fn=lambda: None,
        hang_up_fn=lambda: hung_up.append(True),
        emit=events.append,
        contact_name="Carol",
    )
    flow.run()

    assert len(hung_up) == 1
    assert any("someone called" in t.lower() for t in tts.spoken)


def test_double_silence_emits_declined():
    """Two consecutive silences → emit screen_declined."""
    events: list[tuple] = []
    tts = _FakeTTS()
    stt = _FakeSTT(["", ""])

    flow = ScreenCallFlow(
        tts=tts,
        stt=stt,
        play_fn=lambda _: None,
        capture_fn=lambda _s: "/tmp/cap.wav",
        relay_fn=lambda _: None,
        get_decision=lambda _: "take_message",
        put_through_fn=lambda: None,
        hang_up_fn=lambda: None,
        emit=events.append,
        contact_name="Bob",
    )
    flow.run()

    ev = next((e for e in events if e[0] == "screen_declined"), None)
    assert ev is not None


def test_double_silence_does_not_relay():
    """When caller is silent, we never relay — the call ends before step 4."""
    relayed: list[str] = []
    tts = _FakeTTS()
    stt = _FakeSTT(["", ""])

    flow = ScreenCallFlow(
        tts=tts,
        stt=stt,
        play_fn=lambda _: None,
        capture_fn=lambda _s: "/tmp/cap.wav",
        relay_fn=lambda t: relayed.append(t),
        get_decision=lambda _: "take_message",
        put_through_fn=lambda: None,
        hang_up_fn=lambda: None,
        emit=lambda _: None,
        contact_name="Alice",
    )
    flow.run()
    assert relayed == []


# ---------------------------------------------------------------------------
# Disclosure WAV
# ---------------------------------------------------------------------------

def test_disclosure_wav_played_when_exists():
    """Pre-rendered disclosure WAV is played to the caller first."""
    played: list[str] = []
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        disc_path = f.name

    tts = _FakeTTS()
    stt = _FakeSTT(["Bob."])

    flow = ScreenCallFlow(
        tts=tts,
        stt=stt,
        play_fn=lambda wav: played.append(wav),
        capture_fn=lambda _s: "/tmp/cap.wav",
        relay_fn=lambda _: None,
        get_decision=lambda _: "take_message",
        put_through_fn=lambda: None,
        hang_up_fn=lambda: None,
        emit=lambda _: None,
        contact_name="Alice",
        disclosure_wav=disc_path,
    )
    flow.run()
    assert played[0] == disc_path
    pathlib.Path(disc_path).unlink(missing_ok=True)


def test_disclosure_via_tts_when_wav_missing():
    """When disclosure WAV path doesn't exist, inline TTS fallback is used."""
    flow, tts, relayed, events, hung_up, put_through = _flow(
        stt_answers=["Sam."],
        disclosure_wav="/nonexistent/disclosure.wav",
    )
    flow.run()
    assert any("Iris" in t for t in tts.spoken)


# ---------------------------------------------------------------------------
# Crash safety
# ---------------------------------------------------------------------------

def test_hang_up_called_on_crash():
    """hang_up_fn is called even when TTS raises."""
    hung_up: list[bool] = []

    class CrashingTTS:
        def synth(self, text: str) -> str:
            raise RuntimeError("TTS offline")

    flow = ScreenCallFlow(
        tts=CrashingTTS(),
        stt=_FakeSTT([]),
        play_fn=lambda _: None,
        capture_fn=lambda _s: "/tmp/cap.wav",
        relay_fn=lambda _: None,
        get_decision=lambda _: "take_message",
        put_through_fn=lambda: None,
        hang_up_fn=lambda: hung_up.append(True),
        emit=lambda _: None,
        contact_name="Alice",
    )
    flow.run()
    assert len(hung_up) == 1


# ===========================================================================
# ScreenPivotFlow — abbreviated take-message after screen pivot (ti-eki3)
# ===========================================================================

def _pivot(
    *,
    stt_answers: list[str],
    caller_name: str = "Bob Smith",
    caller_number: str = "+15555550202",
    contact_name: str = "Alice",
) -> tuple[ScreenPivotFlow, _FakeTTS, list[tuple], list[bool]]:
    """Build a ScreenPivotFlow with stubs; returns (flow, tts, events, hung_up)."""
    tts = _FakeTTS()
    stt = _FakeSTT(stt_answers)
    events: list[tuple] = []
    hung_up: list[bool] = []

    flow = ScreenPivotFlow(
        tts=tts,
        stt=stt,
        play_fn=lambda _: None,
        capture_fn=lambda _s: "/tmp/cap.wav",
        hang_up_fn=lambda: hung_up.append(True),
        emit=events.append,
        caller_name=caller_name,
        caller_number=caller_number,
        contact_name=contact_name,
    )
    return flow, tts, events, hung_up


def test_pivot_emits_take_message_done():
    """Pivot emits take_message_done event (same as TakeMessageFlow)."""
    flow, tts, events, hung_up = _pivot(stt_answers=["My number is 555-1234."])
    flow.run()
    ev = next((e for e in events if e[0] == "take_message_done"), None)
    assert ev is not None


def test_pivot_event_contains_caller_name():
    """take_message_done carries the caller_name from screening."""
    flow, tts, events, hung_up = _pivot(
        stt_answers=["Just call me back."],
        caller_name="Janet Doe",
    )
    flow.run()
    ev = next(e for e in events if e[0] == "take_message_done")
    assert ev[1] == "Janet Doe"


def test_pivot_event_contains_addition():
    """take_message_done carries the caller's addition as the transcript."""
    flow, tts, events, hung_up = _pivot(
        stt_answers=["Reach me at 555-9999 after 3pm."],
    )
    flow.run()
    ev = next(e for e in events if e[0] == "take_message_done")
    assert "555-9999" in ev[2]


def test_pivot_event_contains_contact_name():
    """take_message_done carries the contact_name from the roster."""
    flow, tts, events, hung_up = _pivot(
        stt_answers=["Thanks."],
        contact_name="Grace",
    )
    flow.run()
    ev = next(e for e in events if e[0] == "take_message_done")
    assert ev[3] == "Grace"


def test_pivot_event_contains_caller_number():
    flow, tts, events, hung_up = _pivot(
        stt_answers=["Done."],
        caller_number="+19995550101",
    )
    flow.run()
    ev = next(e for e in events if e[0] == "take_message_done")
    assert ev[4] == "+19995550101"


def test_pivot_hangs_up():
    flow, tts, events, hung_up = _pivot(stt_answers=["That's all."])
    flow.run()
    assert len(hung_up) == 1


def test_pivot_says_goodbye():
    flow, tts, events, hung_up = _pivot(stt_answers=["No, that's it."])
    flow.run()
    assert any("Goodbye" in t for t in tts.spoken)


def test_pivot_says_pass_along():
    """The pivot greeting starts with 'I'll pass that along'."""
    flow, tts, events, hung_up = _pivot(stt_answers=[""])
    flow.run()
    assert any("pass that along" in t.lower() for t in tts.spoken)


def test_pivot_only_one_capture():
    """Pivot captures exactly once (no name-ask, no message-ask)."""
    captured: list[float] = []
    tts = _FakeTTS()
    stt = _FakeSTT(["My number is 555-0000."])

    flow = ScreenPivotFlow(
        tts=tts,
        stt=stt,
        play_fn=lambda _: None,
        capture_fn=lambda s: (captured.append(s), "/tmp/cap.wav")[1],
        hang_up_fn=lambda: None,
        emit=lambda _: None,
        caller_name="Sam",
        contact_name="Carol",
    )
    flow.run()
    assert len(captured) == 1


def test_pivot_empty_addition_still_emits():
    """Silent caller → take_message_done still emitted with empty transcript."""
    flow, tts, events, hung_up = _pivot(stt_answers=[""])
    flow.run()
    ev = next((e for e in events if e[0] == "take_message_done"), None)
    assert ev is not None
    assert ev[2] == ""


def test_pivot_crash_safe():
    """hang_up_fn is called even when TTS crashes."""
    hung_up: list[bool] = []

    class CrashingTTS:
        def synth(self, text: str) -> str:
            raise RuntimeError("TTS offline")

    flow = ScreenPivotFlow(
        tts=CrashingTTS(),
        stt=_FakeSTT([]),
        play_fn=lambda _: None,
        capture_fn=lambda _s: "/tmp/cap.wav",
        hang_up_fn=lambda: hung_up.append(True),
        emit=lambda _: None,
        caller_name="Sam",
        contact_name="Carol",
    )
    flow.run()
    assert len(hung_up) == 1
