"""Tests for iris doctor health check + remediation CLI (ti-qxel.4).

These tests FAIL until the builder implements iris/doctor.py.
All external calls (systemctl, /health HTTP) are mocked.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_services():
    from iris.doctor import ServiceDescriptor
    return [
        ServiceDescriptor(name="iris-llama",   unit="iris-llama.service",
                          health_url="http://127.0.0.1:8080/health", required=True,
                          deep_check=None),
        ServiceDescriptor(name="iris-whisper", unit="iris-whisper.service",
                          health_url="http://127.0.0.1:8082/health", required=True,
                          deep_check=None),
        ServiceDescriptor(name="tincand",      unit="tincand.service",
                          health_url="http://127.0.0.1:9001/health", required=False,
                          deep_check=None),
    ]


def _mock_active() -> MagicMock:
    r = MagicMock()
    r.returncode = 0
    r.stdout = "active"
    return r


def _mock_inactive() -> MagicMock:
    r = MagicMock()
    r.returncode = 3
    r.stdout = "inactive"
    return r


def _mock_not_found() -> MagicMock:
    r = MagicMock()
    r.returncode = 4
    r.stdout = "not-found"
    return r


def _mock_health_ok() -> MagicMock:
    resp = MagicMock()
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    resp.read.return_value = json.dumps({"ready": True}).encode()
    resp.status = 200
    return resp


# ---------------------------------------------------------------------------
# Status levels: OK, DEGRADED, DOWN, ABSENT, UNKNOWN
# ---------------------------------------------------------------------------

def test_status_ok_when_active_and_health_200():
    from iris.doctor import DoctorStatus, check_services
    services = _get_services()

    with patch("iris.doctor.subprocess.run", return_value=_mock_active()), \
         patch("iris.doctor.urllib.request.urlopen", return_value=_mock_health_ok()):
        results = check_services([services[0]])
    assert results[0].status == DoctorStatus.OK


def test_status_degraded_when_active_but_health_non_200():
    from iris.doctor import DoctorStatus, check_services
    import urllib.error
    services = _get_services()

    with patch("iris.doctor.subprocess.run", return_value=_mock_active()), \
         patch("iris.doctor.urllib.request.urlopen",
               side_effect=urllib.error.HTTPError(
                   url="", code=503, msg="", hdrs=None, fp=None)):
        results = check_services([services[0]])
    assert results[0].status == DoctorStatus.DEGRADED


def test_status_down_when_unit_inactive():
    from iris.doctor import DoctorStatus, check_services
    services = _get_services()

    with patch("iris.doctor.subprocess.run", return_value=_mock_inactive()):
        results = check_services([services[0]])
    assert results[0].status == DoctorStatus.DOWN


def test_status_absent_when_unit_not_found():
    from iris.doctor import DoctorStatus, check_services
    services = _get_services()

    with patch("iris.doctor.subprocess.run", return_value=_mock_not_found()):
        results = check_services([services[2]])  # optional tincand
    assert results[0].status == DoctorStatus.ABSENT


def test_status_unknown_when_systemctl_fails():
    from iris.doctor import DoctorStatus, check_services
    services = _get_services()

    with patch("iris.doctor.subprocess.run", side_effect=OSError("systemctl not found")):
        results = check_services([services[0]])
    assert results[0].status == DoctorStatus.UNKNOWN


# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------

def test_exit_code_0_all_ok():
    from iris.doctor import doctor_main
    services = _get_services()[:2]

    with patch("iris.doctor.subprocess.run", return_value=_mock_active()), \
         patch("iris.doctor.urllib.request.urlopen", return_value=_mock_health_ok()), \
         patch("iris.doctor.EXPECTED_SERVICES", services):
        code = doctor_main(args=[])
    assert code == 0


def test_exit_code_1_degraded():
    from iris.doctor import doctor_main
    import urllib.error
    services = _get_services()[:1]

    with patch("iris.doctor.subprocess.run", return_value=_mock_active()), \
         patch("iris.doctor.urllib.request.urlopen",
               side_effect=urllib.error.HTTPError(
                   url="", code=503, msg="", hdrs=None, fp=None)), \
         patch("iris.doctor.EXPECTED_SERVICES", services):
        code = doctor_main(args=[])
    assert code == 1


def test_exit_code_2_down():
    from iris.doctor import doctor_main
    services = _get_services()[:1]

    with patch("iris.doctor.subprocess.run", return_value=_mock_inactive()), \
         patch("iris.doctor.EXPECTED_SERVICES", services):
        code = doctor_main(args=[])
    assert code == 2


# ---------------------------------------------------------------------------
# --fix behavior
# ---------------------------------------------------------------------------

def test_fix_calls_systemctl_start_for_down_services():
    from iris.doctor import doctor_main
    services = _get_services()[:2]
    started = []

    def _run(cmd, **kw):
        if isinstance(cmd, list) and "start" in cmd:
            started.append(cmd)
            return MagicMock(returncode=0)
        return _mock_inactive()

    with patch("iris.doctor.subprocess.run", side_effect=_run), \
         patch("iris.doctor.EXPECTED_SERVICES", services):
        doctor_main(args=["--fix"])

    assert len(started) >= 1


def test_fix_skips_ok_services():
    from iris.doctor import doctor_main
    services = _get_services()[:1]
    started = []

    def _run(cmd, **kw):
        if isinstance(cmd, list) and "start" in cmd:
            started.append(cmd)
        return _mock_active()

    with patch("iris.doctor.subprocess.run", side_effect=_run), \
         patch("iris.doctor.urllib.request.urlopen", return_value=_mock_health_ok()), \
         patch("iris.doctor.EXPECTED_SERVICES", services):
        doctor_main(args=["--fix"])

    assert started == []


def test_fix_skips_degraded_services():
    from iris.doctor import doctor_main
    import urllib.error
    services = _get_services()[:1]
    started = []

    def _run(cmd, **kw):
        if isinstance(cmd, list) and "start" in cmd:
            started.append(cmd)
        return _mock_active()

    with patch("iris.doctor.subprocess.run", side_effect=_run), \
         patch("iris.doctor.urllib.request.urlopen",
               side_effect=urllib.error.HTTPError(
                   url="", code=503, msg="", hdrs=None, fp=None)), \
         patch("iris.doctor.EXPECTED_SERVICES", services):
        doctor_main(args=["--fix"])

    assert started == []


# ---------------------------------------------------------------------------
# --json output
# ---------------------------------------------------------------------------

def test_json_output_has_required_fields(capsys):
    from iris.doctor import doctor_main
    services = _get_services()[:1]

    with patch("iris.doctor.subprocess.run", return_value=_mock_active()), \
         patch("iris.doctor.urllib.request.urlopen", return_value=_mock_health_ok()), \
         patch("iris.doctor.EXPECTED_SERVICES", services):
        doctor_main(args=["--json"])

    out = capsys.readouterr().out
    data = json.loads(out)
    assert "services" in data
    assert "exit_code" in data
    svc = data["services"][0]
    assert "name" in svc
    assert "status" in svc
    assert "required" in svc


def test_json_output_correct_values(capsys):
    from iris.doctor import doctor_main
    services = _get_services()[:1]

    with patch("iris.doctor.subprocess.run", return_value=_mock_active()), \
         patch("iris.doctor.urllib.request.urlopen", return_value=_mock_health_ok()), \
         patch("iris.doctor.EXPECTED_SERVICES", services):
        doctor_main(args=["--json"])

    out = capsys.readouterr().out
    data = json.loads(out)
    svc = data["services"][0]
    assert svc["name"] == "iris-llama"
    assert svc["status"] == "ok"
    assert svc["required"] is True


# ---------------------------------------------------------------------------
# --check=svc filters to single row
# ---------------------------------------------------------------------------

def test_check_flag_filters_to_single_service(capsys):
    from iris.doctor import doctor_main
    services = _get_services()[:2]

    with patch("iris.doctor.subprocess.run", return_value=_mock_active()), \
         patch("iris.doctor.urllib.request.urlopen", return_value=_mock_health_ok()), \
         patch("iris.doctor.EXPECTED_SERVICES", services):
        doctor_main(args=["--check=iris-llama"])

    out = capsys.readouterr().out
    assert "iris-llama" in out
    assert "iris-whisper" not in out


# ---------------------------------------------------------------------------
# Table drops Notes col when terminal under 72 cols
# ---------------------------------------------------------------------------

def test_table_drops_notes_col_under_72_cols(capsys, monkeypatch):
    from iris.doctor import doctor_main
    import shutil
    services = _get_services()[:1]
    monkeypatch.setattr(shutil, "get_terminal_size", lambda: MagicMock(columns=70))

    with patch("iris.doctor.subprocess.run", return_value=_mock_active()), \
         patch("iris.doctor.urllib.request.urlopen", return_value=_mock_health_ok()), \
         patch("iris.doctor.EXPECTED_SERVICES", services):
        doctor_main(args=[])

    out = capsys.readouterr().out
    assert "Notes" not in out


def test_table_includes_notes_col_at_wide_terminal(capsys, monkeypatch):
    from iris.doctor import doctor_main
    import shutil
    services = _get_services()[:1]
    monkeypatch.setattr(shutil, "get_terminal_size", lambda: MagicMock(columns=120))

    with patch("iris.doctor.subprocess.run", return_value=_mock_active()), \
         patch("iris.doctor.urllib.request.urlopen", return_value=_mock_health_ok()), \
         patch("iris.doctor.EXPECTED_SERVICES", services):
        doctor_main(args=[])

    out = capsys.readouterr().out
    assert "Notes" in out
