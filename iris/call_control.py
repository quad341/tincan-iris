"""TincanCallControl — D-Bus client for im.tincan.Calls.

Subscribes to ``im.tincan.Calls`` signals and acts by policy:
  - ``IncomingCall``: optional auto-answer (opt-in; off by default)
  - ``CallConnected``: (re)discover live SCO PipeWire nodes → update ``endpoint``
  - ``CallEnded``: drop the current endpoint, emit event
  - ``AudioError`` / ``AudioRestored``: propagate as events

The D-Bus main loop runs in a daemon thread so callers don't block. All
callbacks fire on that thread; ``emit`` must be thread-safe (list.append is).

For tests, inject a ``_bus`` mock — the signal handlers (``_on_incoming``,
``_on_connected``, etc.) are public so tests can call them directly.

Real usage::

    ctrl = TincanCallControl(auto_answer=True, emit=events.append)
    ctrl.start()           # non-blocking — daemon thread starts the GLib loop
    ...
    ctrl.stop()            # quit the loop; thread joins with a short timeout
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from . import settings
from .audio.endpoint import TincanSCOAudio, discover_sco_nodes

# Authoritative addresses, confirmed by introspecting the live daemon:
#   busctl --user introspect im.tincan.Daemon /im/tincan
# The im.tincan.Calls interface (Answer/Dial; CallConnected/CallEnded/IncomingCall)
# is exported at bus name im.tincan.Daemon, object path /im/tincan — NOT a
# dedicated /im/tincan/Calls path. (Same shape as the messages fix in #81.)
_BUS_NAME = "im.tincan.Daemon"
_OBJECT_PATH = "/im/tincan"
_INTERFACE = "im.tincan.Calls"


class TincanCallControl:
    """D-Bus subscriber for tincan call lifecycle signals.

    ``auto_answer=True`` makes Iris answer every incoming call autonomously.
    Set to False (the default) for supervised mode — the operator answers; Iris
    just picks up the audio endpoint on ``CallConnected``.
    """

    def __init__(
        self,
        *,
        auto_answer: bool = False,
        emit: Callable[[tuple], None] | None = None,
        _bus: Any = None,   # injected in tests; None → real dbus.SessionBus at start()
        discover_tries: int = 6,
        discover_delay: float = 0.25,
    ) -> None:
        self.auto_answer = auto_answer
        self.emit = emit or (lambda ev: None)
        self.endpoint: TincanSCOAudio | None = None
        self._bus = _bus
        self._loop = None
        self._thread: threading.Thread | None = None
        # SCO PipeWire nodes can lag the CallConnected signal slightly; retry
        # discovery briefly. Tests pass discover_tries=1, discover_delay=0.
        self._discover_tries = discover_tries
        self._discover_delay = discover_delay

    # --- signal handlers (public — called directly in tests) ---

    def _on_incoming(self, caller_name: str = "", caller_number: str = "", *args: Any) -> None:
        """``IncomingCall(caller_name, caller_number)`` — answer if policy says yes.

        tincan emits the caller's name + number (no call id); the number drives
        the per-contact roster lookup (ADR-0004/0005). ``Answer("")`` answers the
        single ringing call (tincan semantics)."""
        self.emit(("incoming_call", str(caller_name), str(caller_number)))
        if self.auto_answer:
            self._answer("")

    def _on_connected(self, call_id: str = "", *args: Any) -> None:
        """``CallConnected`` — rediscover SCO nodes and bind the new endpoint.

        The SCO PipeWire nodes appear when the call's audio transport comes up,
        which can lag the signal slightly, so retry discovery briefly. AEC is
        enabled per ``IRIS_AEC`` so the console's ride-along is echo-free.
        """
        sink = source = None
        for attempt in range(max(1, self._discover_tries)):
            sink, source = discover_sco_nodes()
            if sink:
                break
            if attempt + 1 < self._discover_tries:
                time.sleep(self._discover_delay)
        if sink:
            self.endpoint = TincanSCOAudio(
                sink, source, aec=settings.get_bool("IRIS_AEC")
            )
        self.emit(("call_connected", sink, source))

    def _on_ended(self, call_id: str = "", *args: Any) -> None:
        """``CallEnded`` — drop the audio endpoint."""
        self.endpoint = None
        self.emit(("call_ended", str(call_id)))

    def _on_audio_error(self, call_id: str = "", reason: str = "", *args: Any) -> None:
        self.emit(("audio_error", str(call_id), str(reason)))

    def _on_audio_restored(self, call_id: str = "", *args: Any) -> None:
        self.emit(("audio_restored", str(call_id)))

    # --- D-Bus call ---

    def _answer(self, call_id: str = "") -> None:
        """Send ``Answer(call_id)`` on the D-Bus interface. call_id='' answers the
        single ringing call (tincan semantics)."""
        if self._bus is None:
            return
        try:
            proxy = self._bus.get_object(_BUS_NAME, _OBJECT_PATH)
            proxy.get_dbus_method("Answer", _INTERFACE)(call_id)
        except Exception:  # noqa: BLE001 — D-Bus hiccup: log and move on
            self.emit(("answer_error", call_id))

    def _dial(self, number: str) -> str | None:
        """Send ``Dial(number)`` on the D-Bus interface. Fire-and-continue: does not
        wait for CallConnected. 15-second timeout handling belongs in DialSkill."""
        if self._bus is None:
            return None
        try:
            proxy = self._bus.get_object(_BUS_NAME, _OBJECT_PATH)
            proxy.get_dbus_method("Dial", _INTERFACE)(number)
            return None
        except Exception as exc:  # noqa: BLE001 — D-Bus hiccup: log and surface to caller
            self.emit(("dial_error", number, str(exc)))
            return str(exc)

    def dial(self, number: str) -> str | None:
        """Place an outgoing call to ``number``. Returns None on success, error
        string on ``DBusException``."""
        return self._dial(number)

    # --- lifecycle ---

    def start(self) -> None:
        """Connect to the session bus and start the GLib main loop in a daemon thread.

        Safe to call when the session bus is unavailable (e.g. CI): catches
        ``dbus.exceptions.DBusException`` and emits ``("bus_unavailable",)`` instead
        of crashing.
        """
        try:
            import dbus  # noqa: PLC0415 — lazy: only needed at runtime
            import dbus.mainloop.glib  # noqa: PLC0415
            from gi.repository import GLib  # noqa: PLC0415
        except ImportError:
            self.emit(("bus_unavailable", "dbus-python or GLib not installed"))
            return

        try:
            dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
            if self._bus is None:
                self._bus = dbus.SessionBus()
        except Exception as exc:  # noqa: BLE001
            self.emit(("bus_unavailable", str(exc)))
            return

        for signal_name, handler in [
            ("IncomingCall", self._on_incoming),
            ("CallConnected", self._on_connected),
            ("CallEnded", self._on_ended),
            ("AudioError", self._on_audio_error),
            ("AudioRestored", self._on_audio_restored),
        ]:
            self._bus.add_signal_receiver(
                handler,
                signal_name=signal_name,
                dbus_interface=_INTERFACE,
            )

        self._loop = GLib.MainLoop()
        self._thread = threading.Thread(target=self._loop.run, daemon=True, name="tincan-dbus")
        self._thread.start()

    def stop(self) -> None:
        if self._loop is not None:
            self._loop.quit()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._loop = None
        self._thread = None
