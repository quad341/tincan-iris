"""``python -m iris.daemon`` — start the always-on call-handling daemon (ADR-0006).

The daemon:
  1. Acquires an exclusive flock on the pid/lock file (same directory as the
     socket, same resolver — see _socket_path.py); exits if already held
  2. Opens RosterStore + PostureManager
  3. Builds PolicyResolver + HandlingEngine
  4. Starts TincanCallControl (D-Bus call signals) + MessageEventSource (ANCS)
  5. Starts DaemonAPI (Unix socket server)
  6. Blocks on SIGTERM / SIGINT for graceful shutdown
"""
from __future__ import annotations

import fcntl
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

from ._socket_path import daemon_pid_path
from .api import DaemonAPI
from .brain_host import BrainHost
from .engine import HandlingEngine
from .heartbeat import BaselineHeartbeat
from .message_event_source import MessageEventSource
from .policy import PolicyResolver
from .posture import PostureManager, PostureWatcher
from .. import settings
from ..brain import Brain
from ..call_control import TincanCallControl
from ..config import Config
from ..notes import NotesStore
from ..notify_sink import DesktopNotifySink
from ..prefs import PreferencesStore
from ..proactive_store import ProactiveStore
from ..roster import RosterStore

if TYPE_CHECKING:
    # Runtime import is deferred into the IRIS_CALL_CARD block below so the base
    # daemon starts without the `call-card` optional extra (NFR-03).
    from .call_card_host import CallCardHost

_PID_PATH = daemon_pid_path()
_LOG_PATH = Path.home() / ".local" / "state" / "iris" / "daemon.log"
_DEFAULT_DB = Path.home() / ".local" / "share" / "iris" / "roster.db"
_AEC_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "aec_audio.sh"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
_log = logging.getLogger("iris.daemon")


def _run_aec_async(action: str) -> None:
    """Best-effort WebRTC AEC bridge on a live call, in a background thread.

    In proxy mode the daemon (not the console) owns the call, so it must wire the
    live SCO nodes into the canceller — otherwise the operator's mic isn't echo-
    cancelled and the far party hears echo. No-op if the script or the canceller
    isn't present. The SCO nodes can lag ``call_connected``, so ``bridge`` retries.
    """
    if not _AEC_SCRIPT.exists():
        return

    def _run() -> None:
        attempts = 4 if action == "bridge" else 1
        for i in range(attempts):
            try:
                result = subprocess.run(
                    ["bash", str(_AEC_SCRIPT), action],
                    capture_output=True, text=True, timeout=15,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                _log.warning("iris daemon: aec %s failed: %s", action, exc)
                return
            if result.returncode == 0:
                _log.info("iris daemon: aec %s ok", action)
                return
            if i + 1 < attempts:
                time.sleep(0.7)  # SCO nodes may not be up yet right after connect
        _log.info(
            "iris daemon: aec %s did not complete (SCO nodes not ready / AEC not loaded)",
            action,
        )

    threading.Thread(target=_run, name=f"aec-{action}", daemon=True).start()


def _start_dbus_components(ctrl: object, mes: object) -> None:
    """Start TincanCallControl then MessageEventSource; log gracefully on D-Bus failure.

    Wires the shared SessionBus (ctrl._bus) into mes before calling mes.start() so
    MessageEventSource can subscribe on the existing bus without opening a second one.
    """
    try:
        ctrl.start()  # type: ignore[union-attr]
    except Exception as exc:  # noqa: BLE001
        _log.warning("D-Bus unavailable — dbus_absent: %s", exc, extra={"dbus_absent": True})
    bus = getattr(ctrl, "_bus", None)
    if bus is not None:
        mes._bus = bus  # type: ignore[union-attr]
    try:
        mes.start()  # type: ignore[union-attr]
    except Exception as exc:  # noqa: BLE001
        _log.warning("D-Bus unavailable — dbus_absent: %s", exc, extra={"dbus_absent": True})


class _DaemonAlreadyRunning(Exception):
    """Raised when another live process already holds the daemon's exclusivity lock."""

    def __init__(self, holder_pid: str) -> None:
        super().__init__(f"another instance holds the lock (pid {holder_pid})")
        self.holder_pid = holder_pid


def _acquire_exclusive_lock(path: Path):
    """Acquire an exclusive, non-blocking flock on ``path``; write our pid on success.

    Returns the open file object — keep it referenced for the process's entire
    lifetime (do not close it). The kernel releases the lock the instant all of
    its file descriptors close, including on crash/SIGKILL/OOM-kill, which is
    what makes this immune to the stale-pid-file/TOCTOU class of bug.

    Raises _DaemonAlreadyRunning if another live process already holds it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = open(path, "a+")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_file.seek(0)
        holder = lock_file.read().strip() or "unknown"
        lock_file.close()
        raise _DaemonAlreadyRunning(holder) from None
    lock_file.truncate(0)
    lock_file.write(str(os.getpid()))
    lock_file.flush()
    return lock_file


def _remove_pid(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _load_call_card_config() -> Config:
    """Real Config for CallCardHost/PostCallEnricher — env > config.toml > default.

    Only the Call Card knobs are threaded through here; the rest of Config's
    fields (Brain/latency/proactive/etc.) stay at their built-in defaults —
    the daemon doesn't construct a Brain-facing Config today.
    """
    return Config(
        call_card_disclosure_script=settings.get("IRIS_CALL_CARD_DISCLOSURE_SCRIPT", ""),
    )


def main() -> int:
    try:
        _lock_file = _acquire_exclusive_lock(_PID_PATH)  # noqa: F841 — held for our lifetime, see docstring
    except _DaemonAlreadyRunning as exc:
        _log.error("iris daemon: %s — exiting", exc)
        return 1

    db_path = Path(os.environ.get("IRIS_DB", str(_DEFAULT_DB)))

    roster = RosterStore(db_path)
    posture = PostureManager(path=db_path)
    watcher = PostureWatcher(posture)

    notes = NotesStore()  # uses default ~/.local/share/iris/notes.json, NOT roster.db
    prefs = PreferencesStore()

    # Create TCC with null emit placeholder; emit is wired after brain_host is ready.
    # Shared SessionBus is created inside ctrl.start() — MessageEventSource (ti-s9mm.4.2)
    # will receive it via ctrl._bus after start() returns successfully.
    ctrl = TincanCallControl(auto_answer=False)

    brain = Brain(ctrl=ctrl, notes_store=notes, prefs=prefs)

    resolver = PolicyResolver(roster=roster, posture=posture)
    notify = DesktopNotifySink()
    engine = HandlingEngine(
        ctrl=ctrl,
        tts=None,
        resolver=resolver,
        notify_sink=notify,
        broadcast=lambda ev: None,  # rewired after api is built
    )

    # Call Card capture is ON by default — a local, silent capture that hurts
    # nothing, so it doesn't hide behind an opt-in flag. Set IRIS_CALL_CARD=0 to
    # disable. Skips gracefully if the `call-card` extra (phonenumbers/dateparser)
    # isn't installed, so the base daemon still runs (NFR-03).
    call_card_host: CallCardHost | None = None
    if os.environ.get("IRIS_CALL_CARD", "1").strip().lower() not in ("0", "false", "no", "off"):
        try:
            from .call_card_host import CallCardHost  # noqa: PLC0415
            from iris.capture.processor import L1CaptureProcessor  # noqa: PLC0415
            from iris.capture.store import CallCardStore  # noqa: PLC0415
        except ImportError as exc:
            _log.warning(
                "Call Card capture DISABLED — required deps missing (%s). This "
                "should not happen on a normal install; run `pip install -e .`.", exc,
            )
        else:
            call_card_host = CallCardHost(
                store=CallCardStore(),
                processor=L1CaptureProcessor(),
                api=None,       # patched below after api is built
                cfg=_load_call_card_config(),
            )
            engine._call_card_host = call_card_host
            _log.info("iris daemon: Call Card capture ENABLED")

    brain_host = BrainHost(brain=brain, db_path=db_path, broadcast=lambda ev: None)
    api = DaemonAPI(
        posture=posture,
        engine=engine,
        brain_host=brain_host,
        call_card_host=call_card_host,
    )
    engine._broadcast = api.broadcast
    brain_host._broadcast = api.broadcast
    engine._brain_host = brain_host
    if call_card_host is not None:
        call_card_host._api = api

    # ti-pugo3.2 (not yet built) will pass on_transition= here to decide when a
    # baseline change is worth notifying about; this daemon only computes+caches.
    heartbeat = BaselineHeartbeat(is_daemon_socket_healthy=api.is_healthy)
    api.set_heartbeat(heartbeat)

    _log.info("iris daemon: Brain and BrainHost initialized")

    def _on_tcc_event(ev: tuple) -> None:  # called from the tincan-dbus thread
        kind = ev[0]
        if kind == "bus_unavailable":
            _log.warning(
                "iris daemon: D-Bus unavailable, call control disabled — %s",
                ev[1] if len(ev) > 1 else "",
                extra={"dbus_absent": True},
            )
        elif kind == "incoming_call":
            caller_number = str(ev[2]) if len(ev) > 2 else ""
            engine.on_incoming_call(caller_number=caller_number)
        elif kind == "call_connected":
            _run_aec_async("bridge")  # feedback-free speakerphone — daemon owns the proxy call
            engine.on_call_connected("")
        elif kind == "call_ended":
            engine.on_call_ended(str(ev[1]) if len(ev) > 1 else "")
            _run_aec_async("unbridge")

    ctrl.emit = _on_tcc_event

    proactive_store = ProactiveStore()
    mes = MessageEventSource(
        proactive_store=proactive_store,
        broadcast=api.broadcast,
        _bus=None,  # wired to ctrl._bus inside _start_dbus_components
    )

    # Load the WebRTC AEC before any call can start (default ON — ti-wunrs;
    # IRIS_AEC=0 opts out). The daemon only ever bridged an already-loaded
    # canceller before, so proxy-mode setups without a console got no echo
    # cancellation unless someone ran aec_audio.sh by hand.
    if settings.get_bool("IRIS_AEC", default=True):
        _run_aec_async("up")

    _start_dbus_components(ctrl, mes)

    _log.info("iris daemon starting (pid=%d)", os.getpid())

    stop_event = threading.Event()

    def _on_signal(signum, frame):
        _log.info("iris daemon received signal %d — shutting down", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    try:
        watcher.start()
        api.start()
        heartbeat.start()
        _log.info("iris daemon ready")
        stop_event.wait()
    finally:
        _log.info("iris daemon stopping")
        mes.stop()
        ctrl.stop()
        api.stop()
        heartbeat.stop()
        watcher.stop()
        _remove_pid(_PID_PATH)
        _log.info("iris daemon stopped")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
