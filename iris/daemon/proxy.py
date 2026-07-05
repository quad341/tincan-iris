"""DaemonProxy — client-side connector to the iris daemon (ADR-0006).

Provides a thin wrapper around the daemon's Unix socket protocol:
  - connect() establishes the connection and starts the single reader thread
    (raises DaemonNotRunning if absent)
  - send(cmd) sends a command and returns the synchronous ack
  - start_event_reader() registers the async-event callback

ONE reader owns the socket. Acks and events share the connection, so exactly
one thread may read it: the reader routes "ack" objects to the FIFO of
pending send() slots (the daemon processes a connection's commands in order,
so first-ack-to-first-sender is sound) and "event" objects to the registered
callback. The previous design had send() and the event loop both reading the
same buffered stream — whoever lost the race swallowed the other's line, which
froze the console UI thread inside send() forever (found live 2026-07-05).

Graceful degradation: callers catch DaemonNotRunning and fall back to direct mode.
"""
from __future__ import annotations

import json
import logging
import queue
import socket
import threading
from collections import deque
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

    #: send() waits at most this long for its ack before declaring the daemon
    #: unresponsive — a blocked UI beats a frozen one, a frozen one is a bug.
    ACK_TIMEOUT_S = 5.0

    def __init__(self, socket_path: Path | None = None) -> None:
        self._path = socket_path or daemon_socket_path()
        self._sock: socket.socket | None = None
        self._rfile = None
        self._wfile = None
        self._send_lock = threading.Lock()
        self._reader_thread: threading.Thread | None = None
        # FIFO of queues, one per in-flight send(); the reader fulfils them
        # in order. Guarded by _pending_lock (reader vs senders).
        self._pending: deque[queue.Queue] = deque()
        self._pending_lock = threading.Lock()
        self._on_event: Callable[[dict], None] | None = None
        self._on_disconnect: Callable[[], None] | None = None
        self._closed = False

    def connect(self) -> None:
        """Connect to the daemon socket.

        Raises DaemonNotRunning if the socket file is absent or the connection is
        refused (daemon not started).
        """
        if not self._path.exists():
            raise DaemonNotRunning(
                "Iris daemon is not running.\n"
                "Start it with:  iris daemon start"
            )
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(str(self._path))
        except (ConnectionRefusedError, FileNotFoundError) as exc:
            raise DaemonNotRunning(
                "Iris daemon is not running.\n"
                "Start it with:  iris daemon start"
            ) from exc
        self._sock = sock
        self._rfile = sock.makefile("rb")
        self._wfile = sock.makefile("wb")
        self._closed = False
        # The single reader starts with the connection: send() depends on it
        # to deliver acks, whether or not the caller ever registers events.
        self._reader_thread = threading.Thread(
            target=self._read_loop, name="daemon-proxy-reader", daemon=True,
        )
        self._reader_thread.start()

    def send(self, cmd: dict) -> dict:
        """Send a command dict and return the ack dict.

        Never reads the socket itself — the reader thread routes the ack to
        this call's FIFO slot. Waits at most ACK_TIMEOUT_S, then raises
        DaemonNotRunning so a caller on the UI thread degrades instead of
        freezing.
        """
        if self._sock is None:
            raise RuntimeError("DaemonProxy.send() called before connect()")
        slot: queue.Queue = queue.Queue(maxsize=1)
        line = json.dumps(cmd, separators=(",", ":")) + "\n"
        with self._send_lock:
            with self._pending_lock:
                self._pending.append(slot)
            try:
                self._wfile.write(line.encode())
                self._wfile.flush()
            except OSError as exc:
                with self._pending_lock:
                    if slot in self._pending:
                        self._pending.remove(slot)
                raise DaemonNotRunning("Lost connection to daemon") from exc
        try:
            result = slot.get(timeout=self.ACK_TIMEOUT_S)
        except queue.Empty:
            with self._pending_lock:
                if slot in self._pending:
                    self._pending.remove(slot)
            raise DaemonNotRunning(
                f"Daemon did not ack within {self.ACK_TIMEOUT_S:.0f}s"
            ) from None
        if result is None:
            raise DaemonNotRunning("Daemon closed the connection")
        return result

    def start_event_reader(
        self,
        on_event: Callable[[dict], None],
        on_disconnect: Callable[[], None] | None = None,
    ) -> None:
        """Register the async-event callback (the reader itself starts at connect()).

        on_event is called for each event JSON object received.
        on_disconnect is called when the connection closes.
        """
        if self._rfile is None:
            raise RuntimeError("start_event_reader() called before connect()")
        self._on_event = on_event
        self._on_disconnect = on_disconnect

    def _fail_pending(self) -> None:
        """Wake every in-flight send() with a connection-closed result."""
        with self._pending_lock:
            pending, self._pending = list(self._pending), deque()
        for slot in pending:
            try:
                slot.put_nowait(None)
            except queue.Full:
                pass

    def _read_loop(self) -> None:
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
                if "ack" in obj:
                    # Route to the oldest in-flight send() — the daemon acks a
                    # connection's commands in order, so FIFO matching is sound.
                    with self._pending_lock:
                        slot = self._pending.popleft() if self._pending else None
                    if slot is not None:
                        slot.put(obj)
                    else:
                        _log.warning("DaemonProxy: ack with no pending send: %r",
                                     obj.get("ack"))
                    continue
                on_event = self._on_event
                if on_event is None:
                    _log.debug("DaemonProxy: event before callback registered: %r",
                               obj.get("event"))
                    continue
                try:
                    on_event(obj)
                except Exception:
                    _log.exception("DaemonProxy: on_event handler raised")
        except OSError:
            pass
        finally:
            self._fail_pending()
            on_disconnect = self._on_disconnect
            if on_disconnect is not None and not self._closed:
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
        self._closed = True  # deliberate close — suppress on_disconnect
        self._fail_pending()
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
