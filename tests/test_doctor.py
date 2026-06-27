"""Tests for iris doctor health check + remediation CLI (ti-qxel.4).

These tests FAIL until the builder implements iris/doctor.py.
All external calls (systemctl, /health HTTP) are mocked.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _isolate_assets():
    """Isolate the systemd-service layer.

    Two defaults: neutralize the asset preflight (covered in
    test_doctor_assets.py), and make the /health probe default to 'no server' so
    a real server on the dev box (e.g. a live llama.cpp on :8080) can't leak into
    a unit-state assertion. Tests that need a reachable endpoint override
    ``iris.doctor.urllib.request.urlopen`` locally (inner patch wins).
    """
    import urllib.error
    with patch("iris.doctor.check_assets", return_value=[]), \
         patch("iris.doctor.urllib.request.urlopen",
               side_effect=urllib.error.URLError("no server (test default)")):
        yield


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
    import os
    import shutil
    from iris.doctor import doctor_main
    services = _get_services()[:1]
    monkeypatch.setattr(shutil, "get_terminal_size", lambda *a, **kw: os.terminal_size((70, 24)))

    with patch("iris.doctor.subprocess.run", return_value=_mock_active()), \
         patch("iris.doctor.urllib.request.urlopen", return_value=_mock_health_ok()), \
         patch("iris.doctor.EXPECTED_SERVICES", services):
        doctor_main(args=[])

    out = capsys.readouterr().out
    assert "Notes" not in out


def test_table_includes_notes_col_at_wide_terminal(capsys, monkeypatch):
    import os
    import shutil
    from iris.doctor import doctor_main
    services = _get_services()[:1]
    monkeypatch.setattr(shutil, "get_terminal_size", lambda *a, **kw: os.terminal_size((120, 24)))

    with patch("iris.doctor.subprocess.run", return_value=_mock_active()), \
         patch("iris.doctor.urllib.request.urlopen", return_value=_mock_health_ok()), \
         patch("iris.doctor.EXPECTED_SERVICES", services):
        doctor_main(args=[])

    out = capsys.readouterr().out
    assert "Notes" in out


# ---------------------------------------------------------------------------
# Port probe is independent of the systemd unit (a server run by hand counts)
# ---------------------------------------------------------------------------

def _mock_health(data) -> MagicMock:
    resp = MagicMock()
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    resp.read.return_value = json.dumps(data).encode()
    return resp


def test_health_ready_accepts_llama_and_iris_formats():
    from iris.doctor import _health_ready
    assert _health_ready({"ready": True}) is True
    assert _health_ready({"ready": False}) is False
    assert _health_ready({"status": "ok"}) is True          # llama.cpp
    assert _health_ready({"status": "error"}) is False
    assert _health_ready({}) is True                          # answered, no signal


def test_ok_when_port_healthy_without_unit():
    # operator's case: no systemd unit, but a server is live on the port
    from iris.doctor import DoctorStatus, check_services
    svc = _get_services()[0]  # iris-llama (:8080)
    with patch("iris.doctor.subprocess.run", return_value=_mock_not_found()), \
         patch("iris.doctor.urllib.request.urlopen", return_value=_mock_health({"status": "ok"})):
        results = check_services([svc])
    assert results[0].status == DoctorStatus.OK
    assert "running" in results[0].note.lower()


def test_ok_when_port_healthy_unit_inactive():
    from iris.doctor import DoctorStatus, check_services
    svc = _get_services()[0]
    with patch("iris.doctor.subprocess.run", return_value=_mock_inactive()), \
         patch("iris.doctor.urllib.request.urlopen", return_value=_mock_health({"ready": True})):
        results = check_services([svc])
    assert results[0].status == DoctorStatus.OK


def test_absent_when_no_unit_and_no_server():
    from iris.doctor import DoctorStatus, check_services
    svc = _get_services()[0]
    # subprocess not-found + the autouse default (urlopen -> URLError) = nothing there
    with patch("iris.doctor.subprocess.run", return_value=_mock_not_found()):
        results = check_services([svc])
    assert results[0].status == DoctorStatus.ABSENT


# ---------------------------------------------------------------------------
# _tincand_deep_check (tincan-m9t6h.2)
# ---------------------------------------------------------------------------

def test_tincand_deep_check_all_pass():
    from iris.doctor import _tincand_deep_check
    status = {"call_setup_ready": True, "adapter_warning": "", "connected": True}
    with patch("iris.doctor.urllib.request.urlopen", return_value=_mock_health_ok()), \
         patch("iris.doctor._tincand_get_status", return_value=status):
        lines = _tincand_deep_check("tincand", "tincand.service")
    assert any("✓" in l and "health" in l for l in lines)
    assert any("✓" in l and "SELinux" in l for l in lines)
    assert any("✓" in l and "adapter" in l for l in lines)
    assert any("iPhone" in l for l in lines)


def test_tincand_deep_check_health_unreachable():
    import urllib.error
    from iris.doctor import _tincand_deep_check
    status = {"call_setup_ready": True, "adapter_warning": "", "connected": False}
    with patch("iris.doctor.urllib.request.urlopen",
               side_effect=urllib.error.URLError("refused")), \
         patch("iris.doctor._tincand_get_status", return_value=status):
        lines = _tincand_deep_check("tincand", "tincand.service")
    assert any("✗" in l and "health" in l for l in lines)


def test_tincand_deep_check_selinux_missing():
    from iris.doctor import _tincand_deep_check
    status = {"call_setup_ready": False, "adapter_warning": "", "connected": False}
    with patch("iris.doctor.urllib.request.urlopen", return_value=_mock_health_ok()), \
         patch("iris.doctor._tincand_get_status", return_value=status):
        lines = _tincand_deep_check("tincand", "tincand.service")
    selinux_line = next((l for l in lines if "SELinux" in l), None)
    assert selinux_line is not None
    assert "✗" in selinux_line
    assert "semodule" in selinux_line or "NOT loaded" in selinux_line


def test_tincand_deep_check_adapter_mismatch():
    from iris.doctor import _tincand_deep_check
    status = {"call_setup_ready": True, "adapter_warning": "iPhone on hci0 (built-in)", "connected": False}
    with patch("iris.doctor.urllib.request.urlopen", return_value=_mock_health_ok()), \
         patch("iris.doctor._tincand_get_status", return_value=status):
        lines = _tincand_deep_check("tincand", "tincand.service")
    mismatch = next((l for l in lines if "mismatch" in l.lower() or "adapter" in l.lower()), None)
    assert mismatch is not None
    assert "✗" in mismatch
    assert "hci0" in mismatch


def test_tincand_deep_check_dbus_unavailable():
    from iris.doctor import _tincand_deep_check
    with patch("iris.doctor.urllib.request.urlopen", return_value=_mock_health_ok()), \
         patch("iris.doctor._tincand_get_status", side_effect=Exception("no dbus")):
        lines = _tincand_deep_check("tincand", "tincand.service")
    assert any("?" in l and ("D-Bus" in l or "unavailable" in l) for l in lines)


def test_check_services_deep_populates_deep_lines():
    from iris.doctor import ServiceDescriptor, check_services
    deep_fn = MagicMock(return_value=["✓ health endpoint"])
    svc = ServiceDescriptor("tincand", "tincand.service",
                            "http://127.0.0.1:9001/health", required=False,
                            deep_check=deep_fn)
    with patch("iris.doctor.subprocess.run", return_value=_mock_active()), \
         patch("iris.doctor.urllib.request.urlopen", return_value=_mock_health_ok()):
        results = check_services([svc], deep=True)
    assert results[0].deep_lines == ["✓ health endpoint"]
    deep_fn.assert_called_once_with("tincand", "tincand.service")


def test_check_services_no_deep_skips_deep_check():
    from iris.doctor import ServiceDescriptor, check_services
    deep_fn = MagicMock(return_value=["✓ health endpoint"])
    svc = ServiceDescriptor("tincand", "tincand.service",
                            "http://127.0.0.1:9001/health", required=False,
                            deep_check=deep_fn)
    with patch("iris.doctor.subprocess.run", return_value=_mock_active()), \
         patch("iris.doctor.urllib.request.urlopen", return_value=_mock_health_ok()):
        results = check_services([svc], deep=False)
    assert results[0].deep_lines == []
    deep_fn.assert_not_called()


def test_json_includes_tincand_detail(capsys):
    from iris.doctor import doctor_main
    status = {"call_setup_ready": True, "adapter_warning": "", "connected": True, "device_discovered": False}
    with patch("iris.doctor.subprocess.run", return_value=_mock_active()), \
         patch("iris.doctor.urllib.request.urlopen", return_value=_mock_health_ok()), \
         patch("iris.doctor._tincand_get_status", return_value=status):
        doctor_main(["--check", "tincand", "--json"])
    out = json.loads(capsys.readouterr().out)
    tincand_svc = next((s for s in out["services"] if s["name"] == "tincand"), None)
    assert tincand_svc is not None
    assert "tincand_detail" in tincand_svc
    assert tincand_svc["tincand_detail"]["call_setup_ready"] is True


# ---------------------------------------------------------------------------
# sentinel_hint — tincand DOWN hint (tincan-17bsu)
# ---------------------------------------------------------------------------

def test_sentinel_hint_prints_journalctl_and_want_down_note_when_tincand_down(capsys):
    from iris.doctor import doctor_main
    services = _get_services()
    tincand_svc = next(s for s in services if s.name == "tincand")

    with patch("iris.doctor.subprocess.run", return_value=_mock_inactive()), \
         patch("iris.doctor.EXPECTED_SERVICES", [tincand_svc]):
        doctor_main(args=[])

    out = capsys.readouterr().out
    assert "journalctl --user -u tincand.service -n 20" in out
    assert "/run/tincan/want-down" in out


def test_sentinel_hint_not_printed_when_tincand_ok(capsys):
    from iris.doctor import doctor_main
    services = _get_services()
    tincand_svc = next(s for s in services if s.name == "tincand")

    with patch("iris.doctor.subprocess.run", return_value=_mock_active()), \
         patch("iris.doctor.urllib.request.urlopen", return_value=_mock_health_ok()), \
         patch("iris.doctor.EXPECTED_SERVICES", [tincand_svc]):
        doctor_main(args=[])

    out = capsys.readouterr().out
    assert "journalctl" not in out
    assert "/run/tincan/want-down" not in out
