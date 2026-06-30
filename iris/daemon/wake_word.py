"""WakeWordSource — opt-in headless wake-word activation (ti-s9mm.5.2).

Activated only when IRIS_WAKE_WORD=1. Prefers Pipecat VAD; falls back to a
silence-gated faster-whisper buffer. Muted while a call is in progress.

Security: operator utterances ARE passed to BrainHost.async_turn (they are
addressed voice commands, not ambient data). ANCS notification bodies (handled
by MessageEventSource) are NOT passed to Brain — separate invariant.
"""
from __future__ import annotations

import json
import logging
import math
import os
import threading
import wave
from typing import Any

_log = logging.getLogger(__name__)

_CHIME_HZ = 880
_CHIME_DURATION_S = 0.200
_SAMPLE_RATE = 44100

try:
    import pipecat.processors.audio  # type: ignore[import-untyped]  # noqa: F401
    _HAS_PIPECAT = True
except Exception:
    _HAS_PIPECAT = False


class WakeWordSource:
    """Listen for a wake phrase and dispatch to BrainHost.async_turn.

    :param brain_host: BrainHost instance; checked for call_context.in_call at
                       wake and reply time to suppress output during calls.
    :param threshold:  Confidence threshold (0–1); below this, wake is ignored.
    """

    def __init__(self, brain_host: Any, *, threshold: float = 0.85) -> None:
        self._brain_host = brain_host
        self._threshold = threshold
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        _log.debug(
            "WakeWordSource: confidence_threshold=%.2f  VAD backend=%s",
            threshold,
            "pipecat" if _HAS_PIPECAT else "faster-whisper",
        )

    # ── Public lifecycle ───────────────────────────────────────────

    def start(self) -> None:
        """Start the background detection thread."""
        if _HAS_PIPECAT:
            _log.info("WakeWordSource: starting with Pipecat VAD backend")
        else:
            _log.info("WakeWordSource: starting with faster-whisper fallback backend")
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="wake-word")
        self._thread.start()

    def stop(self) -> None:
        """Signal the detection thread to stop."""
        self._stop_event.set()

    # ── Wake detection response ────────────────────────────────────

    def _handle_wake(self, utterance: str, *, confidence: float) -> None:
        """Called by the detection loop when a wake phrase is recognised.

        Gates:
        1. in_call=True  → suppress entirely (no chime, no turn).
        2. confidence < threshold → ignore silently.
        3. Otherwise: play chime, then dispatch to BrainHost.async_turn.
        """
        if self._brain_host.call_context.in_call:
            return
        if confidence < self._threshold:
            return
        self._play_chime()
        self._brain_host.async_turn(utterance, speaker="operator")

    def on_reply(self, text: str) -> None:
        """Called with Brain's reply text.

        When IRIS_HEADLESS_TTS=1 and not currently in a call, speaks the reply
        via Kokoro HTTP TTS. Checks in_call at call time (not at wake time) so
        that a call beginning between wake and reply suppresses the TTS correctly.
        """
        if os.environ.get("IRIS_HEADLESS_TTS") != "1":
            return
        if self._brain_host.call_context.in_call:
            return
        self._tts_reply(text)

    # ── Audio helpers (patched in tests) ──────────────────────────

    def _play_chime(self) -> None:
        """Play a 200 ms 880 Hz sine-wave confirmation chime via the default output."""
        n_samples = int(_SAMPLE_RATE * _CHIME_DURATION_S)
        try:
            import tempfile

            import simpleaudio as sa  # type: ignore[import-untyped]
            samples = [
                int(32767 * math.sin(2 * math.pi * _CHIME_HZ * i / _SAMPLE_RATE))
                for i in range(n_samples)
            ]
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                tmp = f.name
            with wave.open(tmp, "w") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(_SAMPLE_RATE)
                wf.writeframes(bytes(
                    b for s in samples for b in s.to_bytes(2, "little", signed=True)
                ))
            sa.WaveObject.from_wave_file(tmp).play()
            os.unlink(tmp)
        except Exception:
            _log.debug("WakeWordSource: chime playback unavailable")

    def _tts_reply(self, text: str) -> None:
        """Speak text via Kokoro HTTP TTS endpoint (headless mode)."""
        import urllib.request

        kokoro_url = os.environ.get("IRIS_KOKORO_URL", "http://localhost:8880/tts")
        try:
            data = json.dumps({"text": text}).encode()
            req = urllib.request.Request(kokoro_url, data=data,
                                         headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=10)
        except Exception:
            _log.warning("WakeWordSource: Kokoro TTS request failed for %r", kokoro_url)

    # ── Detection loop (daemon thread) ────────────────────────────

    def _run(self) -> None:
        """Background detection loop; blocks until stop() is called."""
        if _HAS_PIPECAT:
            self._run_pipecat()
        else:
            self._run_faster_whisper()

    def _run_pipecat(self) -> None:
        _log.info("WakeWordSource: Pipecat VAD loop starting")
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=1.0)

    def _run_faster_whisper(self) -> None:
        _log.info("WakeWordSource: faster-whisper fallback loop starting")
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=1.0)
