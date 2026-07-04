"""Continuous streaming transcription — a recorder piped into the venv VAD worker.

Spawns a continuous recorder feeding ``_whisper_stream.py`` (in the network-
isolated whisper venv); reads the worker's JSON transcripts on a thread and hands
each finished utterance to ``on_text``. This is the always-on input for the
console / call mode — you just talk, and each utterance arrives as text (no
push-to-talk). Pair with ``iris.addressing`` to act only when named.
"""
from __future__ import annotations

import itertools
import json
import logging
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

from .. import settings
from .assets import resolve_asset

_REPO_ROOT = Path(__file__).resolve().parents[2]
_STREAM_SCRIPT = Path(__file__).resolve().parent / "_whisper_stream.py"
_DEFAULT_SIZE = settings.get("IRIS_WHISPER_MODEL_SIZE", "small.en")

_log = logging.getLogger(__name__)
_stream_seq = itertools.count(1)


def resolve_node_serial(node_name: str) -> str | None:
    """Return the object.serial for *node_name* via pw-dump, or None.

    Name-based --target is unreliable for binding (WirePlumber falls back to
    the default source when it doesn't resolve the name — verified live);
    serial-based targeting links deterministically.
    """
    try:
        r = subprocess.run(["pw-dump"], capture_output=True, text=True, timeout=5)
        if r.returncode != 0:
            return None
        for obj in json.loads(r.stdout):
            props = (obj.get("info") or {}).get("props") or {}
            if props.get("node.name") == node_name:
                serial = props.get("object.serial")
                return str(serial) if serial is not None else None
    except Exception:
        return None
    return None


def _run_pw_link_l() -> str:
    """Return ``pw-link -l`` output ('' on failure). Seam for tests."""
    try:
        r = subprocess.run(["pw-link", "-l"], capture_output=True, text=True, timeout=5)
        return r.stdout if r.returncode == 0 else ""
    except Exception:
        return ""


class StreamingTranscriber:
    """Continuous mic -> VAD -> faster-whisper, calling ``on_text(text, label)`` per utterance.

    ``label`` tags the logical source — e.g. ``"operator"`` for the local mic and
    ``"far"`` for the call downlink — so the trust model can distinguish who spoke.
    """

    def __init__(
        self,
        on_text: Callable[[str, str], None],
        *,
        source: str | None = None,    # audio device/node to capture (None = default mic)
        backend: str = "pulse",       # "pulse" (parecord) or "pw" (pw-record, for SCO nodes)
        label: str = "",              # logical source tag emitted with each transcript
        python: str | None = None,
        model: str | None = None,
        isolate: bool = True,
        min_silence_ms: int = 800,
        on_stream_end: Callable[[str], None] | None = None,
    ) -> None:
        self.on_text = on_text
        # Called (with label) from the reader thread when the pipeline dies
        # without stop() being requested — e.g. the recorder exiting because
        # its source vanished. Silence here is indistinguishable from a
        # broken channel, so the death must be observable (ti-wunrs findings).
        self.on_stream_end = on_stream_end
        # Unique PipeWire node name so THIS stream is identifiable in the
        # link graph — the basis for verify_target_bound().
        self.stream_node_name = f"iris-cap-{label or 'chan'}-{next(_stream_seq)}"
        self.source = source
        self.backend = backend
        self.label = label
        self.python = python or resolve_asset(
            "IRIS_WHISPER_PYTHON", ".venv-whisper/bin/python", _REPO_ROOT
        )
        self.model = model or resolve_asset(
            "IRIS_WHISPER_DIR", f"models/whisper/{_DEFAULT_SIZE}", _REPO_ROOT
        )
        self.isolate = isolate
        self.min_silence_ms = min_silence_ms
        self._rec: subprocess.Popen | None = None
        self._worker: subprocess.Popen | None = None
        self._reader: threading.Thread | None = None
        self._ready = threading.Event()

    def available(self) -> bool:
        return all(Path(p).exists() for p in (self.python, self.model, _STREAM_SCRIPT))

    def _recorder_cmd(self) -> list[str]:
        if self.backend == "pw":
            # Native PipeWire nodes (SCO) aren't pulse devices: pw-record --target,
            # --raw for headerless s16le PCM piped to the worker.
            #
            # BINDING IS NOT TRUSTED: pw-record with a --target that is missing
            # (or that disappears mid-stream) silently falls back to the DEFAULT
            # source — the operator's mic — and node.dont-reconnect is ignored
            # by the session manager here (verified live 2026-07-04: a far
            # channel became a second mic capture when the call left the SCO
            # route, so far-party attribution was fiction — a hole under the
            # ADR-0002 channel-identity trust model, not just a transcript bug).
            # We set a unique node.name and the caller polices the actual link
            # via verify_target_bound(); dont-reconnect stays for session
            # managers that do honor it.
            props = f"{{ node.name = \"{self.stream_node_name}\" node.dont-reconnect = true }}"
            cmd = ["pw-record", "--raw", "--rate", "16000",
                   "--channels", "1", "--format", "s16", "-P", props]
            if self.source:
                # Target by object.serial when resolvable — deterministic
                # binding; the name stays authoritative for verification.
                target = resolve_node_serial(self.source) or self.source
                cmd += ["--target", target]
            cmd.append("-")
            return cmd
        cmd = ["parecord", "--raw", "--rate=16000", "--channels=1", "--format=s16le"]
        if self.source:
            cmd.append(f"--device={self.source}")
        return cmd

    def _worker_cmd(self) -> list[str]:
        cmd = [
            self.python, str(_STREAM_SCRIPT),
            "--model", self.model, "--min-silence-ms", str(self.min_silence_ms),
        ]
        if self.isolate:
            cmd = ["unshare", "-rn", *cmd]  # fresh net namespace -> no egress
        return cmd

    def verify_target_bound(self) -> tuple[bool, str]:
        """Check the live link graph: is THIS stream fed by its intended source?

        Returns (ok, detail). ok is False when the stream has no incoming
        links yet, or when any incoming link comes from a node other than
        ``self.source`` — i.e. the session manager silently rerouted us
        (typically to the default mic). Only meaningful for backend="pw"
        with an explicit source.
        """
        if self.backend != "pw" or not self.source:
            return True, "no explicit pw target to verify"
        # ".monitor" is a PulseAudio device suffix; the PipeWire node is the
        # bare sink name — accept either as a match.
        target_node = self.source.split(":", 1)[0]
        target_bare = target_node.removesuffix(".monitor")
        graph = _run_pw_link_l()
        if not graph:
            return False, "pw-link -l unavailable"
        peers: set[str] = set()
        current = None
        for raw in graph.splitlines():
            stripped = raw.strip()
            if not stripped:
                continue
            if stripped.startswith("|<-"):
                if current and current.startswith(self.stream_node_name + ":"):
                    peers.add(stripped[3:].strip().split(":", 1)[0])
            elif stripped.startswith("|->"):
                peer = stripped[3:].strip()
                if peer.startswith(self.stream_node_name + ":"):
                    peers.add(current.split(":", 1)[0] if current else "")
            elif not raw[0].isspace():
                current = stripped
        if not peers:
            return False, f"stream {self.stream_node_name} has no incoming links"
        if not peers.issubset({target_node, target_bare}):
            return False, (
                f"stream {self.stream_node_name} fed by {sorted(peers)} — "
                f"expected {target_node} (session manager rerouted us)"
            )
        return True, f"bound to {target_node}"

    def start(self) -> None:
        self._stop_requested = False
        self._rec = subprocess.Popen(
            self._recorder_cmd(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )
        self._worker = subprocess.Popen(
            self._worker_cmd(), stdin=self._rec.stdout,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        if self._rec.stdout:
            self._rec.stdout.close()  # the worker owns the read end now
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_loop(self) -> None:
        if not (self._worker and self._worker.stdout):
            return
        for line in self._worker.stdout:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if msg.get("ready"):
                self._ready.set()
            elif "text" in msg:
                self.on_text(msg["text"], self.label)
        # Pipeline ended. If nobody asked it to stop, the recorder/worker died
        # underneath us — surface it instead of going silently deaf.
        if not getattr(self, "_stop_requested", False):
            _log.warning(
                "StreamingTranscriber[%s]: pipeline ended unexpectedly (%s)",
                self.label, self.stream_node_name,
            )
            if self.on_stream_end is not None:
                try:
                    self.on_stream_end(self.label)
                except Exception:
                    _log.exception("on_stream_end callback failed")

    def wait_ready(self, timeout: float = 60.0) -> bool:
        return self._ready.wait(timeout)

    def stop(self) -> None:
        self._stop_requested = True
        for proc in (self._worker, self._rec):
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
        self._rec = self._worker = None
