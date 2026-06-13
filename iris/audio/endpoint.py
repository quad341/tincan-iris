"""Audio endpoints — where Iris's ears and mouth attach.

Each call platform is an ``AudioEndpoint``: tincan's SCO nodes, a Discord/Zoom
virtual device, or the local mic/speaker. Same brain, different binding. See the
memory note "iris-audio-endpoint-platform-agnostic".
"""
from __future__ import annotations

import shutil
import subprocess
from typing import Protocol


class AudioEndpoint(Protocol):
    name: str

    def playback(self, wav_path: str) -> None:
        """Play a WAV out to this endpoint (speaker / call uplink)."""
        ...

    def capture(self, seconds: float) -> str:
        """Record from this endpoint; return a WAV path. (mic side, next PR)"""
        ...


class LocalAudio:
    """The local default mic/speaker via PipeWire (``pw-cat``), ALSA fallback."""

    name = "local"

    def __init__(self, player: list[str] | None = None) -> None:
        self._player = player  # explicit override; else auto-detect

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

    def capture(self, seconds: float) -> str:
        raise NotImplementedError("mic capture lands with the STT (whisper.cpp) PR")
