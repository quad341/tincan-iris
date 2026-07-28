"""Tests for iris.daemon.heartbeat (ti-pugo3.1 / ti-hxqpz items 1-5).

Zero coverage existed for this module before this bead. Mirrors
tests/test_posture.py's Event-based (no sleep-based timing) style for the
BaselineHeartbeat threading tests, since BaselineHeartbeat's thread shape is a
deliberate copy of PostureWatcher's (iris/daemon/posture.py:187).

NFR-3 isolation tests patch the three pooled check functions on the
iris.daemon.heartbeat module object itself (not iris.doctor) -- _collect_checks
resolves those names from its own module globals at call time, so patching
iris.doctor's copies would have no effect here.
"""
from __future__ import annotations

import threading

import pytest

from iris.daemon import heartbeat as hb
from iris.daemon.heartbeat import (
    BaselineHeartbeat,
    BaselineStatus,
    _aggregate,
    _collect_checks,
    _daemon_socket_check,
    _service_to_asset,
)
from iris.doctor import AssetCheckResult, DoctorStatus, ServiceCheckResult


def _check(name, status, required, detail=""):
    return AssetCheckResult(name, status, required, detail=detail)


# ---------------------------------------------------------------------------
# _aggregate (item 2)
# ---------------------------------------------------------------------------


def test_aggregate_green_when_all_required_checks_ok():
    checks = [_check("a", DoctorStatus.OK, True), _check("b", DoctorStatus.OK, False)]
    assert _aggregate(checks) == "green"


def test_aggregate_green_when_no_checks_at_all():
    assert _aggregate([]) == "green"


@pytest.mark.parametrize("bad_status", [DoctorStatus.DOWN, DoctorStatus.ABSENT, DoctorStatus.UNKNOWN])
def test_aggregate_red_when_a_required_check_is_down_absent_or_unknown(bad_status):
    checks = [_check("a", DoctorStatus.OK, True), _check("b", bad_status, True)]
    assert _aggregate(checks) == "red"


def test_aggregate_yellow_when_a_required_check_is_degraded():
    checks = [_check("a", DoctorStatus.OK, True), _check("b", DoctorStatus.DEGRADED, True)]
    assert _aggregate(checks) == "yellow"


def test_aggregate_red_takes_priority_over_yellow():
    checks = [_check("a", DoctorStatus.DEGRADED, True), _check("b", DoctorStatus.DOWN, True)]
    assert _aggregate(checks) == "red"


@pytest.mark.parametrize(
    "bad_status", [DoctorStatus.DOWN, DoctorStatus.ABSENT, DoctorStatus.UNKNOWN, DoctorStatus.DEGRADED]
)
def test_aggregate_ignores_non_required_checks_regardless_of_status(bad_status):
    checks = [_check("a", DoctorStatus.OK, True), _check("optional", bad_status, False)]
    assert _aggregate(checks) == "green"


def test_aggregate_unknown_counts_as_red_here_unlike_cli_exit_code_convention():
    """Deliberate divergence from doctor.py's _asset_exit_code(), which never
    escalates on UNKNOWN (only DOWN/ABSENT -> 2, DEGRADED -> 1)."""
    checks = [_check("a", DoctorStatus.UNKNOWN, True)]
    assert _aggregate(checks) == "red"


# ---------------------------------------------------------------------------
# _service_to_asset (item 4)
# ---------------------------------------------------------------------------


def test_service_to_asset_maps_fields_and_has_no_fix_when_not_down():
    svc = ServiceCheckResult(name="tincand", unit="tincand.service", status=DoctorStatus.OK,
                              required=False, note="reachable")
    asset = _service_to_asset(svc)
    assert asset == AssetCheckResult("tincand", DoctorStatus.OK, False, detail="reachable", fix="")


def test_service_to_asset_populates_fix_when_down():
    svc = ServiceCheckResult(name="iris-whisper", unit="iris-whisper.service", status=DoctorStatus.DOWN,
                              required=True, note="connection refused")
    asset = _service_to_asset(svc)
    assert asset.fix == "journalctl --user -u iris-whisper.service -n 20"


def test_service_to_asset_fix_empty_for_degraded():
    svc = ServiceCheckResult(name="iris-kokoro", unit="iris-kokoro.service", status=DoctorStatus.DEGRADED,
                              required=True, note="slow")
    asset = _service_to_asset(svc)
    assert asset.fix == ""


# ---------------------------------------------------------------------------
# _daemon_socket_check (item 5)
# ---------------------------------------------------------------------------


def test_daemon_socket_check_ok_when_healthy():
    result = _daemon_socket_check(lambda: True)
    assert result == AssetCheckResult("daemon-socket", DoctorStatus.OK, True, detail="listening")


def test_daemon_socket_check_down_when_unhealthy():
    result = _daemon_socket_check(lambda: False)
    assert result.status == DoctorStatus.DOWN
    assert result.required is True
    assert "socket missing" in result.detail


def test_daemon_socket_check_unknown_on_exception():
    def _raise():
        raise RuntimeError("boom")

    result = _daemon_socket_check(_raise)
    assert result.status == DoctorStatus.UNKNOWN
    assert result.required is True
    assert "boom" in result.detail


# ---------------------------------------------------------------------------
# _collect_checks / NFR-3 (item 3)
# ---------------------------------------------------------------------------


def _patch_pooled(monkeypatch, *, caps=None, svcs=None, enrich=None):
    if caps is not None:
        monkeypatch.setattr(hb, "check_baseline_capabilities", caps)
    if svcs is not None:
        monkeypatch.setattr(hb, "check_services", svcs)
    if enrich is not None:
        monkeypatch.setattr(hb, "check_call_card_enrichment", enrich)


def test_collect_checks_filters_expected_services_to_heartbeat_set(monkeypatch):
    seen_names = []

    def _fake_check_services(services, *, timeout_s, deep):
        seen_names.extend(s.name for s in services)
        return []

    _patch_pooled(
        monkeypatch,
        caps=list,
        svcs=_fake_check_services,
        enrich=lambda *, timeout_s: _check("call-card-enrichment", DoctorStatus.OK, False),
    )
    _collect_checks(lambda: True)

    assert set(seen_names) == {"iris-whisper", "iris-kokoro", "tincand"}
    assert "iris-llama" not in seen_names


def test_collect_checks_baseline_capabilities_exception_degrades_to_unknown_without_blocking_others(monkeypatch):
    def _raise_caps():
        raise RuntimeError("dbus exploded")

    _patch_pooled(
        monkeypatch,
        caps=_raise_caps,
        svcs=lambda services, *, timeout_s, deep: [
            ServiceCheckResult(name="tincand", unit="tincand.service", status=DoctorStatus.OK, required=False)
        ],
        enrich=lambda *, timeout_s: _check("call-card-enrichment", DoctorStatus.OK, False),
    )
    checks = _collect_checks(lambda: True)
    by_name = {c.name: c for c in checks}

    assert by_name["baseline-capabilities"].status == DoctorStatus.UNKNOWN
    assert by_name["baseline-capabilities"].required is True
    assert "dbus exploded" in by_name["baseline-capabilities"].detail
    assert by_name["tincand"].status == DoctorStatus.OK
    assert by_name["call-card-enrichment"].status == DoctorStatus.OK
    assert by_name["daemon-socket"].status == DoctorStatus.OK


def test_collect_checks_services_exception_degrades_to_unknown_without_blocking_others(monkeypatch):
    def _raise_svcs(services, *, timeout_s, deep):
        raise RuntimeError("systemctl exploded")

    _patch_pooled(
        monkeypatch,
        caps=lambda: [_check("tincand-connected", DoctorStatus.OK, True)],
        svcs=_raise_svcs,
        enrich=lambda *, timeout_s: _check("call-card-enrichment", DoctorStatus.OK, False),
    )
    checks = _collect_checks(lambda: True)
    by_name = {c.name: c for c in checks}

    assert by_name["services"].status == DoctorStatus.UNKNOWN
    assert by_name["services"].required is True
    assert "systemctl exploded" in by_name["services"].detail
    assert by_name["tincand-connected"].status == DoctorStatus.OK
    assert by_name["call-card-enrichment"].status == DoctorStatus.OK
    assert by_name["daemon-socket"].status == DoctorStatus.OK


def test_collect_checks_enrichment_exception_degrades_to_unknown_without_blocking_others(monkeypatch):
    def _raise_enrich(*, timeout_s):
        raise RuntimeError("subprocess exploded")

    _patch_pooled(
        monkeypatch,
        caps=lambda: [_check("tincand-connected", DoctorStatus.OK, True)],
        svcs=lambda services, *, timeout_s, deep: [
            ServiceCheckResult(name="tincand", unit="tincand.service", status=DoctorStatus.OK, required=False)
        ],
        enrich=_raise_enrich,
    )
    checks = _collect_checks(lambda: True)
    by_name = {c.name: c for c in checks}

    assert by_name["call-card-enrichment"].status == DoctorStatus.UNKNOWN
    assert by_name["call-card-enrichment"].required is False
    assert "subprocess exploded" in by_name["call-card-enrichment"].detail
    assert by_name["tincand-connected"].status == DoctorStatus.OK
    assert by_name["tincand"].status == DoctorStatus.OK
    assert by_name["daemon-socket"].status == DoctorStatus.OK


def test_collect_checks_daemon_socket_check_always_runs_even_when_all_three_pooled_checks_raise(monkeypatch):
    def _raise(*a, **kw):
        raise RuntimeError("everything is on fire")

    _patch_pooled(monkeypatch, caps=_raise, svcs=_raise, enrich=_raise)
    checks = _collect_checks(lambda: True)
    by_name = {c.name: c for c in checks}

    assert by_name["daemon-socket"].status == DoctorStatus.OK
    assert by_name["baseline-capabilities"].status == DoctorStatus.UNKNOWN
    assert by_name["services"].status == DoctorStatus.UNKNOWN
    assert by_name["call-card-enrichment"].status == DoctorStatus.UNKNOWN


# ---------------------------------------------------------------------------
# BaselineHeartbeat.start/stop/latest (item 1)
# ---------------------------------------------------------------------------


@pytest.fixture
def no_op_checks(monkeypatch):
    """Keep _collect_checks fast/hermetic for the threading tests below --
    those tests care about start/stop/latest timing, not check content."""
    monkeypatch.setattr(hb, "_HEARTBEAT_INTERVAL_S", 0.05)
    _patch_pooled(
        monkeypatch,
        caps=list,
        svcs=lambda services, *, timeout_s, deep: [],
        enrich=lambda *, timeout_s: _check("call-card-enrichment", DoctorStatus.OK, False),
    )


def test_latest_is_none_before_start(no_op_checks):
    beat = BaselineHeartbeat(is_daemon_socket_healthy=lambda: True)
    assert beat.latest() is None


def test_start_populates_latest_synchronously_before_background_thread_runs(no_op_checks, monkeypatch):
    """start()'s first _run_once() call must happen inline -- don't leave
    /status empty for the first 90s. Interval is pinned huge so any populated
    latest() provably came from the synchronous call, not the background loop."""
    monkeypatch.setattr(hb, "_HEARTBEAT_INTERVAL_S", 999.0)
    beat = BaselineHeartbeat(is_daemon_socket_healthy=lambda: True)
    try:
        beat.start()
        status = beat.latest()
        assert status is not None
        assert isinstance(status, BaselineStatus)
        assert status.level == "green"
    finally:
        beat.stop()


def test_stop_sets_the_event_and_does_not_block_or_join(no_op_checks):
    beat = BaselineHeartbeat(is_daemon_socket_healthy=lambda: True)
    beat.start()

    beat.stop()  # must return immediately -- no join() on the background thread

    assert beat._stop.is_set()


def test_background_thread_updates_latest_after_interval_elapses(no_op_checks, monkeypatch):
    tick_count = threading.Event()
    calls = []
    real_run_once = BaselineHeartbeat._run_once

    def _counting_run_once(self):
        real_run_once(self)
        calls.append(1)
        if len(calls) >= 2:
            tick_count.set()

    monkeypatch.setattr(BaselineHeartbeat, "_run_once", _counting_run_once)
    beat = BaselineHeartbeat(is_daemon_socket_healthy=lambda: True)
    try:
        beat.start()
        assert tick_count.wait(timeout=2), "background thread did not tick a second time in time"
    finally:
        beat.stop()

    assert len(calls) >= 2


def test_thread_is_a_daemon_thread_named_baseline_heartbeat(no_op_checks):
    beat = BaselineHeartbeat(is_daemon_socket_healthy=lambda: True)
    assert beat._thread.daemon is True
    assert beat._thread.name == "baseline-heartbeat"


def test_on_transition_called_with_new_status_and_none_previous_on_first_tick(no_op_checks, monkeypatch):
    monkeypatch.setattr(hb, "_HEARTBEAT_INTERVAL_S", 999.0)
    transitions = []
    beat = BaselineHeartbeat(
        is_daemon_socket_healthy=lambda: True,
        on_transition=lambda new, prev: transitions.append((new, prev)),
    )
    try:
        beat.start()
        assert len(transitions) == 1
        new, prev = transitions[0]
        assert prev is None
        assert new is beat.latest()
    finally:
        beat.stop()
