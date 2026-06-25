"""DaemonProxy — client-side connector to the iris daemon (ADR-0006).

Provides a thin wrapper around the daemon's Unix socket protocol:
  - connect() establishes the connection (raises DaemonNotRunning if absent)
  - send(cmd) sends a command and returns the synchronous ack
  - start_event_reader() spawns a background thread that receives async events

Graceful degradation: callers catch DaemonNotRunning and fall back to direct mode.
"""
from __future__ import annotations

import json
import logging
import socket
import threading
from pathlib import Path
from typing import Callable

from ._socket_path import daemon_socket_path

_log = logging.getLogger(__name__)


class DaemonNotRunning(Exception):
    """Raised by connect() when the daemon socket is not present or not reachable."""


class DaemonProxy:
    """Client-side connector to the iris daemon.

    Typical usage::
        proxy = DaemonProxy()
        try:
            proxy.connect()
        except DaemonNotRunning:
            # fall back to direct mode
            ...
        ack = proxy.send({"cmd": "dnd", "action": "on"})
        proxy.start_event_reader(on_event=my_handler)
        ...
        proxy.close()
    """

    def __init__(self, socket_path: Path | None = None) -> None:
        self._path = socket_path or daemon_socket_path()
        self._sock: socket.socket | None = None
        self._rfile = None
        self._wfile = None
        self._send_lock = threading.Lock()
        self._reader_thread: threading.Thread | None = None

    def connect(self) -> None:
        """Connect to the daemon socket.

        Raises DaemonNotRunning if the socket file is absent or the connection is
        refused (daemon not started).
        """
        if not self._path.exists():
            raise DaemonNotRunning(
                f"Iris daemon is not running.\n"
                f"Start it with:  iris daemon start"
            )
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(str(self._path))
        except (ConnectionRefusedError, FileNotFoundError) as exc:
            raise DaemonNotRunning(
                f"Iris daemon is not running.\n"
                f"Start it with:  iris daemon start"
            ) from exc
        self._sock = sock
        self._rfile = sock.makefile("rb")
        self._wfile = sock.makefile("wb")

    def send(self, cmd: dict) -> dict:
        """Send a command dict and return the ack dict.

        Thread-safe via _send_lock.  The event-reader thread must be started
        separately; this method reads only the next line from the server
        (which will be the ack for the sent command).
        """
        if self._sock is None:
            raise RuntimeError("DaemonProxy.send() called before connect()")
        line = json.dumps(cmd, separators=(",", ":")) + "\n"
        with self._send_lock:
            try:
                self._wfile.write(line.encode())
                self._wfile.flush()
                raw = self._rfile.readline()
            except OSError as exc:
                raise DaemonNotRunning("Lost connection to daemon") from exc
        if not raw:
            raise DaemonNotRunning("Daemon closed the connection")
        return json.loads(raw)

    def start_event_reader(
        self,
        on_event: Callable[[dict], None],
        on_disconnect: Callable[[], None] | None = None,
    ) -> None:
        """Start a daemon thread that reads async events from the daemon.

        on_event is called for each event JSON object received.
        on_disconnect is called when the connection closes.
        """
        if self._rfile is None:
            raise RuntimeError("start_event_reader() called before connect()")
        self._reader_thread = threading.Thread(
            target=self._read_loop,
            args=(on_event, on_disconnect),
            name="daemon-proxy-reader",
            daemon=True,
        )
        self._reader_thread.start()

    def _read_loop(
        self,
        on_event: Callable[[dict], None],
        on_disconnect: Callable[[], None] | None,
    ) -> None:
        try:
            for raw in self._rfile:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    _log.warning("DaemonProxy: malformed event line: %r", raw[:80])
                    continue
                # Events have "event" key; acks have "ack" key — both arrive here
                # since we share one connection.  Pass everything to on_event; caller
                # discriminates by key.
                try:
                    on_event(obj)
                except Exception:
                    _log.exception("DaemonProxy: on_event handler raised")
        except OSError:
            pass
        finally:
            if on_disconnect is not None:
                try:
                    on_disconnect()
                except Exception:
                    _log.exception("DaemonProxy: on_disconnect handler raised")

    def close(self) -> None:
        """Close the connection.

        Shuts down the socket FIRST so any thread blocked in _read_loop()
        (which holds the BufferedReader internal lock) is unblocked before
        we call rfile.close() — otherwise close() deadlocks waiting for
        the lock the blocked thread holds.
        """
        if self._sock is not None:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self._sock.close()
            except OSError:
                pass
        self._sock = None
        if self._rfile is not None:
            try:
                self._rfile.close()
            except OSError:
                pass
        if self._wfile is not None:
            try:
                self._wfile.close()
            except OSError:
                pass
        self._rfile = None
        self._wfile = None
