"""Tests for iris/up.py (ti-2fiv).

All subprocess and network calls are mocked — no real services required.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from iris.up import (
    _bring_up_tincand,
    _is_active,
    _print_tincand_readiness,
    bring_up,
)


def _active_proc():
    return MagicMock(returncode=0, stdout="active", stderr="")


def _inactive_proc():
    return MagicMock(returncode=3, stdout="inactive", stderr="")


# ---------------------------------------------------------------------------
# _is_active
# ---------------------------------------------------------------------------

def test_is_active_true_on_exit_zero():
    with patch("iris.up.subprocess.run", return_value=_active_proc()):
        assert _is_active("iris-whisper") is True


def test_is_active_false_on_nonzero():
    with patch("iris.up.subprocess.run", return_value=_inactive_proc()):
        assert _is_active("iris-whisper") is False


def test_is_active_false_on_oserror():
    with patch("iris.up.subprocess.run", side_effect=OSError):
        assert _is_active("iris-whisper") is False


# ---------------------------------------------------------------------------
# bring_up: managed services
# ---------------------------------------------------------------------------

def test_bring_up_skips_start_when_already_active(capsys):
    with patch("iris.up._is_active", return_value=True), \
         patch("iris.up._health_ok", return_value=True):
        rc = bring_up(launch_console=False)
    assert rc == 0
    out = capsys.readouterr().out
    assert "already active" in out


def test_bring_up_starts_service_when_inactive(capsys):
    call_log: list[str] = []

    def _run(cmd, **kwargs):
        call_log.append(cmd[2])  # 'is-active' or 'start'
        if "is-active" in cmd:
            return _inactive_proc()
        return _active_proc()

    with patch("iris.up.subprocess.run", side_effect=_run), \
         patch("iris.up._health_ok", return_value=True):
        rc = bring_up(launch_console=False)
    assert rc == 0
    assert "start" in call_log


def test_bring_up_returns_1_when_start_fails(capsys):
    def _run(cmd, **kwargs):
        if "is-active" in cmd:
            return _inactive_proc()
        return MagicMock(returncode=1, stdout="", stderr="failed")

    with patch("iris.up.subprocess.run", side_effect=_run), \
         patch("iris.up._health_ok", return_value=True):
        rc = bring_up(launch_console=False)
    assert rc == 1
    out = capsys.readouterr().out
    assert "FAILED" in out or "failed" in out.lower()


# ---------------------------------------------------------------------------
# bring_up: llama and tincand (warn-but-don't-block)
# ---------------------------------------------------------------------------

def test_bring_up_warns_when_llama_unreachable(capsys):
    with patch("iris.up._is_active", return_value=True), \
         patch("iris.up._health_ok", side_effect=lambda url, **_: "9001" in url):
        rc = bring_up(launch_console=False)
    assert rc == 0
    out = capsys.readouterr().out
    assert "llama" in out.lower() or "8080" in out


def test_bring_up_succeeds_when_tincand_absent(capsys):
    with patch("iris.up._is_active", return_value=True), \
         patch("iris.up._health_ok", side_effect=lambda url, **_: "8080" in url):
        rc = bring_up(launch_console=False)
    assert rc == 0
    out = capsys.readouterr().out
    assert "tincand" in out.lower() or "9001" in out


def test_bring_up_all_healthy_returns_0(capsys):
    with patch("iris.up._is_active", return_value=True), \
         patch("iris.up._health_ok", return_value=True):
        rc = bring_up(launch_console=False)
    assert rc == 0


# ---------------------------------------------------------------------------
# bring_up: iris-brain daemon-ensure step (warn-but-don't-block; ti-vvc9o/ti-kiv1b)
#
# _unit_known is keyed off the exact unit string, so returning False for
# everything except "iris-brain.service" also keeps tincand's own
# _bring_up_tincand() short-circuited at its unit-absent check — its output
# always contains "not installed" too, so brain-specific assertions below
# pin to the full "checking iris-brain…" line (or the brain-only warning
# text) rather than a bare substring that tincand's row could also satisfy.
# ---------------------------------------------------------------------------

def test_bring_up_brain_not_installed(capsys):
    def _unit_known(unit):
        return False  # iris-brain.service and tincand.service both absent

    with patch("iris.up._unit_known", side_effect=_unit_known), \
         patch("iris.up._is_active", return_value=True), \
         patch("iris.up._health_ok", return_value=False), \
         patch("iris.up._start_service") as mock_start:
        rc = bring_up(launch_console=False)
    assert rc == 0
    mock_start.assert_not_called()
    out = capsys.readouterr().out
    assert "checking iris-brain… not installed" in out
    assert "iris-brain is not installed" in out
    assert "iris install-services" in out


def test_bring_up_brain_already_active(capsys):
    def _unit_known(unit):
        return unit == "iris-brain.service"

    with patch("iris.up._unit_known", side_effect=_unit_known), \
         patch("iris.up._is_active", return_value=True), \
         patch("iris.up._health_ok", return_value=False), \
         patch("iris.up._start_service") as mock_start:
        rc = bring_up(launch_console=False)
    assert rc == 0
    mock_start.assert_not_called()
    out = capsys.readouterr().out
    assert "checking iris-brain… already active ✓" in out


def test_bring_up_brain_starts_when_inactive(capsys):
    def _unit_known(unit):
        return unit == "iris-brain.service"

    def _is_active(svc):
        return svc != "iris-brain"  # whisper/kokoro active; brain inactive

    with patch("iris.up._unit_known", side_effect=_unit_known), \
         patch("iris.up._is_active", side_effect=_is_active), \
         patch("iris.up._health_ok", return_value=False), \
         patch("iris.up._start_service", return_value=True) as mock_start:
        rc = bring_up(launch_console=False)
    assert rc == 0
    mock_start.assert_called_once_with("iris-brain")
    out = capsys.readouterr().out
    assert "iris-brain is optional" not in out


def test_bring_up_brain_start_fails_does_not_block(capsys):
    # FR-05 regression guard: unlike whisper/kokoro, a failed iris-brain
    # start must not land in the blocking `failed` list — bring_up() still
    # returns 0.
    def _unit_known(unit):
        return unit == "iris-brain.service"

    def _is_active(svc):
        return svc != "iris-brain"

    with patch("iris.up._unit_known", side_effect=_unit_known), \
         patch("iris.up._is_active", side_effect=_is_active), \
         patch("iris.up._health_ok", return_value=False), \
         patch("iris.up._start_service", return_value=False) as mock_start:
        rc = bring_up(launch_console=False)
    assert rc == 0
    mock_start.assert_called_once_with("iris-brain")
    out = capsys.readouterr().out
    assert "iris-brain is optional" in out


# ---------------------------------------------------------------------------
# install.py: iris-brain reinstated in UNITS, always-on daemon (ti-omwom/ti-kzkfv)
# ---------------------------------------------------------------------------

def test_iris_brain_in_install_units():
    from iris.services.install import UNITS
    names = {spec.name for spec in UNITS}
    assert "iris-brain" in names


def test_iris_brain_not_in_doctor_services():
    from iris.doctor import EXPECTED_SERVICES
    names = {svc.name for svc in EXPECTED_SERVICES}
    assert "iris-brain" not in names


def test_install_does_not_retire_iris_brain_unit(tmp_path, capsys):
    from iris.services.install import install
    brain_unit = tmp_path / "iris-brain.service"
    brain_unit.write_text("[Unit]\nDescription=old brain\n")

    systemctl_calls: list[list[str]] = []

    def _run(cmd, **kwargs):
        systemctl_calls.append(list(cmd))
        if "is-active" in cmd and "iris-brain" in cmd[-1]:
            return MagicMock(returncode=0)
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("iris.services.install.subprocess.run", side_effect=_run), \
         patch("iris.services.install._SYSTEMD_USER", tmp_path), \
         patch("iris.services.install._linger_enabled", return_value=True):
        install(dry_run=False)

    stop_cmds = [c for c in systemctl_calls if "stop" in c]
    assert not any("iris-brain" in " ".join(c) for c in stop_cmds)


# ---------------------------------------------------------------------------
# __main__: 'iris up' is wired
# ---------------------------------------------------------------------------

def test_iris_up_registered_in_commands():
    from iris.__main__ import _COMMANDS
    assert "up" in _COMMANDS
    assert "iris.up" in _COMMANDS["up"]


# ---------------------------------------------------------------------------
# _bring_up_tincand (tincan-m9t6h.1)
# ---------------------------------------------------------------------------

def test_bring_up_tincand_unit_absent():
    with patch("iris.up._unit_known", return_value=False):
        result = _bring_up_tincand()
    assert result["reason"] == "unit-absent"
    assert result["health"] is False


def test_bring_up_tincand_start_timeout():
    with patch("iris.up._unit_known", return_value=True), \
         patch("iris.up._is_active", return_value=False), \
         patch("iris.up.subprocess.run", return_value=MagicMock(returncode=0)), \
         patch("iris.up._health_ok", return_value=False), \
         patch("iris.up.time.sleep"):
        result = _bring_up_tincand()
    assert result["reason"] == "start-timeout"
    assert result["health"] is False


def test_bring_up_tincand_dbus_error():
    with patch("iris.up._unit_known", return_value=True), \
         patch("iris.up._is_active", return_value=True), \
         patch("iris.up._health_ok", return_value=True), \
         patch("iris.up.get_tincand_status", side_effect=Exception("no dbus")), \
         patch("iris.up.time.sleep"):
        result = _bring_up_tincand()
    assert result["reason"] == "dbus-error"
    assert result["health"] is True


def test_bring_up_tincand_happy_path():
    status = {
        "connected": True,
        "adapter_warning": "",
        "call_setup_ready": True,
        "device_discovered": True,
    }
    with patch("iris.up._unit_known", return_value=True), \
         patch("iris.up._is_active", return_value=True), \
         patch("iris.up._health_ok", return_value=True), \
         patch("iris.up.get_tincand_status", return_value=status):
        result = _bring_up_tincand()
    assert result["reason"] == "ok"
    assert result["health"] is True
    assert result["connected"] is True
    assert result["call_setup_ready"] is True
    assert result["adapter_warning"] == ""


def test_bring_up_tincand_adapter_warning():
    status = {
        "connected": False,
        "adapter_warning": "iPhone on hci0 (built-in)",
        "call_setup_ready": True,
        "device_discovered": False,
    }
    with patch("iris.up._unit_known", return_value=True), \
         patch("iris.up._is_active", return_value=True), \
         patch("iris.up._health_ok", return_value=True), \
         patch("iris.up.get_tincand_status", return_value=status):
        result = _bring_up_tincand()
    assert result["reason"] == "ok"
    assert result["adapter_warning"] == "iPhone on hci0 (built-in)"


# ---------------------------------------------------------------------------
# _print_tincand_readiness (tincan-m9t6h.1)
# ---------------------------------------------------------------------------

def test_print_tincand_unit_absent(capsys):
    _print_tincand_readiness({"reason": "unit-absent"})
    out = capsys.readouterr().out
    assert "not installed" in out
    assert "optional" in out


def test_print_tincand_start_timeout(capsys):
    _print_tincand_readiness({"reason": "start-timeout"})
    out = capsys.readouterr().out
    assert "did not respond" in out
    assert "journalctl" in out
    assert "optional" in out


def test_print_tincand_dbus_error(capsys):
    _print_tincand_readiness({"reason": "dbus-error"})
    out = capsys.readouterr().out
    assert "degraded" in out or "D-Bus" in out


def test_print_tincand_happy_no_warning(capsys):
    _print_tincand_readiness({
        "reason": "ok",
        "adapter_warning": "",
        "call_setup_ready": True,
        "connected": True,
        "device_discovered": True,
        "health": True,
    })
    out = capsys.readouterr().out
    assert "HFP daemon" in out
    assert "SELinux" in out
    assert "iPhone" in out


def test_print_tincand_adapter_mismatch(capsys):
    _print_tincand_readiness({
        "reason": "ok",
        "adapter_warning": "iPhone on hci0 (built-in, no SCO)",
        "call_setup_ready": True,
        "connected": False,
        "device_discovered": False,
        "health": True,
    })
    out = capsys.readouterr().out
    assert "mismatch" in out.lower() or "hci0" in out
    assert "iPhone" in out
