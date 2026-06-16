"""Tests for the Conductor — the UI-agnostic voice pipeline + state machine.
All providers mocked; no audio, no model, no curses, no threads."""
from __future__ import annotations

from unittest.mock import MagicMock

from iris.console.conductor import Conductor, State


def _make(*, muted=False, transcript="hello"):
    stt = MagicMock()
    stt.transcribe.return_value = transcript
    reply = MagicMock()
    reply.text = "hi there"
    reply.lane = "tier1-qwen"
    reply.skill = None
    reply.timeline.summary.return_value = "tier1=+50ms"
    brain = MagicMock()
    brain.respond.return_value = reply
    tts = MagicMock()
    tts.synth.return_value = "/tmp/out.wav"
    rec = MagicMock()
    rec.stop.return_value = "/tmp/in.wav"
    play = MagicMock()
    mic = MagicMock()
    mic.start_capture.return_value = rec
    mic.start_playback.return_value = play
    events: list = []
    c = Conductor(stt, brain, tts, mic, emit=events.append, pick=lambda: "one sec")
    c.muted = muted
    return c, events, mic, play


def _states(events):
    return [e[1] for e in events if e[0] == "state"]


def test_start_recording_sets_state_and_captures():
    c, _events, mic, _ = _make()
    c.start_recording()
    assert c.state is State.RECORDING
    mic.start_capture.assert_called_once()


def test_start_recording_ignored_when_busy():
    c, _events, mic, _ = _make()
    c.start_recording()
    c.start_recording()  # already recording
    assert mic.start_capture.call_count == 1


def test_happy_path_states_and_events():
    c, events, mic, play = _make()
    c.start_recording()
    c.stop_and_respond()
    assert _states(events) == [
        State.RECORDING, State.TRANSCRIBING, State.THINKING,
        State.SPEAKING, State.IDLE,
    ]
    kinds = [e[0] for e in events]
    assert "transcript" in kinds and "reply" in kinds
    mic.start_playback.assert_called_once()
    play.wait.assert_called_once()


def test_muted_skips_playback():
    c, events, mic, _ = _make(muted=True)
    c.start_recording()
    c.stop_and_respond()
    mic.start_playback.assert_not_called()
    assert State.SPEAKING not in _states(events)
    assert c.state is State.IDLE


def test_empty_transcript_returns_idle_without_thinking():
    c, events, _mic, _ = _make(transcript="")
    c.start_recording()
    c.stop_and_respond()
    states = _states(events)
    assert State.THINKING not in states
    assert states[-1] is State.IDLE
    c.brain.respond.assert_not_called()


def test_stt_error_emits_error_and_idles():
    c, events, _mic, _ = _make()
    c.stt.transcribe.side_effect = RuntimeError("boom")
    c.start_recording()
    c.stop_and_respond()
    assert any(e[0] == "error" for e in events)
    assert c.state is State.IDLE


def test_interrupt_stops_playback_and_cancels():
    c, _events, _mic, play = _make()
    c._play = play  # pretend we're mid-playback
    c.interrupt()
    play.stop.assert_called_once()
    assert c._cancel.is_set()
    assert c.state is State.IDLE


def test_toggle_mute():
    c, events, _mic, _ = _make()
    assert c.toggle_mute() is True
    assert c.toggle_mute() is False
    assert ("mute", True) in events


def test_mute_while_speaking_cuts_playback():
    c, _events, _mic, play = _make()
    c._play = play  # pretend mid-utterance
    c.toggle_mute()
    play.stop.assert_called_once()
    assert c.muted is True


def test_respond_to_runs_brain_and_speaks():
    c, events, mic, play = _make()
    c.respond_to("what time is it")  # streaming/listen path: no recording step
    states = _states(events)
    assert State.THINKING in states and State.SPEAKING in states
    assert states[-1] is State.IDLE
    assert any(e[0] == "reply" for e in events)
    mic.start_playback.assert_called_once()
    play.wait.assert_called_once()


def test_respond_to_ignores_empty_and_busy():
    c, events, mic, _ = _make()
    c.respond_to("")  # empty -> nothing
    c.state = State.SPEAKING
    c.respond_to("hi")  # busy -> nothing
    assert events == []
    c.brain.respond.assert_not_called()


def test_respond_to_threads_speaker_operator():
    c, _events, _mic, _play = _make()
    c.respond_to("what time is it", speaker="operator")
    _, kwargs = c.brain.respond.call_args
    assert kwargs.get("speaker") == "operator"


def test_respond_to_threads_speaker_far():
    c, _events, _mic, _play = _make()
    c.respond_to("what time is it", speaker="far")
    _, kwargs = c.brain.respond.call_args
    assert kwargs.get("speaker") == "far"


# --- trust model ---

from iris.trust import TrustMode  # noqa: E402


def test_far_trust_default_is_demo():
    c, _events, _mic, _play = _make()
    assert c.far_trust is TrustMode.DEMO


def test_grant_far_elevates_to_full():
    c, events, _mic, _play = _make()
    c.grant_far()
    assert c.far_trust is TrustMode.FULL
    assert any(e == ("far_trust", TrustMode.FULL) for e in events)


def test_reset_far_trust_restores_demo():
    c, events, _mic, _play = _make()
    c.grant_far()
    c.reset_far_trust()
    assert c.far_trust is TrustMode.DEMO
    assert any(e == ("far_trust", TrustMode.DEMO) for e in events)


def test_far_trust_threaded_to_brain():
    c, _events, _mic, _play = _make()
    c.grant_far()
    c.respond_to("tell me something", speaker="far")
    _, kwargs = c.brain.respond.call_args
    assert kwargs.get("far_trust") is TrustMode.FULL


def test_far_demo_trust_threaded_to_brain():
    c, _events, _mic, _play = _make()
    c.respond_to("tell me something", speaker="far")
    _, kwargs = c.brain.respond.call_args
    assert kwargs.get("far_trust") is TrustMode.DEMO


# --- speaking property (ti-lfp) -----------------------------------------------

def test_speaking_true_in_thinking():
    c, _events, _mic, _play = _make()
    c.state = State.THINKING
    assert c.speaking is True


def test_speaking_true_in_speaking():
    c, _events, _mic, _play = _make()
    c.state = State.SPEAKING
    assert c.speaking is True


def test_speaking_false_in_idle():
    c, _events, _mic, _play = _make()
    assert c.state is State.IDLE
    assert c.speaking is False


def test_speaking_false_in_recording():
    c, _events, _mic, _play = _make()
    c.state = State.RECORDING
    assert c.speaking is False


def test_speaking_false_in_transcribing():
    c, _events, _mic, _play = _make()
    c.state = State.TRANSCRIBING
    assert c.speaking is False
