"""Tests for the new baseline-capabilities doctor.py checks (ti-pugo3.1 /
ti-hxqpz items 6-9): check_baseline_capabilities, _check_ambient_aec,
_tincand_unit_active, _retrying.

Consumed by iris/daemon/heartbeat.py's periodic aggregation (see
tests/test_heartbeat.py) but exercised directly here at the doctor.py layer,
mirroring check_assets()'s existing test shape in tests/test_doctor.py /
tests/test_doctor_assets.py. No autouse isolation fixture is needed (unlike
test_doctor.py's _isolate_assets) since none of these functions call
check_assets() or urllib.
"""
from __future__ import annotations

import subprocess

import pytest

from iris import doctor as doc
from iris.audio.endpoint import AEC_SINK, AEC_SRC
from iris.doctor import AssetCheckResult, DoctorStatus

# ---------------------------------------------------------------------------
# _tincand_unit_active (item 8)
# ---------------------------------------------------------------------------


def test_tincand_unit_active_true_on_zero_exit_code(monkeypatch):
    monkeypatch.setattr(
        doc.subprocess, "run",
        lambda *a, **kw: subprocess.CompletedProcess(a[0] if a else [], 0, stdout="active\n"),
    )
    assert doc._tincand_unit_active() is True


def test_tincand_unit_active_false_on_nonzero_exit_code(monkeypatch):
    monkeypatch.setattr(
        doc.subprocess, "run",
        lambda *a, **kw: subprocess.CompletedProcess(a[0] if a else [], 3, stdout="inactive\n"),
    )
    assert doc._tincand_unit_active() is False


def test_tincand_unit_active_false_when_systemctl_binary_missing(monkeypatch):
    def _raise(*a, **kw):
        raise OSError("systemctl not found")

    monkeypatch.setattr(doc.subprocess, "run", _raise)
    assert doc._tincand_unit_active() is False


# ---------------------------------------------------------------------------
# _retrying (item 9)
# ---------------------------------------------------------------------------


def test_retrying_returns_result_immediately_on_success():
    calls = []

    def fn():
        calls.append(1)
        return "ok"

    assert doc._retrying(fn) == "ok"
    assert len(calls) == 1


def test_retrying_retries_up_to_the_configured_limit_then_reraises(monkeypatch):
    monkeypatch.setattr(doc.time, "sleep", lambda s: None)
    calls = []

    def fn():
        calls.append(1)
        raise ValueError(f"attempt {len(calls)}")

    with pytest.raises(ValueError, match="attempt 3"):
        doc._retrying(fn)

    assert len(calls) == doc._BASELINE_DBUS_RETRIES + 1


def test_retrying_succeeds_after_a_transient_failure(monkeypatch):
    monkeypatch.setattr(doc.time, "sleep", lambda s: None)
    calls = []

    def fn():
        calls.append(1)
        if len(calls) < 2:
            raise ValueError("transient")
        return "recovered"

    assert doc._retrying(fn) == "recovered"
    assert len(calls) == 2


def test_retrying_sleeps_between_attempts_but_not_after_the_last_one(monkeypatch):
    sleeps = []
    monkeypatch.setattr(doc.time, "sleep", lambda s: sleeps.append(s))

    def fn():
        raise RuntimeError("always fails")

    with pytest.raises(RuntimeError):
        doc._retrying(fn)

    assert sleeps == [doc._BASELINE_DBUS_RETRY_DELAY_S] * doc._BASELINE_DBUS_RETRIES


# ---------------------------------------------------------------------------
# _check_ambient_aec (item 7)
# ---------------------------------------------------------------------------


def _pactl_result(stdout: str) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(["pactl"], 0, stdout=stdout)


def test_check_ambient_aec_ok_when_sink_and_source_match(monkeypatch):
    outputs = iter([_pactl_result(AEC_SINK + "\n"), _pactl_result(AEC_SRC + "\n")])
    monkeypatch.setattr(doc.subprocess, "run", lambda *a, **kw: next(outputs))

    result = doc._check_ambient_aec()

    assert result.name == "ambient-aec-default"
    assert result.status == DoctorStatus.OK
    assert result.required is True
    assert AEC_SINK in result.detail and AEC_SRC in result.detail


def test_check_ambient_aec_down_on_mismatch_and_detail_includes_both_actual_values(monkeypatch):
    outputs = iter([_pactl_result("some-other-sink\n"), _pactl_result(AEC_SRC + "\n")])
    monkeypatch.setattr(doc.subprocess, "run", lambda *a, **kw: next(outputs))

    result = doc._check_ambient_aec()

    assert result.status == DoctorStatus.DOWN
    assert result.required is True
    assert "some-other-sink" in result.detail
    assert AEC_SRC in result.detail
    assert result.fix


def test_check_ambient_aec_unknown_on_oserror(monkeypatch):
    def _raise(*a, **kw):
        raise OSError("pactl not found")

    monkeypatch.setattr(doc.subprocess, "run", _raise)
    result = doc._check_ambient_aec()
    assert result.status == DoctorStatus.UNKNOWN
    assert result.required is True
    assert "pactl not found" in result.detail


def test_check_ambient_aec_unknown_on_timeout(monkeypatch):
    def _raise(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="pactl", timeout=2)

    monkeypatch.setattr(doc.subprocess, "run", _raise)
    result = doc._check_ambient_aec()
    assert result.status == DoctorStatus.UNKNOWN


# ---------------------------------------------------------------------------
# check_baseline_capabilities (item 6)
# ---------------------------------------------------------------------------


@pytest.fixture
def no_ambient_aec_issues(monkeypatch):
    """Isolate check_baseline_capabilities's tincand-status branch logic from
    _check_ambient_aec's own pactl-dependent behavior, which is covered
    separately above -- both branches call it unconditionally (FR-1.2)."""
    ok = AssetCheckResult("ambient-aec-default", DoctorStatus.OK, True, detail=f"{AEC_SINK} / {AEC_SRC}")
    monkeypatch.setattr(doc, "_check_ambient_aec", lambda: ok)
    return ok


def _active_tincand(monkeypatch, *, connected=True, call_setup_ready=True, messages=True):
    monkeypatch.setattr(doc, "_tincand_unit_active", lambda: True)
    monkeypatch.setattr(doc, "_retrying", lambda fn: fn())
    monkeypatch.setattr(doc, "get_tincand_status", lambda: {
        "connected": connected,
        "call_setup_ready": call_setup_ready,
        "capabilities": {"messages": messages},
    })


def test_baseline_capabilities_tincand_inactive_all_four_checks_absent_not_required(monkeypatch, no_ambient_aec_issues):
    monkeypatch.setattr(doc, "_tincand_unit_active", lambda: False)
    results = doc.check_baseline_capabilities()
    by_name = {r.name: r for r in results}

    for name in ("tincand-connected", "call-setup-ready", "messages-capability", "call-audio-aec"):
        assert by_name[name].status == DoctorStatus.ABSENT
        assert by_name[name].required is False

    assert by_name["ambient-aec-default"] is no_ambient_aec_issues


def test_baseline_capabilities_tincand_inactive_check_names_match_the_active_branch(monkeypatch, no_ambient_aec_issues):
    """Deliberate builder judgment call: check *names* stay identical across
    both branches (no collapsed placeholder name) so a console/API consumer
    keying by name never sees the check-name set change shape at runtime."""
    monkeypatch.setattr(doc, "_tincand_unit_active", lambda: False)
    inactive_names = {r.name for r in doc.check_baseline_capabilities()}

    _active_tincand(monkeypatch)
    active_names = {r.name for r in doc.check_baseline_capabilities()}

    assert inactive_names == active_names


def test_baseline_capabilities_tincand_active_connected_and_call_setup_ready_reflect_status(monkeypatch, no_ambient_aec_issues):
    _active_tincand(monkeypatch, connected=True, call_setup_ready=True)
    by_name = {r.name: r for r in doc.check_baseline_capabilities()}

    assert by_name["tincand-connected"].status == DoctorStatus.OK
    assert by_name["tincand-connected"].required is True
    assert by_name["call-setup-ready"].status == DoctorStatus.OK
    assert by_name["call-setup-ready"].required is True


def test_baseline_capabilities_tincand_active_but_disconnected_and_setup_not_ready(monkeypatch, no_ambient_aec_issues):
    _active_tincand(monkeypatch, connected=False, call_setup_ready=False)
    by_name = {r.name: r for r in doc.check_baseline_capabilities()}

    assert by_name["tincand-connected"].status == DoctorStatus.DOWN
    assert by_name["call-setup-ready"].status == DoctorStatus.DOWN


def test_baseline_capabilities_messages_capability_required_false_and_degraded_when_absent(monkeypatch, no_ambient_aec_issues):
    _active_tincand(monkeypatch, messages=False)
    by_name = {r.name: r for r in doc.check_baseline_capabilities()}

    assert by_name["messages-capability"].status == DoctorStatus.DEGRADED
    assert by_name["messages-capability"].required is False


def test_baseline_capabilities_messages_capability_ok_when_present(monkeypatch, no_ambient_aec_issues):
    _active_tincand(monkeypatch, messages=True)
    by_name = {r.name: r for r in doc.check_baseline_capabilities()}

    assert by_name["messages-capability"].status == DoctorStatus.OK


@pytest.mark.parametrize("tincand_active", [True, False])
def test_baseline_capabilities_call_audio_aec_is_always_absent_and_not_required(monkeypatch, no_ambient_aec_issues, tincand_active):
    """FR-1.2: call-audio-aec must never contribute to a non-green aggregate,
    in either branch, since tincand does not yet expose the capability flag."""
    if tincand_active:
        _active_tincand(monkeypatch)
    else:
        monkeypatch.setattr(doc, "_tincand_unit_active", lambda: False)

    by_name = {r.name: r for r in doc.check_baseline_capabilities()}

    assert by_name["call-audio-aec"].status == DoctorStatus.ABSENT
    assert by_name["call-audio-aec"].required is False


def test_baseline_capabilities_calls_ambient_aec_unconditionally_in_both_branches(monkeypatch):
    calls = []

    def _fake_ambient_aec():
        calls.append(1)
        return AssetCheckResult("ambient-aec-default", DoctorStatus.OK, True)

    monkeypatch.setattr(doc, "_check_ambient_aec", _fake_ambient_aec)

    monkeypatch.setattr(doc, "_tincand_unit_active", lambda: False)
    doc.check_baseline_capabilities()
    assert len(calls) == 1

    _active_tincand(monkeypatch)
    doc.check_baseline_capabilities()
    assert len(calls) == 2


def test_baseline_capabilities_uses_retrying_for_the_tincand_dbus_call(monkeypatch, no_ambient_aec_issues):
    """Confirms get_tincand_status is invoked through the real _retrying (not
    called directly) -- a transient exception on the first attempt must be
    absorbed rather than propagating out of check_baseline_capabilities."""
    monkeypatch.setattr(doc, "_tincand_unit_active", lambda: True)
    monkeypatch.setattr(doc.time, "sleep", lambda s: None)

    attempts = []

    def _flaky_status():
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("transient dbus blip")
        return {"connected": True, "call_setup_ready": True, "capabilities": {"messages": True}}

    monkeypatch.setattr(doc, "get_tincand_status", _flaky_status)
    by_name = {r.name: r for r in doc.check_baseline_capabilities()}

    assert len(attempts) == 2
    assert by_name["tincand-connected"].status == DoctorStatus.OK
