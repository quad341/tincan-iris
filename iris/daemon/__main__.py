"""``python -m iris.daemon`` — start the always-on call-handling daemon (ADR-0006).

The daemon:
  1. Opens RosterStore + PostureManager
  2. Builds PolicyResolver + HandlingEngine
  3. Starts TincanCallControl (D-Bus call signals)
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
from .engine import HandlingEngine
from .policy import PolicyResolver
from .posture import PostureManager, PostureWatcher
from ..brain import Brain
from ..call_control import TincanCallControl
from ..notes import NotesStore
from ..notify_sink import DesktopNotifySink
from ..prefs import PreferencesStore
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

    notes = NotesStore(db_path)
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

    api = DaemonAPI(posture=posture, engine=engine)
    engine._broadcast = api.broadcast

    brain_host = BrainHost(brain=brain, db_path=db_path, broadcast=api.broadcast)
    api._brain_host = brain_host
    _log.info("iris daemon: Brain and BrainHost initialized")

    # Caller info cache: populated on incoming_call, consumed on call_connected.
    _caller: dict[str, str] = {"id": "", "name": "", "number": ""}

    def _on_tcc_event(ev: tuple) -> None:  # called from the tincan-dbus thread
        kind = ev[0]
        if kind == "bus_unavailable":
            _log.warning(
                "iris daemon: D-Bus unavailable, call control disabled — %s",
                ev[1] if len(ev) > 1 else "",
                extra={"dbus_absent": True},
            )
        elif kind == "incoming_call":
            caller_name, caller_number = str(ev[1]), str(ev[2])
            result = resolver.resolve(caller_number, "")
            contact = result.contact
            _caller["id"] = str(contact.id) if contact else ""
            _caller["name"] = contact.display_name if contact else caller_name
            _caller["number"] = contact.phone_e164 or caller_number if contact else caller_number
            engine.on_incoming_call(caller_number=caller_number)
        elif kind == "call_connected":
            brain_host.set_call_context(
                contact_id=_caller["id"],
                contact_name=_caller["name"],
                contact_number=_caller["number"],
            )
        elif kind == "call_ended":
            engine.on_call_ended(str(ev[1]))
            brain_host.clear_call_context()

    ctrl.emit = _on_tcc_event
    ctrl.start()

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
        ctrl.stop()
        api.stop()
        watcher.stop()
        _remove_pid(_PID_PATH)
        _log.info("iris daemon stopped")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
