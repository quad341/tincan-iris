"""Screen call flow and screen-to-take_message pivot — ti-pwms / ti-eki3.

ScreenCallFlow
    Handles inbound calls with handling_rule='screen' (and unknown callers).
    Runs on a blocking thread and communicates with the console via emit().

    Flow:
      1. Play disclosure WAV (pre-rendered by disclosure.py)
      2. "Can I ask who's calling and what this is about?"  →  capture (10 s)
      3. Silence: re-ask once (5 s window); if still silent → farewell + hang up
      4. Relay caller intro (≤20 words) to the operator via relay_fn
      5. Wait relay_timeout_s for operator decision via get_decision():
           "put_through"  → connect call, emit ("screen_put_through", caller_name)
           "take_message" → emit ("screen_take_message", caller_name, caller_number)
           "decline"      → speak goodbye to caller, hang up
           ""  (timeout)  → auto-pivot: emit ("screen_take_message", caller_name, ...)

    Two separate audio paths:
      play_fn / capture_fn  — call audio (caller hears/speaks)
      relay_fn              — operator's local speaker/headset

ScreenPivotFlow
    Abbreviated take-message used when ScreenCallFlow pivots to message-taking.
    The caller already heard the disclosure; their name is already known.

    Pivot script (ti-eki3):
      "I'll pass that along. Is there anything you'd like to add, or a good
       number to reach you?" → capture → confirm → goodbye → hang up
      → emit ("take_message_done", ...) same as TakeMessageFlow

The caller injects all dependencies so tests run without audio hardware.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from . import settings

logger = logging.getLogger(__name__)

# Caller-side capture windows (seconds) — v1.
_INTRO_WINDOW_S: float = settings.get_float("IRIS_SC_INTRO_S", 10.0)
_RETRY_WINDOW_S: float = settings.get_float("IRIS_SC_RETRY_S", 5.0)
_RELAY_TIMEOUT_S: float = settings.get_float("IRIS_SC_RELAY_TIMEOUT_S", 20.0)
_RELAY_MAX_WORDS: int = 20


class _TTS(Protocol):
    def synth(self, text: str) -> str: ...


class _STT(Protocol):
    def transcribe(self, wav_path: str) -> str: ...


def _truncate_words(text: str, max_words: int) -> str:
    """Return text truncated to at most max_words words."""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + "…"


class ScreenCallFlow:
    """Scripted screen-call dialogue — run on a thread via run().

    Parameters
    ----------
    tts             : TTS protocol — synth(text) → wav_path; output goes to caller
    stt             : STT protocol — transcribe(wav_path) → text; input from caller
    play_fn         : callable(wav_path) → None — plays audio into the call (caller hears)
    capture_fn      : callable(seconds) → wav_path — records caller audio for N seconds
    relay_fn        : callable(text) → None — speaks to the OPERATOR (local speaker)
    get_decision    : callable(timeout_s) → str — blocks for operator reply; returns
                      "put_through", "take_message", "decline", or "" on timeout
    put_through_fn  : callable() → None — connects the call to the operator directly
    hang_up_fn      : callable() → None — hangs up the call
    emit            : callable(event) → None — thread-safe event sink
    contact_name    : roster display name of the called party (may be "" for unknowns)
    caller_number   : E.164 caller number from roster or SIP (may be "")
    disclosure_wav  : path to pre-rendered disclosure WAV; None → inline TTS fallback
    relay_timeout_s : seconds to wait for operator decision before auto-pivoting
    """

    def __init__(
        self,
        *,
        tts: _TTS,
        stt: _STT,
        play_fn: Callable[[str], None],
        capture_fn: Callable[[float], str],
        relay_fn: Callable[[str], None],
        get_decision: Callable[[float], str],
        put_through_fn: Callable[[], None],
        hang_up_fn: Callable[[], None],
        emit: Callable[[tuple], None],
        contact_name: str = "",
        caller_number: str = "",
        disclosure_wav: str | Path | None = None,
        relay_timeout_s: float = _RELAY_TIMEOUT_S,
    ) -> None:
        self.tts = tts
        self.stt = stt
        self.play_fn = play_fn
        self.capture_fn = capture_fn
        self.relay_fn = relay_fn
        self.get_decision = get_decision
        self.put_through_fn = put_through_fn
        self.hang_up_fn = hang_up_fn
        self.emit = emit
        self.contact_name = contact_name.strip()
        self.caller_number = caller_number.strip()
        self.disclosure_wav = str(disclosure_wav) if disclosure_wav else None
        self.relay_timeout_s = relay_timeout_s

    # --- helpers (caller-side) ---

    def _speak(self, text: str) -> None:
        logger.debug("screen_call: speak→caller: %s", text[:80])
        wav = self.tts.synth(text)
        self.play_fn(wav)

    def _listen(self, window_s: float) -> str:
        wav = self.capture_fn(window_s)
        text = self.stt.transcribe(wav).strip()
        logger.debug("screen_call: heard: %s", text[:80] if text else "(silence)")
        return text

    def _play_disclosure(self) -> None:
        if self.disclosure_wav and Path(self.disclosure_wav).exists():
            self.play_fn(self.disclosure_wav)
        else:
            self._speak(
                "Hi, I'm Iris, an AI assistant. "
                "I'll let the person you're calling know you're on the line."
            )

    # --- main flow ---

    def run(self) -> None:
        """Execute the screen-call dialogue.  Blocking — call from a thread."""
        try:
            self._run()
        except Exception:
            logger.exception("screen_call flow crashed")
            try:
                self.hang_up_fn()
            except Exception:
                logger.exception("screen_call hang_up also failed")

    def _run(self) -> None:
        name = self.contact_name or "the person you're calling"

        # 1. Disclosure (caller hears)
        self._play_disclosure()

        # 2. Ask who's calling
        self._speak("Can I ask who's calling and what this is about?")
        intro = self._listen(_INTRO_WINDOW_S)

        # 3. Silence → re-ask once, then hang up
        if not intro:
            self._speak("Sorry — I didn't catch that. Who's calling, please?")
            intro = self._listen(_RETRY_WINDOW_S)

        if not intro:
            farewell = (
                f"I'll let {name} know someone called. Goodbye."
                if self.contact_name
                else "I'll let them know someone called. Goodbye."
            )
            self._speak(farewell)
            self.emit(("screen_declined", "", self.caller_number))
            self.hang_up_fn()
            return

        # 4. Relay intro to operator (≤20 words) and ask for a decision
        relay_text = _truncate_words(intro, _RELAY_MAX_WORDS)
        relay_prompt = (
            f"{relay_text}. "
            "Want me to take a message, or should I put them through?"
        )
        logger.debug("screen_call: relay→operator: %s", relay_prompt[:120])
        self.relay_fn(relay_prompt)

        # 5. Wait for operator decision
        decision = self.get_decision(self.relay_timeout_s)
        logger.debug("screen_call: operator decision: %r", decision)

        if decision == "put_through":
            self.put_through_fn()
            self.emit(("screen_put_through", intro, self.caller_number))
            return

        if decision == "decline":
            self._speak("Thanks for calling — I'll pass that along. Goodbye.")
            self.emit(("screen_declined", intro, self.caller_number))
            self.hang_up_fn()
            return

        # "take_message" or timeout ("") → pivot to take_message
        self.emit(("screen_take_message", intro, self.caller_number))


# ---------------------------------------------------------------------------
# ScreenPivotFlow — abbreviated take-message after a screen pivot (ti-eki3)
# ---------------------------------------------------------------------------

# Pivot capture window — same as the take_message addition window by default.
_PIVOT_WINDOW_S: float = settings.get_float("IRIS_SC_PIVOT_S", 30.0)


class ScreenPivotFlow:
    """Abbreviated take-message dialogue used after a ScreenCallFlow pivot.

    The caller already heard the disclosure WAV during screening, and their
    name is known from the intro they gave.  This flow skips both the
    disclosure and the name-ask steps.

    Pivot script:
      1. "I'll pass that along. Is there anything you'd like to add, or a
         good number to reach you?"  →  capture (_PIVOT_WINDOW_S)
      2. "Got it — I'll make sure [contact] gets this.  Thanks for calling.
         Goodbye."
      3. Hang up → emit ("take_message_done", caller_name, addition, ...)

    Emits the same ("take_message_done", ...) tuple as TakeMessageFlow so
    the console can handle both with the same handler.

    Parameters
    ----------
    tts            : TTS protocol — synth(text) → wav_path
    stt            : STT protocol — transcribe(wav_path) → text
    play_fn        : callable(wav_path) → None — plays into the call
    capture_fn     : callable(seconds) → wav_path — records caller audio
    hang_up_fn     : callable() → None
    emit           : callable(event: tuple) → None — thread-safe event sink
    caller_name    : name the caller gave during screening (may be "")
    caller_number  : E.164 number (may be "")
    contact_name   : roster display name of the called party (may be "")
    """

    def __init__(
        self,
        *,
        tts: _TTS,
        stt: _STT,
        play_fn: Callable[[str], None],
        capture_fn: Callable[[float], str],
        hang_up_fn: Callable[[], None],
        emit: Callable[[tuple], None],
        caller_name: str = "",
        caller_number: str = "",
        contact_name: str = "",
    ) -> None:
        self.tts = tts
        self.stt = stt
        self.play_fn = play_fn
        self.capture_fn = capture_fn
        self.hang_up_fn = hang_up_fn
        self.emit = emit
        self.caller_name = caller_name.strip() or "the caller"
        self.caller_number = caller_number.strip()
        self.contact_name = contact_name.strip()

    def _speak(self, text: str) -> None:
        logger.debug("screen_pivot: speak: %s", text[:80])
        wav = self.tts.synth(text)
        self.play_fn(wav)

    def _listen(self, window_s: float) -> str:
        wav = self.capture_fn(window_s)
        text = self.stt.transcribe(wav).strip()
        logger.debug("screen_pivot: heard: %s", text[:80] if text else "(silence)")
        return text

    def run(self) -> None:
        """Execute the pivot dialogue.  Blocking — call from a thread."""
        try:
            self._run()
        except Exception:
            logger.exception("screen_pivot flow crashed")
            try:
                self.hang_up_fn()
            except Exception:
                logger.exception("screen_pivot hang_up also failed")

    def _run(self) -> None:
        name = self.contact_name or "the person you're calling"

        # Pivot greeting (disclosure already played; caller name already known)
        self._speak(
            "I'll pass that along. Is there anything you'd like to add, "
            "or a good number to reach you?"
        )
        addition = self._listen(_PIVOT_WINDOW_S)

        # Sign off
        close_text = f"Got it — I'll make sure {name} gets this. Thanks for calling. Goodbye."
        self._speak(close_text)

        self.emit(
            ("take_message_done", self.caller_name, addition,
             self.contact_name, self.caller_number)
        )
        self.hang_up_fn()
