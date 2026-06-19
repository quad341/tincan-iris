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
from collections.abc import Callable
from typing import Any

from .audio.endpoint import TincanSCOAudio, discover_sco_nodes

_BUS_NAME = "im.tincan"
_OBJECT_PATH = "/im/tincan/Calls"
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
    ) -> None:
        self.auto_answer = auto_answer
        self.emit = emit or (lambda ev: None)
        self.endpoint: TincanSCOAudio | None = None
        self._bus = _bus
        self._loop = None
        self._thread: threading.Thread | None = None

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
        """``CallConnected`` — rediscover SCO nodes and bind the new endpoint."""
        sink, source = discover_sco_nodes()
        if sink:
            self.endpoint = TincanSCOAudio(sink, source)
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

    def dial(self, number: str) -> str | None:
        """Place an outgoing call via ``Dial(number)`` on ``im.tincan.Calls``.

        tincand drives oFono's VoiceCallManager.Dial; on success it returns the
        new call's id (a string), and a ``CallConnected`` signal later binds the
        SCO audio endpoint exactly as for an answered call — so Iris rides an
        outgoing call the same way she rides an incoming one. Mirrors
        :meth:`_answer`: no bus → no-op; a D-Bus error emits ``("dial_error",
        number)`` and returns ``None`` rather than raising, so a dialing hiccup
        never crashes the brain.

        This is a privileged action — the *skill* that calls it is gated to the
        operator/mic channel; this transport method does no gating itself."""
        if self._bus is None:
            return None
        try:
            proxy = self._bus.get_object(_BUS_NAME, _OBJECT_PATH)
            result = proxy.get_dbus_method("Dial", _INTERFACE)(number)
            return str(result) if result is not None else ""
        except Exception:  # noqa: BLE001 — D-Bus hiccup: log and move on
            self.emit(("dial_error", number))
            return None

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
