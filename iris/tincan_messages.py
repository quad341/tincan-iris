"""TincanMessages — D-Bus client for im.tincan.Messages (SMS/messaging lane).

Subscribes to ``MessageReceived``, ``MessageSent``, ``ConversationUpdated``, and
``ContactPhotoReceived`` signals, and wraps the method API into Python calls.

Mirrors TincanCallControl's structure exactly — inject ``_bus`` in tests so
signal handlers can be invoked directly without a real GLib main loop.

Capability-gated: checks ``capabilities['messages']`` from
``im.tincan.Daemon.GetStatus`` at start. Method calls are no-ops when the
gateway lacks this capability so callers never need to check.

    ctrl = TincanMessages(emit=events.append)
    ctrl.start()           # daemon thread starts the GLib loop
    ...
    ctrl.stop()
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

_BUS_NAME = "im.tincan"
_OBJECT_PATH = "/im/tincan/Messages"
_INTERFACE = "im.tincan.Messages"
_DAEMON_PATH = "/im/tincan"
_DAEMON_IFACE = "im.tincan.Daemon"


class TincanMessages:
    """D-Bus subscriber + method client for tincan's messaging interface.

    All emitted events are tuples so they drop into the same queue as
    TincanCallControl events (both use ``emit(tuple)`` as the sink).
    """

    def __init__(
        self,
        *,
        emit: Callable[[tuple], None] | None = None,
        _bus: Any = None,
    ) -> None:
        self.emit = emit or (lambda ev: None)
        self._bus = _bus
        self._loop = None
        self._thread: threading.Thread | None = None
        self._capable: bool = False  # set by _check_capability() at start()

    # --- signal handlers (public — called directly in tests) ---

    def _on_message_received(
        self, conversation_id: str = "", message_id: str = "", *args: Any
    ) -> None:
        """``MessageReceived(conversation_id, message_id)``."""
        self.emit(("message_received", str(conversation_id), str(message_id)))

    def _on_message_sent(
        self, conversation_id: str = "", message_id: str = "", *args: Any
    ) -> None:
        """``MessageSent(conversation_id, message_id)``."""
        self.emit(("message_sent", str(conversation_id), str(message_id)))

    def _on_conversation_updated(
        self, conversation_id: str = "", *args: Any
    ) -> None:
        """``ConversationUpdated(conversation_id)``."""
        self.emit(("conversation_updated", str(conversation_id)))

    def _on_contact_photo_received(
        self, contact_id: str = "", *args: Any
    ) -> None:
        """``ContactPhotoReceived(contact_id)``."""
        self.emit(("contact_photo_received", str(contact_id)))

    # --- D-Bus proxy helpers ---

    def _proxy(self) -> Any | None:
        """Return the Messages proxy object, or None if incapable/unavailable."""
        if self._bus is None or not self._capable:
            return None
        try:
            return self._bus.get_object(_BUS_NAME, _OBJECT_PATH)
        except Exception:  # noqa: BLE001
            return None

    def _call(self, method_name: str, *args: Any) -> Any:
        """Dispatch a method on im.tincan.Messages. Returns None on any failure."""
        proxy = self._proxy()
        if proxy is None:
            return None
        try:
            return proxy.get_dbus_method(method_name, _INTERFACE)(*args)
        except Exception:  # noqa: BLE001
            self.emit(("messages_error", method_name))
            return None

    # --- method wrappers ---

    def list_conversations(self) -> list[dict]:
        """Return all conversations. Empty list when messaging is unavailable."""
        result = self._call("ListConversations")
        return list(result) if result is not None else []

    def get_messages(self, conversation_id: str) -> list[dict]:
        """Return all messages in a conversation."""
        result = self._call("GetMessages", str(conversation_id))
        return list(result) if result is not None else []

    def get_message(self, conversation_id: str, message_id: str) -> dict | None:
        """Return a single message by id."""
        return self._call("GetMessage", str(conversation_id), str(message_id))

    def send_message(self, conversation_id: str, body: str) -> bool:
        """Send a message to an existing conversation. Returns True on success."""
        result = self._call("SendMessage", str(conversation_id), str(body))
        return bool(result) if result is not None else False

    def send_message_to_recipients(
        self, numbers: list[str], body: str
    ) -> bool:
        """Start a new conversation to one or more recipients by E.164 number."""
        result = self._call("SendMessageToRecipients", list(numbers), str(body))
        return bool(result) if result is not None else False

    def get_conversation_participants(
        self, conversation_id: str
    ) -> list[dict]:
        """Return participants for a conversation (name + number)."""
        result = self._call("GetConversationParticipants", str(conversation_id))
        return list(result) if result is not None else []

    def get_contacts(self) -> list[dict]:
        """Return contacts from tincan for name→number resolution."""
        result = self._call("GetContacts")
        return list(result) if result is not None else []

    def mark_conversation_read(self, conversation_id: str) -> None:
        """Mark all messages in a conversation as read."""
        self._call("MarkConversationRead", str(conversation_id))

    # --- capability check ---

    def _check_capability(self) -> bool:
        """Return True iff tincan's daemon reports 'messages' capability."""
        if self._bus is None:
            return False
        try:
            daemon = self._bus.get_object(_BUS_NAME, _DAEMON_PATH)
            status = daemon.get_dbus_method("GetStatus", _DAEMON_IFACE)()
            return bool(status.get("capabilities", {}).get("messages", False))
        except Exception:  # noqa: BLE001
            return False

    # --- lifecycle ---

    def start(self) -> None:
        """Connect to the session bus, check capability, subscribe to signals.

        Safe to call when the session bus is unavailable — emits
        ``("bus_unavailable", reason)`` instead of raising.
        """
        try:
            import dbus  # noqa: PLC0415
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

        self._capable = self._check_capability()
        if not self._capable:
            self.emit(
                ("messages_unavailable", "tincan does not expose messaging capability")
            )

        for signal_name, handler in [
            ("MessageReceived", self._on_message_received),
            ("MessageSent", self._on_message_sent),
            ("ConversationUpdated", self._on_conversation_updated),
            ("ContactPhotoReceived", self._on_contact_photo_received),
        ]:
            self._bus.add_signal_receiver(
                handler,
                signal_name=signal_name,
                dbus_interface=_INTERFACE,
            )

        self._loop = GLib.MainLoop()
        self._thread = threading.Thread(
            target=self._loop.run, daemon=True, name="tincan-messages-dbus"
        )
        self._thread.start()

    def stop(self) -> None:
        if self._loop is not None:
            self._loop.quit()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._loop = None
        self._thread = None
