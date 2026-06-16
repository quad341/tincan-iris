"""Tests for TincanMessages.

No D-Bus daemon, no GLib loop: the mock bus is injected and signal handlers
are invoked directly so tests run in plain pytest."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from iris.tincan_messages import TincanMessages


def _msgs(*, capable: bool = True) -> tuple[TincanMessages, list]:
    """Factory: TincanMessages with a mock bus, already marked capable (or not)."""
    events: list = []
    mock_bus = MagicMock()
    m = TincanMessages(emit=events.append, _bus=mock_bus)
    m._capable = capable
    return m, events


# --- signal handlers ---

def test_message_received_emits_event():
    m, events = _msgs()
    m._on_message_received("conv-1", "msg-42")
    assert ("message_received", "conv-1", "msg-42") in events


def test_message_received_tolerates_extra_args():
    m, events = _msgs()
    m._on_message_received("conv-1", "msg-42", "extra")
    assert ("message_received", "conv-1", "msg-42") in events


def test_message_sent_emits_event():
    m, events = _msgs()
    m._on_message_sent("conv-1", "msg-7")
    assert ("message_sent", "conv-1", "msg-7") in events


def test_conversation_updated_emits_event():
    m, events = _msgs()
    m._on_conversation_updated("conv-2")
    assert ("conversation_updated", "conv-2") in events


def test_contact_photo_received_emits_event():
    m, events = _msgs()
    m._on_contact_photo_received("contact-99")
    assert ("contact_photo_received", "contact-99") in events


# --- method wrappers: capable ---

def test_list_conversations_calls_dbus():
    m, _ = _msgs()
    m._bus.get_object.return_value.get_dbus_method.return_value.return_value = [
        {"id": "c1", "display_name": "Alice", "unread_count": 2},
    ]
    result = m.list_conversations()
    m._bus.get_object.assert_called_with("im.tincan", "/im/tincan/Messages")
    proxy = m._bus.get_object.return_value
    proxy.get_dbus_method.assert_called_with("ListConversations", "im.tincan.Messages")
    assert len(result) == 1
    assert result[0]["display_name"] == "Alice"


def test_get_messages_calls_dbus():
    m, _ = _msgs()
    m._bus.get_object.return_value.get_dbus_method.return_value.return_value = [
        {"body": "hi", "sender": "+1555"},
    ]
    result = m.get_messages("conv-1")
    proxy = m._bus.get_object.return_value
    proxy.get_dbus_method.assert_called_with("GetMessages", "im.tincan.Messages")
    method = proxy.get_dbus_method.return_value
    method.assert_called_once_with("conv-1")
    assert result[0]["body"] == "hi"


def test_get_message_calls_dbus():
    m, _ = _msgs()
    m._bus.get_object.return_value.get_dbus_method.return_value.return_value = {
        "body": "hello", "id": "msg-1"
    }
    result = m.get_message("conv-1", "msg-1")
    proxy = m._bus.get_object.return_value
    proxy.get_dbus_method.assert_called_with("GetMessage", "im.tincan.Messages")
    method = proxy.get_dbus_method.return_value
    method.assert_called_once_with("conv-1", "msg-1")
    assert result["body"] == "hello"


def test_send_message_returns_true_on_success():
    m, _ = _msgs()
    m._bus.get_object.return_value.get_dbus_method.return_value.return_value = True
    assert m.send_message("conv-1", "Hey") is True


def test_send_message_to_recipients_calls_dbus():
    m, _ = _msgs()
    m._bus.get_object.return_value.get_dbus_method.return_value.return_value = True
    assert m.send_message_to_recipients(["+15555550100"], "Hi") is True
    proxy = m._bus.get_object.return_value
    proxy.get_dbus_method.assert_called_with(
        "SendMessageToRecipients", "im.tincan.Messages"
    )
    method = proxy.get_dbus_method.return_value
    method.assert_called_once_with(["+15555550100"], "Hi")


def test_get_conversation_participants_calls_dbus():
    m, _ = _msgs()
    m._bus.get_object.return_value.get_dbus_method.return_value.return_value = [
        {"name": "Bob", "number": "+1555"}
    ]
    result = m.get_conversation_participants("conv-1")
    assert result[0]["name"] == "Bob"


def test_get_contacts_calls_dbus():
    m, _ = _msgs()
    m._bus.get_object.return_value.get_dbus_method.return_value.return_value = [
        {"display_name": "Alice", "number": "+15555550123"},
    ]
    contacts = m.get_contacts()
    assert contacts[0]["display_name"] == "Alice"


def test_mark_conversation_read_calls_dbus():
    m, _ = _msgs()
    m.mark_conversation_read("conv-1")
    proxy = m._bus.get_object.return_value
    proxy.get_dbus_method.assert_called_with(
        "MarkConversationRead", "im.tincan.Messages"
    )
    method = proxy.get_dbus_method.return_value
    method.assert_called_once_with("conv-1")


# --- incapable: methods return empty / False ---

def test_list_conversations_returns_empty_when_incapable():
    m, _ = _msgs(capable=False)
    assert m.list_conversations() == []


def test_send_message_returns_false_when_incapable():
    m, _ = _msgs(capable=False)
    assert m.send_message("conv-1", "hi") is False


def test_get_messages_returns_empty_when_incapable():
    m, _ = _msgs(capable=False)
    assert m.get_messages("conv-1") == []


def test_get_contacts_returns_empty_when_incapable():
    m, _ = _msgs(capable=False)
    assert m.get_contacts() == []


# --- dbus error path ---

def test_method_emits_error_event_on_dbus_failure():
    m, events = _msgs()
    m._bus.get_object.return_value.get_dbus_method.return_value.side_effect = (
        RuntimeError("no service")
    )
    m.list_conversations()
    kinds = {e[0] for e in events}
    assert "messages_error" in kinds


# --- no bus injected ---

def test_methods_noop_without_bus():
    events: list = []
    m = TincanMessages(emit=events.append, _bus=None)
    m._capable = True  # force capable=True; proxy() still returns None (no bus)
    assert m.list_conversations() == []
    assert m.send_message("conv-1", "hi") is False
    assert events == []


# --- start with missing dbus ---

def test_start_emits_bus_unavailable_when_dbus_missing():
    events: list = []
    m = TincanMessages(emit=events.append)
    with patch.dict("sys.modules", {"dbus": None, "dbus.mainloop.glib": None}):
        m.start()
    kinds = {e[0] for e in events}
    assert "bus_unavailable" in kinds


# --- capability check ---

def test_check_capability_returns_true_when_daemon_reports_messages():
    m, _ = _msgs(capable=False)
    m._bus.get_object.return_value.get_dbus_method.return_value.return_value = {
        "capabilities": {"messages": True, "calls": True}
    }
    assert m._check_capability() is True


def test_check_capability_returns_false_when_messages_absent():
    m, _ = _msgs(capable=False)
    m._bus.get_object.return_value.get_dbus_method.return_value.return_value = {
        "capabilities": {"calls": True}
    }
    assert m._check_capability() is False


def test_start_emits_messages_unavailable_when_not_capable():
    events: list = []
    mock_bus = MagicMock()
    # Daemon GetStatus returns no messages capability
    mock_bus.get_object.return_value.get_dbus_method.return_value.return_value = {
        "capabilities": {}
    }

    import dbus as _dbus_real
    import dbus.mainloop.glib as _dbus_ml

    with (
        patch("iris.tincan_messages.TincanMessages._check_capability", return_value=False),
        patch("dbus.mainloop.glib.DBusGMainLoop"),
        patch("dbus.SessionBus", return_value=mock_bus),
    ):
        m = TincanMessages(emit=events.append)
        try:
            m.start()
        except Exception:
            pass

    kinds = {e[0] for e in events}
    assert "messages_unavailable" in kinds
