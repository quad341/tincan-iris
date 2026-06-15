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

import os
import shutil
import signal
import subprocess
import tempfile
import time
from typing import Protocol


class AudioEndpoint(Protocol):
    name: str
    far_source: str | None  # source for the far party, if separate (None = local)
    far_backend: str        # "pulse" (parecord) or "pw" (pw-record) for far_source

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


class _Playback:
    """A running playback. ``.stop()`` cuts it off (barge-in); ``.wait()`` blocks."""

    def __init__(self, proc: subprocess.Popen) -> None:
        self._proc = proc

    def wait(self) -> None:
        self._proc.wait()

    def stop(self) -> None:
        self._proc.send_signal(signal.SIGINT)
        try:
            self._proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait()


class _MultiPlayback:
    """Playback fanned out to several targets (e.g. call uplink + local monitor).

    ``wait()`` blocks on the first proc (the primary — the call), so timing tracks
    what the far party hears; ``stop()`` cuts them all at once (barge-in)."""

    def __init__(self, procs: list[subprocess.Popen]) -> None:
        self._procs = procs

    def wait(self) -> None:
        if self._procs:
            self._procs[0].wait()

    def stop(self) -> None:
        for p in self._procs:
            p.send_signal(signal.SIGINT)
        for p in self._procs:
            try:
                p.wait(timeout=2)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()


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
        # A separate source for the far party (call downlink / app monitor).
        # None for plain local audio — the far party is just on your speakers.
        self.far_source: str | None = None
        # How to capture far_source: "pulse" (parecord --device) or "pw"
        # (pw-record --target, for native PipeWire nodes like SCO).
        self.far_backend: str = "pulse"

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

    def start_playback(self, wav_path: str) -> _Playback:
        """Begin playing now; the handle's ``.stop()`` cuts it off (barge-in)."""
        proc = subprocess.Popen(
            self._player_cmd(wav_path),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return _Playback(proc)

    def playback(self, wav_path: str) -> None:
        self.start_playback(wav_path).wait()

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


class VirtualDeviceAudio(LocalAudio):
    """Bind Iris to virtual PipeWire nodes so she can join an app call (Discord,
    Zoom, …) — no Bluetooth. Her voice plays into a sink the app reads as its
    microphone; she captures from a chosen source (the operator's mic for commands
    now, the far-end later). Same Conductor/console as LocalAudio — only the nodes
    differ. Requires PipeWire (pw-cat/pw-record --target); set the nodes up with
    scripts/virtual_audio.sh.
    """

    name = "virtual-device"

    def __init__(
        self,
        playback_target: str,
        capture_target: str | None = None,
        *,
        rate: int = 16000,
        channels: int = 1,
    ) -> None:
        super().__init__(rate=rate, channels=channels)
        self.playback_target = playback_target   # sink the call app reads as its mic
        self.capture_target = capture_target     # source Iris hears (None = default mic)

    # PulseAudio tools resolve named sinks/sources reliably; pw-cat/pw-record
    # --target proved flaky with a null-sink's pulse names (and quieter).
    def _player_cmd(self, wav: str) -> list[str]:
        return ["paplay", f"--device={self.playback_target}", wav]

    def _recorder_cmd(self, wav: str) -> list[str]:
        # Default mic: reuse pw-record (LocalAudio) — it finalizes the WAV cleanly
        # on SIGINT. parecord drops its tail buffer on SIGINT (truncates ~2s),
        # which cut off paused speech. A named source still uses parecord --device.
        if self.capture_target is None:
            return super()._recorder_cmd(wav)
        return [
            "parecord", f"--rate={self.rate}", f"--channels={self.channels}",
            "--format=s16le", "--file-format=wav",
            f"--device={self.capture_target}", wav,
        ]


def _pw_link_nodes(direction: str) -> list[str]:
    """Distinct node names from ``pw-link`` ports. ``direction='out'`` lists output
    ports (sources), ``'in'`` lists input ports (sinks); [] on failure."""
    flag = "-o" if direction == "out" else "-i"
    try:
        out = subprocess.run(
            ["pw-link", flag], capture_output=True, text=True, timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []
    names: list[str] = []
    for line in out.stdout.splitlines():
        node = line.strip().split(":", 1)[0].strip()  # "node:port" -> node
        if node and node not in names:
            names.append(node)
    return names


def _pick_bluez(names: list[str], prefix: str) -> str | None:
    """First node whose name starts with ``prefix`` (``bluez_output``/``bluez_input``)."""
    for n in names:
        if n.startswith(prefix):
            return n
    return None


def discover_sco_nodes() -> tuple[str | None, str | None]:
    """Find the live HFP/SCO ``(sink, source)`` for an active call via ``pw-link``.

    The SCO nodes are **native PipeWire nodes** — the uplink sink
    ``bluez_output.<mac>.N`` and the downlink source ``bluez_input.<mac>.N``. They
    do NOT appear in PulseAudio, so ``pactl``/``paplay``/``parecord`` can't see
    them; only ``pw-link``/``pw-cat`` do. They exist only while a call is up and
    embed the device MAC (PII), so they're discovered fresh each call, never
    persisted. A future ``TincanCallControl`` re-runs this on ``CallConnected``.
    """
    sink = _pick_bluez(_pw_link_nodes("in"), "bluez_output")    # uplink — Iris's mouth
    source = _pick_bluez(_pw_link_nodes("out"), "bluez_input")  # downlink — Iris's ear
    return sink, source


class TincanSCOAudio(VirtualDeviceAudio):
    """Ride a real phone call over tincan's HFP/SCO audio.

    Iris's voice plays into the SCO **sink** (``bluez_output.<mac>.N`` — the call
    uplink the far party hears); her far-ear is the SCO **source**
    (``bluez_input.<mac>.N`` — the downlink from the far party). Push-to-talk stays
    on the default mic, so the operator addresses Iris with their own voice (the
    supervised co-pilot model).

    Unlike Discord's null-sinks, the SCO nodes are **native PipeWire nodes invisible
    to PulseAudio**, so this endpoint uses ``pw-cat``/``pw-record --target`` rather
    than ``paplay``/``parecord`` (hence ``far_backend = "pw"``).

    This is **media only** — it knows nothing about ringing, answering, or call
    state. Signaling lives in tincan's ``im.tincan.Calls`` D-Bus interface
    (``IncomingCall`` / ``Answer`` / ``CallConnected`` / ``CallEnded``). The
    autonomous path (later): a ``TincanCallControl`` client answers an incoming
    call by policy, then on ``CallConnected`` discovers the now-live SCO nodes and
    binds this endpoint; on ``CallEnded`` it drops it. Keeping media and signaling
    separate is what lets that land without touching this class.
    """

    name = "tincan-sco"

    def __init__(
        self,
        sink: str,
        source: str | None = None,
        *,
        monitor: bool = True,
        rate: int = 16000,
        channels: int = 1,
    ) -> None:
        # capture_target=None -> push-to-talk uses the default mic (the operator).
        super().__init__(sink, capture_target=None, rate=rate, channels=channels)
        self.far_source = source  # the SCO downlink — the far party, for _far_stream
        self.far_backend = "pw"   # SCO source is a native PipeWire node -> pw-record
        # Also play Iris to the local default sink so the OPERATOR hears her too —
        # the supervised model means hearing both sides (mom on the downlink, Iris's
        # replies on the monitor). Use headphones to keep the monitor out of the mic.
        self.monitor = monitor

    def _player_cmd(self, wav: str) -> list[str]:
        # SCO nodes are native PipeWire nodes (invisible to PulseAudio/paplay):
        # play Iris's voice into the uplink with pw-cat --target.
        return ["pw-cat", "-p", "--target", self.playback_target, wav]

    def _monitor_cmd(self, wav: str) -> list[str]:
        # Local default sink (operator's speakers) — no --target.
        return ["pw-cat", "-p", wav]

    def start_playback(self, wav_path: str) -> _MultiPlayback:
        """Play Iris to the call uplink (mom hears) and, if monitoring, the local
        speakers (operator hears). ``.wait()`` tracks the uplink; ``.stop()`` cuts
        both (barge-in)."""
        procs = [subprocess.Popen(
            self._player_cmd(wav_path),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )]
        if self.monitor:
            procs.append(subprocess.Popen(
                self._monitor_cmd(wav_path),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            ))
        return _MultiPlayback(procs)


def default_endpoint() -> AudioEndpoint:
    """LocalAudio by default.

    - ``IRIS_AUDIO=tincan-sco`` rides tincan's live HFP/SCO call audio: the bluez
      nodes are discovered (``IRIS_SCO_SINK`` / ``IRIS_SCO_SOURCE`` override) — a
      call must be active for them to exist.
    - else ``IRIS_PLAYBACK_TARGET`` selects VirtualDeviceAudio (e.g. the
      ``iris_mic`` null-sink routing Iris into Discord/Zoom — see
      scripts/virtual_audio.sh).
    """
    if os.environ.get("IRIS_AUDIO", "").lower() in ("tincan-sco", "sco"):
        sink = os.environ.get("IRIS_SCO_SINK")
        source = os.environ.get("IRIS_SCO_SOURCE")
        if not sink or not source:
            d_sink, d_source = discover_sco_nodes()
            sink = sink or d_sink
            source = source or d_source
        if not sink:
            raise RuntimeError(
                "tincan-sco: no HFP/SCO sink found — is a call active on the dongle? "
                "Set IRIS_SCO_SINK / IRIS_SCO_SOURCE to override."
            )
        return TincanSCOAudio(sink, source)
    target = os.environ.get("IRIS_PLAYBACK_TARGET")
    if target:
        return VirtualDeviceAudio(target, os.environ.get("IRIS_CAPTURE_TARGET"))
    return LocalAudio()


if __name__ == "__main__":  # python -m iris.audio.endpoint — probe live SCO nodes
    _sink, _source = discover_sco_nodes()
    _miss = "— none found (is a call active on the dongle?)"
    print(f"SCO sink   (uplink → far party hears Iris): {_sink or _miss}")
    print(f"SCO source (downlink → Iris hears far party): {_source or _miss}")
    if _sink:
        print("\nRun the console on this call:\n  IRIS_AUDIO=tincan-sco python -m iris.console")
