"""``python -m iris.daemon`` — start the always-on call-handling daemon (ADR-0006).

The daemon:
  1. Opens RosterStore + PostureManager
  2. Builds PolicyResolver + HandlingEngine (stubs until ti-gxpt.5)
  3. Starts DaemonAPI (Unix socket server)
  4. Writes PID to ~/.local/run/iris/daemon.pid
  5. Blocks on SIGTERM / SIGINT for graceful shutdown
"""
from __future__ import annotations

import logging
import os
import signal
import sys
import threading
from pathlib import Path

from .api import DaemonAPI
from .call_card_host import CallCardHost
from .engine import HandlingEngine
from .policy import PolicyResolver
from .posture import PostureManager, PostureWatcher
from ..notify_sink import DesktopNotifySink
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

    # Stub ctrl + notify_sink — wired up fully in ti-gxpt.5
    class _StubCtrl:
        def _answer(self, call_id): pass
        def _hangup(self, call_id): pass

    resolver = PolicyResolver(roster=roster, posture=posture)
    notify = DesktopNotifySink()
    engine = HandlingEngine(
        ctrl=_StubCtrl(),
        tts=None,
        resolver=resolver,
        notify_sink=notify,
        broadcast=lambda ev: None,  # rewired after api is built
    )

    # Construct CallCardHost when IRIS_CALL_CARD=1; None otherwise (section absent).
    call_card_host: CallCardHost | None = None
    if os.environ.get("IRIS_CALL_CARD") == "1":
        from iris.capture.processor import L1CaptureProcessor
        from iris.capture.store import CallCardStore
        call_card_host = CallCardHost(
            store=CallCardStore(),
            processor=L1CaptureProcessor(),
            api=None,       # patched below after api is built
            cfg=None,
        )
        engine._call_card_host = call_card_host

    api = DaemonAPI(posture=posture, engine=engine, call_card_host=call_card_host)
    # Rewire broadcast so engine uses the real API broadcast
    engine._broadcast = api.broadcast
    if call_card_host is not None:
        call_card_host._api = api

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
        api.stop()
        watcher.stop()
        _remove_pid(_PID_PATH)
        _log.info("iris daemon stopped")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
