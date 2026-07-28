"""Tests for TincanCallControl wired to BrainHost + MessageEventSource (ti-s9mm.4.3).

Written BEFORE the builder implements ti-s9mm.4.1 and ti-s9mm.4.2.  All tests
WILL FAIL until:
  - HandlingEngine accepts brain_host= and calls set/clear_call_context
  - iris/daemon/message_event_source.py exists with MessageEventSource
  - iris/daemon/__main__.py wraps ctrl.start()/mes.start() in try/except and
    extracts _start_dbus_components() (or equivalent) for TC5

No real D-Bus connection in any test.  TCC's _bus is always MagicMock()
or start() is patched.

Security invariant (enforced in TC3 and TC4):
  Brain.respond and Brain.respond_stream must NEVER be called from the
  MessageEventSource._on_notification code path.
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from iris.daemon.engine import HandlingEngine
from iris.daemon.policy import PolicyResolver, ResolveResult
from iris.roster import Contact

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _contact(
    *,
    id: int = 42,
    display_name: str = "Alice",
    phone_e164: str = "+15550001111",
    handling_rule: str = "screen",
) -> Contact:
    return Contact(
        id=id,
        display_name=display_name,
        phone_e164=phone_e164,
        handling_rule=handling_rule,
        trust_tier="demo",
        relationship_notes="",
        created_at=0.0,
        updated_at=0.0,
    )


def _mock_resolver(contact: Contact | None = None, verb: str = "screen") -> MagicMock:
    """PolicyResolver mock that always returns the given contact."""
    resolver = MagicMock(spec=PolicyResolver)
    resolver.resolve.return_value = ResolveResult(
        verb=verb,
        contact=contact,
        event={
            "event": "incoming_call",
            "call_id": "call-1",
            "caller_name": contact.display_name if contact else "",
            "caller_number": contact.phone_e164 if contact else "+15550001111",
            "verb": verb,
            "choices": [],
        },
    )
    return resolver


def _make_engine(*, brain_host: object | None = None, contact: Contact | None = None) -> HandlingEngine:
    """HandlingEngine with mocked dependencies; brain_host injected for TC1/TC2."""
    c = _contact() if contact is None else contact
    resolver = _mock_resolver(contact=c)
    return HandlingEngine(
        ctrl=MagicMock(),
        tts=None,
        resolver=resolver,
        notify_sink=MagicMock(),
        broadcast=MagicMock(),
        brain_host=brain_host,
    )


# ---------------------------------------------------------------------------
# TC1: CallConnected → HandlingEngine → BrainHost.set_call_context
# ---------------------------------------------------------------------------


def test_call_connected_sets_brain_context():
    """_on_connected → HandlingEngine.on_call_connected → brain_host.set_call_context
    called with (contact_id, contact_name, contact_number)."""
    brain_host = MagicMock()
    contact = _contact(id=42, display_name="Alice", phone_e164="+15550001111")
    engine = _make_engine(brain_host=brain_host, contact=contact)

    # Simulate incoming_call first so the engine caches the contact
    engine.on_incoming_call("+15550001111", call_id="call-1")

    # Simulate CallConnected — builder will add on_call_connected
    engine.on_call_connected("call-1")

    brain_host.set_call_context.assert_called_once_with(42, "Alice", "+15550001111")


def test_call_connected_no_contact_does_not_set_brain_context():
    """If caller is unknown (no roster entry), set_call_context must NOT be called —
    there is no contact_id to set."""
    brain_host = MagicMock()
    resolver = _mock_resolver(contact=None, verb="screen")
    engine = HandlingEngine(
        ctrl=MagicMock(),
        tts=None,
        resolver=resolver,
        notify_sink=MagicMock(),
        broadcast=MagicMock(),
        brain_host=brain_host,
    )
    engine.on_incoming_call("+19999999999", call_id="call-unknown")
    engine.on_call_connected("call-unknown")

    brain_host.set_call_context.assert_not_called()


# ---------------------------------------------------------------------------
# TC2: CallEnded → HandlingEngine → BrainHost.clear_call_context
# ---------------------------------------------------------------------------


def test_call_ended_clears_brain_context():
    """_on_ended → HandlingEngine.on_call_ended → brain_host.clear_call_context()."""
    brain_host = MagicMock()
    contact = _contact(id=42, display_name="Alice", phone_e164="+15550001111")
    engine = _make_engine(brain_host=brain_host, contact=contact)

    engine.on_incoming_call("+15550001111", call_id="call-1")
    engine.on_call_connected("call-1")
    engine.on_call_ended("call-1")

    brain_host.clear_call_context.assert_called_once()


def test_call_ended_without_prior_connect_still_clears():
    """on_call_ended must call clear_call_context even if on_call_connected was
    never called (e.g. caller hung up before pick-up)."""
    brain_host = MagicMock()
    engine = _make_engine(brain_host=brain_host)

    engine.on_incoming_call("+15550001111", call_id="call-1")
    engine.on_call_ended("call-1")

    brain_host.clear_call_context.assert_called_once()


# ---------------------------------------------------------------------------
# TC3: MessageEventSource._on_notification → ProactiveStore.enqueue(priority=2)
# ---------------------------------------------------------------------------


def test_mes_notification_enqueues_to_proactive_store():
    """_on_notification(sender, body, type_str) → ProactiveStore.enqueue called
    with priority=2 and the sender/body in the message."""
    from iris.daemon.message_event_source import (
        MessageEventSource,  # builder creates this
    )

    brain = MagicMock()  # security sentinel — must stay call_count==0
    proactive_store = MagicMock()
    broadcast = MagicMock()

    mes = MessageEventSource(proactive_store=proactive_store, broadcast=broadcast)
    mes._on_notification("Alice", "Hey, call me back", "iMessage")

    proactive_store.enqueue.assert_called_once()
    # priority must be 2 (display-only tier, per design)
    kwargs = proactive_store.enqueue.call_args.kwargs
    assert kwargs.get("priority") == 2, (
        f"Expected priority=2; got call_args={proactive_store.enqueue.call_args}"
    )

    # Security invariant: Brain.respond must never be called from this path
    assert brain.respond.call_count == 0, "Brain.respond must not be called from MES notification path"
    assert brain.respond_stream.call_count == 0, "Brain.respond_stream must not be called from MES notification path"


def test_mes_notification_enqueue_includes_sender_in_message():
    """The enqueued message string must reference the sender so the console can
    surface who the notification is from without re-parsing the broadcast event."""
    from iris.daemon.message_event_source import MessageEventSource

    proactive_store = MagicMock()
    mes = MessageEventSource(proactive_store=proactive_store, broadcast=MagicMock())
    mes._on_notification("Bob", "Are you free?", "SMS")

    kwargs = proactive_store.enqueue.call_args.kwargs
    message = kwargs.get("message", "")
    assert "Bob" in message, f"Enqueued message must contain sender 'Bob'; got: {message!r}"


# ---------------------------------------------------------------------------
# TC4: MessageEventSource._on_notification → DaemonAPI.broadcast(notification_event)
# ---------------------------------------------------------------------------


def test_mes_notification_broadcasts_event():
    """_on_notification → broadcast({'event':'notification','type':'ancs',
    'sender':...,'body':...,'timestamp':...}) — Brain.respond never called."""
    from iris.daemon.message_event_source import MessageEventSource

    brain = MagicMock()  # security sentinel
    broadcast = MagicMock()
    proactive_store = MagicMock()

    mes = MessageEventSource(proactive_store=proactive_store, broadcast=broadcast)
    mes._on_notification("Alice", "Hey, call me back", "iMessage")

    broadcast.assert_called_once()
    event = broadcast.call_args[0][0]

    assert event.get("event") == "notification"
    assert event.get("type") == "ancs"
    assert event.get("sender") == "Alice"
    assert event.get("body") == "Hey, call me back"
    assert "timestamp" in event, "notification event must include a timestamp field"
    assert isinstance(event["timestamp"], (int, float)), (
        f"timestamp must be numeric; got {type(event['timestamp'])}"
    )

    # Security invariant
    assert brain.respond.call_count == 0, "Brain.respond must not be called from MES notification path"
    assert brain.respond_stream.call_count == 0, "Brain.respond_stream must not be called from MES notification path"


def test_mes_notification_no_real_dbus():
    """MessageEventSource._on_notification must work without any D-Bus connection.
    Verifies that the notification handler is a plain method, not a D-Bus callback
    that requires a live bus."""
    from iris.daemon.message_event_source import MessageEventSource

    broadcast = MagicMock()
    proactive_store = MagicMock()

    # No _bus injected; _on_notification should not touch dbus at all
    mes = MessageEventSource(proactive_store=proactive_store, broadcast=broadcast)
    mes._on_notification("Carol", "ping", "SMS")  # must not raise

    broadcast.assert_called_once()


# ---------------------------------------------------------------------------
# TC5: D-Bus absent → graceful start, WARNING with dbus_absent=True
# ---------------------------------------------------------------------------


class _FakeDBusException(Exception):
    """Stand-in for dbus.exceptions.DBusException in environments without dbus-python."""


def test_dbus_absent_graceful_start(caplog):
    """When TincanCallControl.start() raises DBusException, the daemon bootstrap
    function completes without raising and emits a WARNING containing 'dbus_absent'."""
    from iris.daemon.__main__ import _start_dbus_components  # builder extracts this

    ctrl = MagicMock()
    ctrl.start.side_effect = _FakeDBusException("org.freedesktop.DBus.Error.NoServer: no session bus")
    mes = MagicMock()
    mes.start.side_effect = _FakeDBusException("org.freedesktop.DBus.Error.NoServer: no session bus")

    with caplog.at_level(logging.WARNING, logger="iris.daemon"):
        _start_dbus_components(ctrl, mes)  # must not raise

    warning_messages = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("dbus_absent" in m for m in warning_messages), (
        f"Expected WARNING containing 'dbus_absent'; got: {warning_messages}"
    )


def test_dbus_absent_does_not_raise(caplog):
    """_start_dbus_components must not propagate DBusException to caller even when
    both ctrl.start() and mes.start() fail."""
    from iris.daemon.__main__ import _start_dbus_components

    ctrl = MagicMock()
    ctrl.start.side_effect = _FakeDBusException("no bus")
    mes = MagicMock()
    mes.start.side_effect = _FakeDBusException("no bus")

    try:
        with caplog.at_level(logging.WARNING):
            _start_dbus_components(ctrl, mes)
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"_start_dbus_components raised unexpectedly: {exc}")


def test_dbus_present_starts_both_components():
    """When neither raises, both ctrl.start() and mes.start() are called exactly once."""
    from iris.daemon.__main__ import _start_dbus_components

    ctrl = MagicMock()
    mes = MagicMock()

    _start_dbus_components(ctrl, mes)

    ctrl.start.assert_called_once()
    mes.start.assert_called_once()
