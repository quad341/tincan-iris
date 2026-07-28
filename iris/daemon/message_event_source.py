"""MessageEventSource — ANCS/MAP D-Bus notification subscriber (ti-s9mm.4.2).

Subscribes to AppNotificationReceived on im.tincan.Daemon and routes each
notification to ProactiveStore (priority-2 badge) and DaemonAPI broadcast.

Security invariant: notification bodies are display data only — they MUST NEVER
be passed to Brain.respond() or Brain.respond_stream().
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

_IFACE = "im.tincan.Daemon"

_log = logging.getLogger(__name__)


class MessageEventSource:
    """Subscribes to tincand ANCS/MAP notification signals via D-Bus.

    Shares the SessionBus with TincanCallControl — pass _bus=ctrl._bus after
    ctrl.start() succeeds.  If _bus is None (D-Bus absent), start() is a no-op.

    Security invariant: _on_notification MUST NEVER call Brain.respond or
    Brain.respond_stream — notification bodies are display data only.
    """

    def __init__(
        self,
        *,
        proactive_store: object,
        broadcast: Callable[[dict], None],
        _bus: Any = None,
    ) -> None:
        self._proactive_store = proactive_store
        self._broadcast = broadcast
        self._bus = _bus

    def start(self) -> None:
        """Subscribe to AppNotificationReceived signals on the shared D-Bus."""
        if self._bus is None:
            _log.debug("MessageEventSource: no D-Bus bus — skipping subscription")
            return
        self._bus.add_signal_receiver(
            self._on_notification,
            signal_name="AppNotificationReceived",
            dbus_interface=_IFACE,
        )
        _log.info(
            "MessageEventSource: subscribed to AppNotificationReceived on %s", _IFACE
        )

    def stop(self) -> None:
        """Remove signal receiver; quit GLib loop if one was started."""
        if self._bus is None:
            return
        try:
            self._bus.remove_signal_receiver(
                self._on_notification,
                signal_name="AppNotificationReceived",
                dbus_interface=_IFACE,
            )
        except Exception:
            pass

    def _on_notification(
        self, sender: str = "", body: str = "", type_str: str = "", *args: Any
    ) -> None:
        """Handle AppNotificationReceived(sender, body, type_str).

        Enqueues to ProactiveStore at priority 2 and broadcasts a notification
        event to all connected clients.

        Security: body is display data — NEVER passed to Brain.respond().
        """
        sender = str(sender)
        body = str(body)

        try:
            self._proactive_store.enqueue(  # type: ignore[union-attr]
                trigger_class="ancs",
                priority=2,
                message=f"{sender}: {body}",
                source_skill="tincand",
            )
        except Exception:
            _log.exception("MessageEventSource: ProactiveStore.enqueue failed")

        self._broadcast({
            "event": "notification",
            "type": "ancs",
            "sender": sender,
            "body": body,
            "timestamp": time.time(),
        })
