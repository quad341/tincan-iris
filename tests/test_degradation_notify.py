"""Tests for degradation_notify — edge-triggered desktop notify on baseline
transitions (ti-buyq8 / ti-ngtmb, from:ti-pugo3.2).

Module-level globals (_notify_sink, _last_level, _last_red_notify_ts) drive
the edge-detection state machine and are reset before/after every test.

test_on_baseline_transition_noop_when_sink_never_configured currently FAILS
against shipped code: _notify_degraded/_notify_recovered call
_notify_sink.notify(...) with no None-guard, so on_baseline_transition raises
AttributeError if init() was never called -- contradicting the no-op
contract both source beads require. Written to match the spec, not the bug;
the fix belongs in degradation_notify.py.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from iris.daemon import degradation_notify
from iris.daemon.heartbeat import BaselineStatus
from iris.doctor import AssetCheckResult, DoctorStatus
from iris.notify_sink import DesktopNotifySink


@pytest.fixture(autouse=True)
def _reset_state():
    degradation_notify._notify_sink = None
    degradation_notify._last_level = None
    degradation_notify._last_red_notify_ts = None
    yield
    degradation_notify._notify_sink = None
    degradation_notify._last_level = None
    degradation_notify._last_red_notify_ts = None


@pytest.fixture
def sink():
    mock = MagicMock(spec=DesktopNotifySink)
    degradation_notify.init(mock)
    return mock


def _status(level, checks=None, checked_at=0.0):
    return BaselineStatus(level=level, checks=list(checks or []), checked_at=checked_at)


def _check(name="svc", status=DoctorStatus.DOWN, required=True, detail="", fix=""):
    return AssetCheckResult(name=name, status=status, required=required, detail=detail, fix=fix)


def _fake_time(t):
    return patch("iris.daemon.degradation_notify.time.time", return_value=t)


# ---------------------------------------------------------------------------
# green / cold-start -> non-green
# ---------------------------------------------------------------------------

def test_cold_start_green_is_silent(sink):
    degradation_notify.on_baseline_transition(_status("green"), None)
    sink.notify.assert_not_called()


def test_cold_start_yellow_notifies_once(sink):
    degradation_notify.on_baseline_transition(_status("yellow"), None)
    sink.notify.assert_called_once()


def test_cold_start_red_notifies_and_stamps_red_ts(sink):
    with _fake_time(1000.0):
        degradation_notify.on_baseline_transition(_status("red"), None)
    sink.notify.assert_called_once()
    assert degradation_notify._last_red_notify_ts == 1000.0


def test_cold_start_yellow_does_not_stamp_red_ts(sink):
    degradation_notify.on_baseline_transition(_status("yellow"), None)
    assert degradation_notify._last_red_notify_ts is None


def test_green_to_yellow_notifies_once(sink):
    degradation_notify.on_baseline_transition(_status("green"), None)
    degradation_notify.on_baseline_transition(_status("yellow"), None)
    sink.notify.assert_called_once()


def test_green_to_red_notifies_and_stamps_ts(sink):
    degradation_notify.on_baseline_transition(_status("green"), None)
    with _fake_time(500.0):
        degradation_notify.on_baseline_transition(_status("red"), None)
    sink.notify.assert_called_once()
    assert degradation_notify._last_red_notify_ts == 500.0


# ---------------------------------------------------------------------------
# non-green -> green (recovery)
# ---------------------------------------------------------------------------

def test_yellow_to_green_notifies_recovered_once(sink):
    degradation_notify.on_baseline_transition(_status("yellow"), None)
    sink.notify.reset_mock()
    degradation_notify.on_baseline_transition(_status("green"), None)
    sink.notify.assert_called_once()
    title = sink.notify.call_args[0][0]
    assert "back to green" in title.lower()


def test_red_to_green_clears_red_notify_ts(sink):
    with _fake_time(100.0):
        degradation_notify.on_baseline_transition(_status("red"), None)
    assert degradation_notify._last_red_notify_ts is not None
    degradation_notify.on_baseline_transition(_status("green"), None)
    assert degradation_notify._last_red_notify_ts is None


def test_recovered_notify_urgency_is_normal(sink):
    degradation_notify.on_baseline_transition(_status("red"), None)
    degradation_notify.on_baseline_transition(_status("green"), None)
    _args, kwargs = sink.notify.call_args
    assert kwargs.get("urgency") == "normal"


# ---------------------------------------------------------------------------
# red reminder interval (86400s, FR-2.2)
# ---------------------------------------------------------------------------

def test_red_reminder_silent_within_interval(sink):
    with _fake_time(0.0):
        degradation_notify.on_baseline_transition(_status("red"), None)
    with _fake_time(86399.0):
        degradation_notify.on_baseline_transition(_status("red"), None)
    sink.notify.assert_called_once()


def test_red_reminder_fires_at_interval_boundary(sink):
    with _fake_time(0.0):
        degradation_notify.on_baseline_transition(_status("red"), None)
    with _fake_time(86400.0):
        degradation_notify.on_baseline_transition(_status("red"), None)
    assert sink.notify.call_count == 2
    title = sink.notify.call_args[0][0]
    assert "reminder" in title.lower()


def test_red_reminder_fires_after_interval(sink):
    with _fake_time(0.0):
        degradation_notify.on_baseline_transition(_status("red"), None)
    with _fake_time(90000.0):
        degradation_notify.on_baseline_transition(_status("red"), None)
    assert sink.notify.call_count == 2


def test_red_reminder_restamps_ts_so_next_tick_stays_silent(sink):
    with _fake_time(0.0):
        degradation_notify.on_baseline_transition(_status("red"), None)
    with _fake_time(86400.0):
        degradation_notify.on_baseline_transition(_status("red"), None)
    with _fake_time(86400.0 + 1.0):
        degradation_notify.on_baseline_transition(_status("red"), None)
    assert sink.notify.call_count == 2


# ---------------------------------------------------------------------------
# steady state (non-red) is fully silent
# ---------------------------------------------------------------------------

def test_green_to_green_is_silent(sink):
    degradation_notify.on_baseline_transition(_status("green"), None)
    degradation_notify.on_baseline_transition(_status("green"), None)
    sink.notify.assert_not_called()


def test_yellow_to_yellow_is_silent_after_initial_notify(sink):
    degradation_notify.on_baseline_transition(_status("yellow"), None)
    sink.notify.reset_mock()
    degradation_notify.on_baseline_transition(_status("yellow"), None)
    sink.notify.assert_not_called()


# ---------------------------------------------------------------------------
# _notify_degraded body construction
# ---------------------------------------------------------------------------

def test_body_uses_detail_when_present(sink):
    checks = [_check(name="tincand", status=DoctorStatus.DOWN, detail="device_address wiped")]
    degradation_notify.on_baseline_transition(_status("red", checks), None)
    body = sink.notify.call_args[0][1]
    assert "tincand: device_address wiped" in body


def test_body_falls_back_to_status_value_when_detail_empty(sink):
    checks = [_check(name="tincand", status=DoctorStatus.DOWN, detail="")]
    degradation_notify.on_baseline_transition(_status("red", checks), None)
    body = sink.notify.call_args[0][1]
    assert "tincand: down" in body


def test_body_appends_fix_suffix_when_present(sink):
    checks = [_check(name="tincand", status=DoctorStatus.DOWN, detail="wiped", fix="restart bluetooth")]
    degradation_notify.on_baseline_transition(_status("red", checks), None)
    body = sink.notify.call_args[0][1]
    assert "wiped — restart bluetooth" in body


def test_body_omits_fix_suffix_when_absent(sink):
    checks = [_check(name="tincand", status=DoctorStatus.DOWN, detail="wiped", fix="")]
    degradation_notify.on_baseline_transition(_status("red", checks), None)
    body = sink.notify.call_args[0][1]
    assert "—" not in body


def test_body_excludes_non_required_failing_checks(sink):
    checks = [
        _check(name="required-down", status=DoctorStatus.DOWN, required=True, detail="r"),
        _check(name="optional-down", status=DoctorStatus.DOWN, required=False, detail="o"),
    ]
    degradation_notify.on_baseline_transition(_status("red", checks), None)
    body = sink.notify.call_args[0][1]
    assert "required-down" in body
    assert "optional-down" not in body


def test_body_excludes_ok_checks(sink):
    checks = [
        _check(name="passing", status=DoctorStatus.OK, required=True, detail="fine"),
        _check(name="failing", status=DoctorStatus.DEGRADED, required=True, detail="slow"),
    ]
    degradation_notify.on_baseline_transition(_status("yellow", checks), None)
    body = sink.notify.call_args[0][1]
    assert "passing" not in body
    assert "failing" in body


def test_body_joins_multiple_failing_checks(sink):
    checks = [
        _check(name="first", status=DoctorStatus.DOWN, detail="a"),
        _check(name="second", status=DoctorStatus.DOWN, detail="b"),
    ]
    degradation_notify.on_baseline_transition(_status("red", checks), None)
    body = sink.notify.call_args[0][1]
    assert body == "first: a; second: b"


# ---------------------------------------------------------------------------
# urgency mapping
# ---------------------------------------------------------------------------

def test_yellow_degraded_urgency_is_normal(sink):
    degradation_notify.on_baseline_transition(_status("yellow"), None)
    _args, kwargs = sink.notify.call_args
    assert kwargs.get("urgency") == "normal"


def test_red_degraded_urgency_is_critical(sink):
    degradation_notify.on_baseline_transition(_status("red"), None)
    _args, kwargs = sink.notify.call_args
    assert kwargs.get("urgency") == "critical"


def test_red_reminder_urgency_is_critical(sink):
    with _fake_time(0.0):
        degradation_notify.on_baseline_transition(_status("red"), None)
    with _fake_time(86400.0):
        degradation_notify.on_baseline_transition(_status("red"), None)
    _args, kwargs = sink.notify.call_args
    assert kwargs.get("urgency") == "critical"


# ---------------------------------------------------------------------------
# `previous` argument is intentionally ignored (module docstring: restart
# semantics fall out of tracking _last_level instead)
# ---------------------------------------------------------------------------

def test_previous_argument_is_ignored_in_favor_of_module_state(sink):
    degradation_notify.on_baseline_transition(_status("red"), None)
    sink.notify.reset_mock()
    contradicting_previous = _status("red")  # claims "was already red" -- must not matter
    degradation_notify.on_baseline_transition(_status("green"), contradicting_previous)
    sink.notify.assert_called_once()
    title = sink.notify.call_args[0][0]
    assert "back to green" in title.lower()


# ---------------------------------------------------------------------------
# notify_sink defaulting to None (init() never called) -- see module and
# bead-level "must not raise" requirement
# ---------------------------------------------------------------------------

def test_on_baseline_transition_noop_when_sink_never_configured():
    """EXPECTED TO FAIL against current code: _notify_degraded/_notify_recovered
    call _notify_sink.notify(...) with no None-guard, raising AttributeError
    instead of no-op'ing. Fix belongs in degradation_notify.py.
    """
    degradation_notify.on_baseline_transition(_status("red"), None)  # must not raise
