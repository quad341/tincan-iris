"""Take-message call flow — ti-r4mu.

Runs a scripted dialogue for contacts with handling_rule='take_message'.
The flow runs on a thread (blocking) and communicates with the console via emit().

Flow:
  1. Play disclosure WAV (pre-rendered by disclosure.py)
  2. "May I ask who's calling?"  →  capture caller name (8 s)
  3. "Can I take a message?"     →  capture message (30 s)
  4. Confirm receipt + "Anything else?"  →  capture addition (10 s)
  5. "Thanks for calling. Goodbye."
  6. Hang up  →  emit ("take_message_done", caller_name, full_message)

Silence / VAD: v1 uses fixed-length capture windows.  Natural-pause detection
(StreamingTranscriber) is a future upgrade tracked in the bead notes.

The caller injects TTS, STT, capture, play, and hang_up so tests can stub them
without touching the filesystem or audio hardware.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)

# Fixed capture windows (seconds) — v1.
_NAME_WINDOW_S: float = float(os.environ.get("IRIS_TM_NAME_S", "8"))
_MSG_WINDOW_S: float = float(os.environ.get("IRIS_TM_MSG_S", "30"))
_ADD_WINDOW_S: float = float(os.environ.get("IRIS_TM_ADD_S", "10"))


class _TTS(Protocol):
    def synth(self, text: str) -> str: ...


class _STT(Protocol):
    def transcribe(self, wav_path: str) -> str: ...


class TakeMessageFlow:
    """Scripted take-message dialogue — run on a thread via run().

    Parameters
    ----------
    tts          : TTS protocol object (synth → wav_path)
    stt          : STT protocol object (transcribe(wav_path) → text)
    play_fn      : callable(wav_path: str) → None — blocks until playback done
    capture_fn   : callable(seconds: float) → wav_path — blocks for N seconds
    hang_up_fn   : callable() → None — hangs up the call
    emit         : callable(event: tuple) → None — thread-safe event sink
    contact_name : display name of the contact being called (for the "I'll tell X" phrase)
    disclosure_wav: path to pre-rendered disclosure WAV; if None the disclosure is
                    synthesised inline (slower — only a fallback)
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
        contact_name: str = "",
        caller_number: str = "",
        disclosure_wav: str | Path | None = None,
    ) -> None:
        self.tts = tts
        self.stt = stt
        self.play_fn = play_fn
        self.capture_fn = capture_fn
        self.hang_up_fn = hang_up_fn
        self.emit = emit
        self.contact_name = contact_name.strip()
        self.caller_number = caller_number.strip()
        self.disclosure_wav = str(disclosure_wav) if disclosure_wav else None

    # --- internal helpers ---

    def _speak(self, text: str) -> None:
        logger.debug("take_message: speak: %s", text[:80])
        wav = self.tts.synth(text)
        self.play_fn(wav)

    def _listen(self, window_s: float) -> str:
        wav = self.capture_fn(window_s)
        text = self.stt.transcribe(wav).strip()
        logger.debug("take_message: heard: %s", text[:80] if text else "(silence)")
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
        """Execute the scripted take-message dialogue.  Blocking — call from a thread."""
        try:
            self._run()
        except Exception:
            logger.exception("take_message flow crashed")
            try:
                self.hang_up_fn()
            except Exception:
                logger.exception("take_message hang_up also failed")

    def _run(self) -> None:
        name = self.contact_name or "the person you're calling"

        # 1. Disclosure
        self._play_disclosure()

        # 2. Ask who's calling
        self._speak("May I ask who's calling?")
        caller_name = self._listen(_NAME_WINDOW_S)
        if not caller_name:
            caller_name = "the caller"

        # 3. Ask for a message
        self._speak("Can I take a message?")
        message = self._listen(_MSG_WINDOW_S)

        if not message:
            self._speak("I'm sorry — I didn't quite catch that. Please leave your message after a moment.")
            message = self._listen(_MSG_WINDOW_S)

        # 4. Confirm + "Anything else?"
        confirmation = f"Got it — I'll make sure {name} gets this message. Anything else?"
        self._speak(confirmation)
        addition = self._listen(_ADD_WINDOW_S)

        # Build the full message transcript
        full_message = message
        if addition:
            full_message = f"{message} {addition}".strip()

        # 5. Sign off + hang up
        self._speak("Thanks for calling. Goodbye.")

        self.emit(
            ("take_message_done", caller_name, full_message, self.contact_name,
             self.caller_number)
        )
        self.hang_up_fn()
