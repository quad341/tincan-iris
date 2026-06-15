"""Continuous streaming transcription — a recorder piped into the venv VAD worker.

Spawns a continuous recorder feeding ``_whisper_stream.py`` (in the network-
isolated whisper venv); reads the worker's JSON transcripts on a thread and hands
each finished utterance to ``on_text``. This is the always-on input for the
console / call mode — you just talk, and each utterance arrives as text (no
push-to-talk). Pair with ``iris.addressing`` to act only when named.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_STREAM_SCRIPT = Path(__file__).resolve().parent / "_whisper_stream.py"
_DEFAULT_SIZE = os.environ.get("IRIS_WHISPER_MODEL_SIZE", "small.en")


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
    ) -> None:
        self.on_text = on_text
        self.source = source
        self.backend = backend
        self.label = label
        self.python = python or os.environ.get(
            "IRIS_WHISPER_PYTHON", str(_REPO_ROOT / ".venv-whisper" / "bin" / "python")
        )
        self.model = model or os.environ.get(
            "IRIS_WHISPER_DIR", str(_REPO_ROOT / "models" / "whisper" / _DEFAULT_SIZE)
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
            cmd = ["pw-record", "--raw", "--rate", "16000",
                   "--channels", "1", "--format", "s16"]
            if self.source:
                cmd += ["--target", self.source]
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

    def start(self) -> None:
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

    def wait_ready(self, timeout: float = 60.0) -> bool:
        return self._ready.wait(timeout)

    def stop(self) -> None:
        for proc in (self._worker, self._rec):
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
        self._rec = self._worker = None
