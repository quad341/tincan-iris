"""Audio endpoints — where Iris's ears and mouth attach.

Each call platform is an ``AudioEndpoint``: tincan's SCO nodes, a Discord/Zoom
virtual device, or the local mic/speaker. Same brain, different binding. See the
memory note "iris-audio-endpoint-platform-agnostic".

``LocalAudio`` is the standalone binding (your own mic + speakers) for testing
Iris in isolation before the call routing exists. Capture is 16 kHz mono — what
whisper wants. ``start_capture()`` is the push-to-talk handle (start on key-down,
``.stop()`` on key-up); ``capture(seconds)`` is the fixed-duration convenience
built on it.
"""
from __future__ import annotations

import shutil
import signal
import subprocess
import tempfile
import time
from typing import Protocol


class AudioEndpoint(Protocol):
    name: str

    def playback(self, wav_path: str) -> None:
        """Play a WAV out to this endpoint (speaker / call uplink)."""
        ...

    def capture(self, seconds: float) -> str:
        """Record ``seconds`` from this endpoint; return a WAV path."""
        ...


class _Recording:
    """A running mic capture. Call ``.stop()`` to finalize and get the WAV."""

    def __init__(self, proc: subprocess.Popen, wav_path: str) -> None:
        self._proc = proc
        self.wav_path = wav_path

    def stop(self) -> str:
        # SIGINT lets the recorder flush a valid WAV header (unlike SIGKILL).
        self._proc.send_signal(signal.SIGINT)
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait()
        return self.wav_path


class LocalAudio:
    """Local mic/speaker via PipeWire (``pw-cat``/``pw-record``), ALSA/Pulse fallback."""

    name = "local"

    def __init__(
        self,
        player: list[str] | None = None,
        recorder: list[str] | None = None,
        *,
        rate: int = 16000,
        channels: int = 1,
    ) -> None:
        self._player = player  # explicit overrides; else auto-detect
        self._recorder = recorder
        self.rate = rate
        self.channels = channels

    # --- playback (mouth) ---
    def _player_cmd(self, wav: str) -> list[str]:
        if self._player:
            return [*self._player, wav]
        if shutil.which("pw-cat"):
            return ["pw-cat", "-p", wav]
        if shutil.which("aplay"):
            return ["aplay", "-q", wav]
        if shutil.which("paplay"):
            return ["paplay", wav]
        raise RuntimeError("no audio player found (pw-cat / aplay / paplay)")

    def playback(self, wav_path: str) -> None:
        subprocess.run(self._player_cmd(wav_path), check=False)

    # --- capture (ears) ---
    def _recorder_cmd(self, wav: str) -> list[str]:
        if self._recorder:
            return [*self._recorder, wav]
        if shutil.which("pw-record"):
            return ["pw-record", "--rate", str(self.rate),
                    "--channels", str(self.channels), "--format", "s16", wav]
        if shutil.which("arecord"):
            return ["arecord", "-q", "-f", "S16_LE", "-r", str(self.rate),
                    "-c", str(self.channels), wav]
        if shutil.which("parecord"):
            return ["parecord", "--file-format=wav", f"--rate={self.rate}",
                    f"--channels={self.channels}", "--format=s16le", wav]
        raise RuntimeError("no audio recorder found (pw-record / arecord / parecord)")

    def start_capture(self) -> _Recording:
        """Begin recording now; the returned handle's ``.stop()`` ends it.
        Push-to-talk: start on key-down, ``.stop()`` on key-up."""
        wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
        proc = subprocess.Popen(
            self._recorder_cmd(wav),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return _Recording(proc, wav)

    def capture(self, seconds: float) -> str:
        rec = self.start_capture()
        time.sleep(seconds)
        return rec.stop()
