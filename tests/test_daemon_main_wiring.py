"""Tests for iris.daemon.__main__'s construction/start/stop wiring around
BaselineHeartbeat (ti-pugo3.1 / ti-hxqpz item 14): heartbeat is constructed
after api, api.set_heartbeat() runs before any daemon I/O starts, heartbeat
starts after api (so its first tick's is_healthy() reading isn't a false
negative), and heartbeat stops before watcher in the shutdown path.

main() is a long, linear, side-effecting function -- the same shape
tests/test_daemon_call_card_config.py's own end-to-end main() test already
exercises (patch one downstream construction to raise, inspect what ran
before it). That existing test proves RosterStore/PostureManager/NotesStore/
PreferencesStore/TincanCallControl/Brain/PolicyResolver/DesktopNotifySink/
HandlingEngine are all safe to construct for real in a test (none of them do
I/O at __init__ -- verified directly for the store classes, and the existing
test already constructs a real TincanCallControl this way today without
starting it).

This bead's invariants are about *order*, not the CallCardHost value-passing
the existing test covers, so instead of one raising fake this patches every
object whose start()/stop()/__init__() the bead's wiring description names,
as a MagicMock -- so incidental attribute access several calls deep (e.g.
Brain() -> optional_skills() -> DialVoiceSkills(ctrl, roster).skills()) can't
fail on a missing attribute the way a hand-rolled fake could. The
BaselineHeartbeat fake raises _StopEarly from .start(), the last call in
main()'s try block before the blocking stop_event.wait(), so main() unwinds
straight into its finally block in one pass.

Also patched, to avoid side effects the existing test currently tolerates as
known flakiness rather than deliberately relying on: _acquire_exclusive_lock
(the existing test takes a REAL flock on the real per-user pid file -- this is
exactly the file implicated in this bead's own noted pre-existing/
environmental failure, where a real iris.daemon happens to already be running
on the dev machine and holds that lock) and signal.signal (installing real
SIGTERM/SIGINT handlers on the pytest process itself would otherwise leak
across tests). DaemonAPI is faked rather than left real because main() never
passes socket_path= -- a real instance would bind the production Unix socket.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from iris.daemon import __main__ as daemon_main


class _StopEarly(Exception):
    """Raised from the fake BaselineHeartbeat.start() to unwind main() into its
    finally block without ever reaching the blocking stop_event.wait()."""


def _tracking_mock(call_order: list, label: str) -> MagicMock:
    m = MagicMock(name=label)
    call_order.append(f"{label}.__init__")
    m.start.side_effect = lambda: call_order.append(f"{label}.start")
    m.stop.side_effect = lambda: call_order.append(f"{label}.stop")
    return m


def _make_api(call_order: list) -> MagicMock:
    api = _tracking_mock(call_order, "api")
    api.set_heartbeat.side_effect = lambda hb: call_order.append("api.set_heartbeat")
    return api


def _make_heartbeat(call_order: list) -> MagicMock:
    heartbeat = _tracking_mock(call_order, "heartbeat")

    def _start_and_raise():
        call_order.append("heartbeat.start")
        raise _StopEarly()

    heartbeat.start.side_effect = _start_and_raise
    return heartbeat


@pytest.fixture
def call_order(monkeypatch, tmp_path):
    order: list[str] = []

    monkeypatch.setenv("IRIS_DB", str(tmp_path / "test.db"))
    monkeypatch.setenv("IRIS_CALL_CARD", "0")  # out of scope for item 14; own coverage in test_daemon_call_card_config.py
    monkeypatch.setenv("IRIS_AEC", "0")  # avoid spawning the real aec_audio.sh background thread

    monkeypatch.setattr(daemon_main, "DaemonAPI", lambda **kw: _make_api(order))
    monkeypatch.setattr(daemon_main, "BaselineHeartbeat", lambda **kw: _make_heartbeat(order))
    monkeypatch.setattr(daemon_main, "PostureWatcher", lambda posture: _tracking_mock(order, "watcher"))
    monkeypatch.setattr(daemon_main, "TincanCallControl", lambda **kw: _tracking_mock(order, "ctrl"))
    monkeypatch.setattr(daemon_main, "MessageEventSource", lambda **kw: _tracking_mock(order, "mes"))
    monkeypatch.setattr(daemon_main, "_acquire_exclusive_lock", lambda path: object())
    monkeypatch.setattr(daemon_main, "_remove_pid", lambda path: order.append("_remove_pid"))
    monkeypatch.setattr(daemon_main.signal, "signal", lambda *a, **kw: None)

    return order


@pytest.fixture
def run_main(call_order):
    with pytest.raises(_StopEarly):
        daemon_main.main()
    return call_order


# ---------------------------------------------------------------------------
# Construction order
# ---------------------------------------------------------------------------

def test_api_constructed_before_heartbeat(run_main):
    assert run_main.index("api.__init__") < run_main.index("heartbeat.__init__")


def test_set_heartbeat_called_before_any_daemon_io_starts(run_main):
    set_hb = run_main.index("api.set_heartbeat")
    starts = [i for i, call in enumerate(run_main) if call.endswith(".start")]
    assert starts, "no .start() calls were recorded"
    assert set_hb < min(starts)


# ---------------------------------------------------------------------------
# Start order
# ---------------------------------------------------------------------------

def test_start_order_is_watcher_then_api_then_heartbeat(run_main):
    assert (
        run_main.index("watcher.start")
        < run_main.index("api.start")
        < run_main.index("heartbeat.start")
    )


# ---------------------------------------------------------------------------
# Stop order (finally block, despite heartbeat.start() raising)
# ---------------------------------------------------------------------------

def test_heartbeat_stops_before_watcher_in_finally_block(run_main):
    assert run_main.index("heartbeat.stop") < run_main.index("watcher.stop")


def test_all_stop_calls_and_pid_removal_run_despite_the_start_exception(run_main):
    for label in ("mes.stop", "ctrl.stop", "api.stop", "heartbeat.stop", "watcher.stop", "_remove_pid"):
        assert label in run_main, f"{label} did not run"
