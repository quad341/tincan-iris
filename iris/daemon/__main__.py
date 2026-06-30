"""``python -m iris.daemon`` — start the always-on call-handling daemon (ADR-0006).

The daemon:
  1. Opens RosterStore + PostureManager
  2. Builds PolicyResolver + HandlingEngine
  3. Starts TincanCallControl (D-Bus call signals) + MessageEventSource (ANCS)
  4. Starts DaemonAPI (Unix socket server)
  5. Writes PID to ~/.local/run/iris/daemon.pid
  6. Blocks on SIGTERM / SIGINT for graceful shutdown
"""
from __future__ import annotations

import logging
import os
import signal
import sys
import threading
from pathlib import Path

from .api import DaemonAPI
from .brain_host import BrainHost
from .call_card_host import CallCardHost
from .engine import HandlingEngine
from .message_event_source import MessageEventSource
from .policy import PolicyResolver
from .posture import PostureManager, PostureWatcher
from ..brain import Brain
from ..call_control import TincanCallControl
from ..notes import NotesStore
from ..notify_sink import DesktopNotifySink
from ..prefs import PreferencesStore
from ..proactive_store import ProactiveStore
from ..roster import RosterStore

_PID_PATH = Path.home() / ".local" / "run" / "iris" / "daemon.pid"
_LOG_PATH = Path.home() / ".local" / "state" / "iris" / "daemon.log"
_DEFAULT_DB = Path.home() / ".local" / "share" / "iris" / "roster.db"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
_log = logging.getLogger("iris.daemon")


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


def _write_pid(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(os.getpid()))


def _remove_pid(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def main() -> int:
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

    # Construct CallCardHost when IRIS_CALL_CARD=1; None otherwise (section absent).
    call_card_host: CallCardHost | None = None
    if os.environ.get("IRIS_CALL_CARD") == "1":
        from iris.capture.processor import L1CaptureProcessor  # noqa: PLC0415
        from iris.capture.store import CallCardStore  # noqa: PLC0415
        call_card_host = CallCardHost(
            store=CallCardStore(),
            processor=L1CaptureProcessor(),
            api=None,       # patched below after api is built
            cfg=None,
        )
        engine._call_card_host = call_card_host

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
            engine.on_call_connected("")
        elif kind == "call_ended":
            engine.on_call_ended(str(ev[1]) if len(ev) > 1 else "")

    ctrl.emit = _on_tcc_event

    proactive_store = ProactiveStore()
    mes = MessageEventSource(
        proactive_store=proactive_store,
        broadcast=api.broadcast,
        _bus=None,  # wired to ctrl._bus inside _start_dbus_components
    )

    _start_dbus_components(ctrl, mes)

    _write_pid(_PID_PATH)
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
        _log.info("iris daemon ready")
        stop_event.wait()
    finally:
        _log.info("iris daemon stopping")
        mes.stop()
        ctrl.stop()
        api.stop()
        watcher.stop()
        _remove_pid(_PID_PATH)
        _log.info("iris daemon stopped")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
