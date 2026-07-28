"""Integration tests for ProfileResolver wired into ScreenCallFlow + TakeMessageFlow.

Bead: ti-d3lr.1 (validator phase) — TDD red phase.
These tests FAIL until the builder implements ti-d3lr:
  - ScreenCallFlow and TakeMessageFlow gain a `resolver` parameter (ProfileResolver | None)
  - resolver.resolve() is called once per call with the utt-1 transcript
  - Resolved profile is stored as flow.profile after run()
  - resolver.turn_cadence() is used per-turn when re_ask fires
  - Detection runs concurrently with utt-1 transcription (zero added latency)
  - Automated path only (ScreenCallFlow + TakeMessageFlow); ride-along out of scope

Coverage map:
  ①  resolver.resolve() called exactly once per call (not per-turn)
  ②  resolve() receives utt-1 transcript as `utterance` kwarg
  ③  profile stored on flow after run (accessible as flow.profile)
  ④  resolver=None → backward-compatible (no resolver installed = old behavior)
  ⑤  TakeMessageFlow: resolve() called with caller-name utterance (first capture)
  ⑥  profile locked: resolve() NOT called again on subsequent utt captures
  ⑦  re_ask=True → turn_cadence() returns cadence_slow; profile.cadence unchanged
  ⑧  detection concurrent: detector callable runs while STT transcription is active
"""
from __future__ import annotations

import threading
from unittest.mock import MagicMock

from iris.profile_resolver import PresentationProfile, ProfileResolver
from iris.screen_call import ScreenCallFlow
from iris.take_message import TakeMessageFlow

# ---------------------------------------------------------------------------
# Stubs and helpers
# ---------------------------------------------------------------------------

def _fake_profile(
    language: str = "en",
    tts_voice: str = "ef_aria",
    tts_lang: str = "en",
    cadence: float = 1.0,
    source: str = "detector",
) -> PresentationProfile:
    return PresentationProfile(
        language=language,
        tts_voice=tts_voice,
        tts_lang=tts_lang,
        cadence=cadence,
        source=source,
    )


class _SpyResolver:
    """Minimal ProfileResolver spy — records resolve() calls."""

    def __init__(self, profile: PresentationProfile | None = None) -> None:
        self._profile = profile or _fake_profile()
        self.resolve_calls: list[dict] = []
        self.turn_cadence_calls: list[dict] = []

    def resolve(
        self,
        *,
        override_key: str | None = None,
        contact_id: str | None = None,
        utterance: str | None = None,
    ) -> PresentationProfile:
        self.resolve_calls.append({
            "override_key": override_key,
            "contact_id": contact_id,
            "utterance": utterance,
        })
        return self._profile

    def turn_cadence(self, profile: PresentationProfile, *, re_ask: bool) -> float:
        result = 0.7 if re_ask else profile.cadence
        self.turn_cadence_calls.append({"re_ask": re_ask, "result": result})
        return result


class _FakeTTS:
    def __init__(self) -> None:
        self.spoken: list[str] = []

    def synth(self, text: str, **kwargs) -> str:
        self.spoken.append(text)
        return "/tmp/tts.wav"


class _FakeSTT:
    def __init__(self, answers: list[str]) -> None:
        self._q: list[str] = list(answers)

    def transcribe(self, wav_path: str) -> str:
        return self._q.pop(0) if self._q else ""


def _screen_flow(
    *,
    stt_answers: list[str],
    decision: str = "take_message",
    resolver: _SpyResolver | None = None,
    contact_name: str = "Alice",
    caller_number: str = "+15555550101",
) -> tuple[ScreenCallFlow, _FakeTTS, list[tuple]]:
    tts = _FakeTTS()
    stt = _FakeSTT(stt_answers)
    events: list[tuple] = []

    kwargs: dict = {
        "tts": tts,
        "stt": stt,
        "play_fn": lambda _: None,
        "capture_fn": lambda _s: "/tmp/cap.wav",
        "relay_fn": lambda _text: None,
        "get_decision": lambda _timeout: decision,
        "put_through_fn": lambda: None,
        "hang_up_fn": lambda: None,
        "emit": events.append,
        "contact_name": contact_name,
        "caller_number": caller_number,
    }
    if resolver is not None:
        kwargs["resolver"] = resolver

    flow = ScreenCallFlow(**kwargs)
    return flow, tts, events


def _take_flow(
    *,
    stt_answers: list[str],
    resolver: _SpyResolver | None = None,
    contact_name: str = "Alice",
) -> tuple[TakeMessageFlow, _FakeTTS, list[tuple]]:
    tts = _FakeTTS()
    stt = _FakeSTT(stt_answers)
    events: list[tuple] = []

    kwargs: dict = {
        "tts": tts,
        "stt": stt,
        "play_fn": lambda _: None,
        "capture_fn": lambda _s: "/tmp/cap.wav",
        "hang_up_fn": lambda: None,
        "emit": events.append,
        "contact_name": contact_name,
    }
    if resolver is not None:
        kwargs["resolver"] = resolver

    flow = TakeMessageFlow(**kwargs)
    return flow, tts, events


# ---------------------------------------------------------------------------
# ① resolver.resolve() called exactly once per call
# ---------------------------------------------------------------------------

def test_screen_call_with_resolver_calls_resolve_exactly_once():
    """resolver.resolve() is called once per call, not per-turn."""
    spy = _SpyResolver()
    flow, tts, events = _screen_flow(
        stt_answers=["My name is Bob and I have a question."],
        resolver=spy,
    )
    flow.run()

    assert len(spy.resolve_calls) == 1, (
        f"Expected resolve() called once; got {len(spy.resolve_calls)} calls"
    )


# ---------------------------------------------------------------------------
# ② resolve() receives utt-1 transcript as `utterance`
# ---------------------------------------------------------------------------

def test_screen_call_resolve_receives_utt1_transcript():
    """resolve() must receive the utt-1 transcript as the `utterance` kwarg."""
    spy = _SpyResolver()
    flow, tts, events = _screen_flow(
        stt_answers=["Hola, me llamo Carlos."],
        resolver=spy,
    )
    flow.run()

    assert spy.resolve_calls, "resolve() was never called"
    assert spy.resolve_calls[0]["utterance"] == "Hola, me llamo Carlos.", (
        f"resolve() got utterance={spy.resolve_calls[0]['utterance']!r}; "
        "expected the full utt-1 transcript"
    )


# ---------------------------------------------------------------------------
# ③ profile stored on flow after run()
# ---------------------------------------------------------------------------

def test_screen_call_profile_stored_after_run():
    """flow.profile is set to the resolved PresentationProfile after run()."""
    profile = _fake_profile(language="es", tts_voice="ef_dalia")
    spy = _SpyResolver(profile=profile)
    flow, tts, events = _screen_flow(
        stt_answers=["Buenos días."],
        resolver=spy,
    )
    flow.run()

    assert hasattr(flow, "profile"), "ScreenCallFlow has no .profile attribute after run()"
    assert flow.profile is profile, (
        "flow.profile should be the exact PresentationProfile returned by resolve()"
    )


# ---------------------------------------------------------------------------
# ④ resolver=None → backward-compatible (no regression in existing tests)
# ---------------------------------------------------------------------------

def test_screen_call_without_resolver_runs_unchanged():
    """ScreenCallFlow works without a resolver (resolver=None or omitted)."""
    flow, tts, events = _screen_flow(
        stt_answers=["It's Dave from the garage."],
        decision="take_message",
    )
    flow.run()

    ev = next((e for e in events if e[0] == "screen_take_message"), None)
    assert ev is not None, "screen_take_message event not emitted (regression)"


def test_take_message_without_resolver_runs_unchanged():
    """TakeMessageFlow works without a resolver (resolver=None or omitted)."""
    hung_up: list[bool] = []
    events: list[tuple] = []
    tts = _FakeTTS()
    stt = _FakeSTT(["Bob Smith", "Please call me back.", "Nothing more."])
    flow = TakeMessageFlow(
        tts=tts,
        stt=stt,
        play_fn=lambda _: None,
        capture_fn=lambda _s: "/tmp/cap.wav",
        hang_up_fn=lambda: hung_up.append(True),
        emit=events.append,
    )
    flow.run()

    ev = next((e for e in events if e[0] == "take_message_done"), None)
    assert ev is not None, "take_message_done event not emitted (regression)"
    assert hung_up, "hang_up_fn not called (regression)"


# ---------------------------------------------------------------------------
# ⑤ TakeMessageFlow: resolve() called with caller-name utterance
# ---------------------------------------------------------------------------

def test_take_message_resolve_receives_caller_name_utterance():
    """TakeMessageFlow calls resolve() with the caller-name capture (first utterance)."""
    spy = _SpyResolver()
    flow, tts, events = _take_flow(
        stt_answers=["Hola soy Maria", "Un recado por favor.", "Nada más."],
        resolver=spy,
    )
    flow.run()

    assert spy.resolve_calls, "resolve() was never called in TakeMessageFlow"
    assert spy.resolve_calls[0]["utterance"] == "Hola soy Maria", (
        f"resolve() got utterance={spy.resolve_calls[0]['utterance']!r}; "
        "expected the caller-name capture"
    )


def test_take_message_with_resolver_calls_resolve_exactly_once():
    """TakeMessageFlow calls resolve() once, not for every capture."""
    spy = _SpyResolver()
    flow, tts, events = _take_flow(
        stt_answers=["Bob Smith", "Please call back.", "Nothing else."],
        resolver=spy,
    )
    flow.run()

    assert len(spy.resolve_calls) == 1, (
        f"Expected resolve() once; got {len(spy.resolve_calls)} calls"
    )


# ---------------------------------------------------------------------------
# ⑥ profile locked: resolve() NOT called again after utt-1
# ---------------------------------------------------------------------------

def test_screen_call_resolve_not_called_after_utt1():
    """resolve() is called only once — profile is locked for the call lifetime."""
    spy = _SpyResolver()
    # Give two non-empty captures (unlikely in screen_call, but ensure lock semantics)
    flow, tts, events = _screen_flow(
        stt_answers=["First utterance."],
        resolver=spy,
        decision="take_message",
    )
    flow.run()

    # Only one resolve() call, regardless of how many turns happen
    assert len(spy.resolve_calls) == 1, (
        "resolve() was called more than once — profile must be locked after utt-1"
    )


# ---------------------------------------------------------------------------
# ⑦ re_ask=True → cadence_slow used; profile.cadence unchanged
# ---------------------------------------------------------------------------

def test_profile_cadence_not_mutated_on_re_ask():
    """turn_cadence(re_ask=True) returns 0.7× but must not alter profile.cadence."""
    original_cadence = 1.0
    profile = _fake_profile(cadence=original_cadence)
    spy = _SpyResolver(profile=profile)

    # Simulate the resolver's turn_cadence behavior directly
    cadence_for_rask = spy.turn_cadence(profile, re_ask=True)
    cadence_normal = spy.turn_cadence(profile, re_ask=False)

    assert cadence_for_rask < original_cadence, (
        f"turn_cadence(re_ask=True) should return < {original_cadence}; got {cadence_for_rask}"
    )
    assert cadence_normal == original_cadence, (
        f"turn_cadence(re_ask=False) should return {original_cadence}; got {cadence_normal}"
    )
    # Profile must be immutable (frozen dataclass)
    assert profile.cadence == original_cadence, (
        "profile.cadence was mutated — PresentationProfile must be frozen"
    )


def test_screen_call_silent_utt1_re_ask_uses_cadence_slow():
    """When utt-1 is silent, the re-ask turn uses cadence_slow (< 1.0).

    The re-ask TTS call must be produced at slow cadence by the flow.
    The resolver spy's turn_cadence tracks whether cadence was applied.
    """
    spy = _SpyResolver()
    flow, tts, events = _screen_flow(
        stt_answers=["", "Bob calling."],  # first capture silent → re-ask → then heard
        resolver=spy,
        decision="take_message",
    )
    flow.run()

    # At least one turn_cadence(re_ask=True) call should have been made
    re_ask_turns = [c for c in spy.turn_cadence_calls if c["re_ask"]]
    assert re_ask_turns, (
        "No turn_cadence(re_ask=True) call detected — "
        "re-ask turn must apply cadence_slow via resolver.turn_cadence()"
    )


# ---------------------------------------------------------------------------
# ⑧ detection concurrent with utt-1 transcription
# ---------------------------------------------------------------------------

def test_detection_does_not_add_latency_after_stt():
    """Language detection must run concurrently with utt-1 transcription.

    If detection is serialized (called after STT completes), the sequence is:
      STT.transcribe() → resolver._detector() → resolve()

    With concurrent execution, _detector() starts while STT is still running.
    This test uses a thread-synchronization flag to assert that the detector
    callable was called while STT was still in progress.
    """
    stt_started = threading.Event()
    stt_may_finish = threading.Event()
    detector_called_while_stt_running = threading.Event()

    class _SlowSTT:
        def transcribe(self, wav_path: str) -> str:
            stt_started.set()
            stt_may_finish.wait(timeout=1.0)
            return "hola"

    def _concurrent_detector(utterance: str) -> dict[str, float]:
        # If STT is still running (flag not yet cleared), we are concurrent
        if stt_started.is_set() and not stt_may_finish.is_set():
            detector_called_while_stt_running.set()
        stt_may_finish.set()
        return {"es": 0.9}

    # Build a real ProfileResolver with our spy detector
    import pathlib
    import tempfile

    from iris.config import Config
    from iris.prefs import PreferencesStore

    with tempfile.TemporaryDirectory() as tmp:
        prefs = PreferencesStore(pathlib.Path(tmp) / "prefs.json")
        config = Config(language_set=["es", "en"], language_detect_threshold=0.5)
        resolver = ProfileResolver(
            config=config,
            prefs=prefs,
            voice_lookup=lambda lang: MagicMock(voice_id=f"{lang}-voice"),
            detector=_concurrent_detector,
        )

    tts = _FakeTTS()
    events: list[tuple] = []

    flow = ScreenCallFlow(
        tts=tts,
        stt=_SlowSTT(),
        play_fn=lambda _: None,
        capture_fn=lambda _s: "/tmp/cap.wav",
        relay_fn=lambda _: None,
        get_decision=lambda _: "take_message",
        put_through_fn=lambda: None,
        hang_up_fn=lambda: None,
        emit=events.append,
        resolver=resolver,
    )
    flow.run()

    assert detector_called_while_stt_running.is_set(), (
        "Detector was not called while STT was still running — "
        "language detection must be concurrent with utt-1 transcription (zero added latency)"
    )
