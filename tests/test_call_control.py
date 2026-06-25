"""Tests for TincanCallControl.

No D-Bus daemon, no real audio hardware: the mock bus is injected and signal
handlers are invoked directly so tests run in plain pytest (no GLib loop)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from iris.call_control import TincanCallControl


def _ctrl(*, auto_answer=False) -> tuple[TincanCallControl, list]:
    events: list = []
    mock_bus = MagicMock()
    c = TincanCallControl(
        auto_answer=auto_answer, emit=events.append, _bus=mock_bus,
        discover_tries=1, discover_delay=0,  # no retry sleeps in tests
    )
    return c, events


# --- signal handlers ---

def test_incoming_call_emits_event():
    c, events = _ctrl()
    c._on_incoming("Alice", "+15555550123")
    assert ("incoming_call", "Alice", "+15555550123") in events


def test_incoming_call_tolerates_extra_signal_args():
    # forward-compat: extra positional args from the bus are ignored
    c, events = _ctrl()
    c._on_incoming("Alice", "+15555550123", "unexpected")
    assert ("incoming_call", "Alice", "+15555550123") in events


def test_incoming_call_no_auto_answer_skips_answer():
    c, events = _ctrl(auto_answer=False)
    c._on_incoming("Alice", "+15555550123")
    proxy = c._bus.get_object.return_value
    proxy.get_dbus_method.assert_not_called()


def test_incoming_call_auto_answer_calls_answer():
    c, events = _ctrl(auto_answer=True)
    c._on_incoming("Alice", "+15555550123")
    proxy = c._bus.get_object.return_value
    proxy.get_dbus_method.assert_called_once_with("Answer", "im.tincan.Calls")


def test_call_connected_discovers_sco_and_creates_endpoint():
    c, events = _ctrl()
    with patch(
        "iris.call_control.discover_sco_nodes",
        return_value=("bluez_output.AA_BB.1", "bluez_input.AA_BB.0"),
    ):
        c._on_connected("call-1")
    assert c.endpoint is not None
    assert c.endpoint.playback_target == "bluez_output.AA_BB.1"
    assert c.endpoint.far_source == "bluez_input.AA_BB.0"
    assert ("call_connected", "bluez_output.AA_BB.1", "bluez_input.AA_BB.0") in events


def test_call_connected_no_sco_nodes_emits_none():
    c, events = _ctrl()
    with patch("iris.call_control.discover_sco_nodes", return_value=(None, None)):
        c._on_connected("call-1")
    assert c.endpoint is None
    assert ("call_connected", None, None) in events


def test_call_ended_drops_endpoint_and_emits():
    c, events = _ctrl()
    with patch("iris.call_control.discover_sco_nodes", return_value=("sink", "src")):
        c._on_connected("call-1")
    assert c.endpoint is not None
    c._on_ended("call-1")
    assert c.endpoint is None
    assert ("call_ended", "call-1") in events


def test_audio_error_emits_event():
    c, events = _ctrl()
    c._on_audio_error("call-1", "codec mismatch")
    assert ("audio_error", "call-1", "codec mismatch") in events


def test_audio_restored_emits_event():
    c, events = _ctrl()
    c._on_audio_restored("call-1")
    assert ("audio_restored", "call-1") in events


# --- answer helper ---

def test_answer_calls_dbus_method():
    c, events = _ctrl()
    c._answer("call-1")
    c._bus.get_object.assert_called_once_with("im.tincan.Daemon", "/im/tincan")
    proxy = c._bus.get_object.return_value
    proxy.get_dbus_method.assert_called_once_with("Answer", "im.tincan.Calls")
    method = proxy.get_dbus_method.return_value
    method.assert_called_once_with("call-1")


def test_answer_emits_error_on_dbus_failure():
    c, events = _ctrl()
    c._bus.get_object.side_effect = RuntimeError("no service")
    c._answer("call-1")
    assert ("answer_error", "call-1") in events


def test_answer_no_op_without_bus():
    events: list = []
    c = TincanCallControl(emit=events.append, _bus=None)
    c._answer("call-1")  # must not raise
    assert events == []


# --- start with missing dbus ---

def test_start_emits_bus_unavailable_when_dbus_missing():
    events: list = []
    c = TincanCallControl(emit=events.append)
    with patch.dict("sys.modules", {"dbus": None, "dbus.mainloop.glib": None}):
        c.start()
    kinds = {e[0] for e in events}
    assert "bus_unavailable" in kinds


# --- dial helper ---

def test_dial_calls_dbus_method():
    c, events = _ctrl()
    result = c.dial("+15555550199")
    c._bus.get_object.assert_called_once_with("im.tincan.Daemon", "/im/tincan")
    proxy = c._bus.get_object.return_value
    proxy.get_dbus_method.assert_called_once_with("Dial", "im.tincan.Calls")
    method = proxy.get_dbus_method.return_value
    method.assert_called_once_with("+15555550199")
    assert result is None


def test_dial_emits_error_and_returns_error_string():
    c, events = _ctrl()
    c._bus.get_object.side_effect = RuntimeError("no service")
    result = c.dial("+15555550199")
    assert ("dial_error", "+15555550199", "no service") in events
    assert result == "no service"


def test_dial_no_op_without_bus():
    events: list = []
    c = TincanCallControl(emit=events.append, _bus=None)
    result = c.dial("+15555550199")
    assert result is None
    assert events == []


# --- rebind on reconnect ---

def test_reconnect_replaces_endpoint():
    """A second CallConnected after a hangup rebinds a fresh endpoint (new SCO nodes)."""
    c, events = _ctrl()
    with patch("iris.call_control.discover_sco_nodes", return_value=("sink1", "src1")):
        c._on_connected("call-1")
    first_ep = c.endpoint
    c._on_ended("call-1")
    with patch("iris.call_control.discover_sco_nodes", return_value=("sink2", "src2")):
        c._on_connected("call-2")
    assert c.endpoint is not first_ep
    assert c.endpoint.playback_target == "sink2"


# --- ti-veyx: AEC gating + SCO discovery retry ---

def test_call_connected_enables_aec_when_iris_aec_set():
    c, events = _ctrl()
    with patch(
        "iris.call_control.discover_sco_nodes",
        return_value=("bluez_output.AA.1", "bluez_input.AA.0"),
    ), patch("iris.call_control.settings.get_bool", return_value=True):
        c._on_connected("call-1")
    assert c.endpoint is not None
    assert c.endpoint.aec is True


def test_call_connected_aec_off_by_default():
    c, events = _ctrl()
    with patch(
        "iris.call_control.discover_sco_nodes",
        return_value=("bluez_output.AA.1", "bluez_input.AA.0"),
    ), patch("iris.call_control.settings.get_bool", return_value=False):
        c._on_connected("call-1")
    assert c.endpoint is not None
    assert c.endpoint.aec is False


def test_call_connected_retries_until_sco_nodes_appear():
    """SCO nodes can lag the CallConnected signal — discovery retries first."""
    events: list = []
    c = TincanCallControl(
        emit=events.append, _bus=MagicMock(),
        discover_tries=4, discover_delay=0,
    )
    seq = [(None, None), (None, None), ("bluez_output.AA.1", "bluez_input.AA.0")]
    with patch("iris.call_control.discover_sco_nodes", side_effect=seq):
        c._on_connected("call-1")
    assert c.endpoint is not None
    assert c.endpoint.playback_target == "bluez_output.AA.1"
