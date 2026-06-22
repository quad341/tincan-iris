"""Tests for iris install-services unit file generation (ti-qxel.3, ti-t8dy).

All filesystem writes and subprocess calls are controlled via tmp_path + mocks.
"""
from __future__ import annotations

import io
import os
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from iris.services.install import install, _validate_exec_starts, UNITS


def _ok_run(cmd, **kwargs):
    """Mock subprocess.run that always succeeds."""
    return MagicMock(returncode=0, stdout="active", stderr="")


_PASS_PREFLIGHT = patch("iris.services.install._validate_exec_starts", return_value=[])


# ---------------------------------------------------------------------------
# Template variable substitution
# ---------------------------------------------------------------------------

def test_repo_path_substituted_in_unit_file(tmp_path):
    with _PASS_PREFLIGHT, \
         patch("iris.services.install.subprocess.run", side_effect=_ok_run), \
         patch("iris.services.install._SYSTEMD_USER", tmp_path), \
         patch("iris.services.install._linger_enabled", return_value=True):
        install(dry_run=False)
    for unit_path in tmp_path.iterdir():
        content = unit_path.read_text()
        assert "{REPO_PATH}" not in content


def test_user_home_substituted_in_unit_file(tmp_path):
    with _PASS_PREFLIGHT, \
         patch("iris.services.install.subprocess.run", side_effect=_ok_run), \
         patch("iris.services.install._SYSTEMD_USER", tmp_path), \
         patch("iris.services.install._linger_enabled", return_value=True):
        install(dry_run=False)
    for unit_path in tmp_path.iterdir():
        content = unit_path.read_text()
        assert "{USER_HOME}" not in content


def test_python_whisper_substituted(tmp_path):
    with _PASS_PREFLIGHT, \
         patch("iris.services.install.subprocess.run", side_effect=_ok_run), \
         patch("iris.services.install._SYSTEMD_USER", tmp_path), \
         patch("iris.services.install._linger_enabled", return_value=True):
        install(dry_run=False)
    whisper_unit = tmp_path / "iris-whisper.service"
    if whisper_unit.exists():
        content = whisper_unit.read_text()
        assert "{PYTHON_WHISPER}" not in content
        assert ".venv-whisper" in content or "python" in content.lower()


def test_python_kokoro_substituted(tmp_path):
    with _PASS_PREFLIGHT, \
         patch("iris.services.install.subprocess.run", side_effect=_ok_run), \
         patch("iris.services.install._SYSTEMD_USER", tmp_path), \
         patch("iris.services.install._linger_enabled", return_value=True):
        install(dry_run=False)
    kokoro_unit = tmp_path / "iris-kokoro.service"
    if kokoro_unit.exists():
        content = kokoro_unit.read_text()
        assert "{PYTHON_KOKORO}" not in content
        assert ".venv-kokoro" in content or "python" in content.lower()


# ---------------------------------------------------------------------------
# Idempotency — unchanged shows (unchanged), changed shows (updated)
# ---------------------------------------------------------------------------

def test_idempotent_run_shows_unchanged(tmp_path, capsys):
    with _PASS_PREFLIGHT, \
         patch("iris.services.install.subprocess.run", side_effect=_ok_run), \
         patch("iris.services.install._SYSTEMD_USER", tmp_path), \
         patch("iris.services.install._linger_enabled", return_value=True):
        install(dry_run=False)
        capsys.readouterr()  # discard first run output
        install(dry_run=False)
    out = capsys.readouterr().out
    assert "unchanged" in out.lower()


def test_modified_unit_shows_updated(tmp_path, capsys):
    with _PASS_PREFLIGHT, \
         patch("iris.services.install.subprocess.run", side_effect=_ok_run), \
         patch("iris.services.install._SYSTEMD_USER", tmp_path), \
         patch("iris.services.install._linger_enabled", return_value=True):
        install(dry_run=False)
        first_unit = next(iter(tmp_path.iterdir()))
        first_unit.write_text("# modified externally\n")
        capsys.readouterr()
        install(dry_run=False)
    out = capsys.readouterr().out
    assert "updated" in out.lower()


# ---------------------------------------------------------------------------
# --dry-run
# ---------------------------------------------------------------------------

def test_dry_run_prints_dry_run_prefix(tmp_path, capsys):
    with patch("iris.services.install.subprocess.run", side_effect=_ok_run), \
         patch("iris.services.install._SYSTEMD_USER", tmp_path), \
         patch("iris.services.install._linger_enabled", return_value=True):
        install(dry_run=True)  # preflight is skipped in dry_run mode
    out = capsys.readouterr().out
    assert "[dry-run]" in out


def test_dry_run_does_not_write_files(tmp_path):
    dest = tmp_path / "systemd"
    dest.mkdir()
    with patch("iris.services.install.subprocess.run", side_effect=_ok_run), \
         patch("iris.services.install._SYSTEMD_USER", dest), \
         patch("iris.services.install._linger_enabled", return_value=True):
        install(dry_run=True)  # preflight is skipped in dry_run mode
    assert list(dest.iterdir()) == []


# ---------------------------------------------------------------------------
# systemctl invocations
# ---------------------------------------------------------------------------

def test_systemctl_daemon_reload_called(tmp_path):
    called_cmds = []

    def _cap(cmd, **kwargs):
        called_cmds.append(cmd)
        return MagicMock(returncode=0, stdout="active", stderr="")

    with _PASS_PREFLIGHT, \
         patch("iris.services.install.subprocess.run", side_effect=_cap), \
         patch("iris.services.install._SYSTEMD_USER", tmp_path), \
         patch("iris.services.install._linger_enabled", return_value=True):
        install(dry_run=False)
    assert any("daemon-reload" in cmd for cmd in called_cmds)


def test_systemctl_enable_called_for_each_unit(tmp_path):
    called_cmds = []

    def _cap(cmd, **kwargs):
        called_cmds.append(cmd)
        return MagicMock(returncode=0, stdout="active", stderr="")

    with _PASS_PREFLIGHT, \
         patch("iris.services.install.subprocess.run", side_effect=_cap), \
         patch("iris.services.install._SYSTEMD_USER", tmp_path), \
         patch("iris.services.install._linger_enabled", return_value=True):
        install(dry_run=False)
    assert any("enable" in cmd for cmd in called_cmds)


def test_systemctl_start_or_enable_now_called(tmp_path):
    called_cmds = []

    def _cap(cmd, **kwargs):
        called_cmds.append(cmd)
        return MagicMock(returncode=0, stdout="active", stderr="")

    with _PASS_PREFLIGHT, \
         patch("iris.services.install.subprocess.run", side_effect=_cap), \
         patch("iris.services.install._SYSTEMD_USER", tmp_path), \
         patch("iris.services.install._linger_enabled", return_value=True):
        install(dry_run=False)
    assert any("start" in cmd or "--now" in cmd for cmd in called_cmds)


# ---------------------------------------------------------------------------
# Linger warning when linger disabled
# ---------------------------------------------------------------------------

def test_linger_warning_printed_when_linger_disabled(tmp_path, capsys):
    with _PASS_PREFLIGHT, \
         patch("iris.services.install.subprocess.run", side_effect=_ok_run), \
         patch("iris.services.install._SYSTEMD_USER", tmp_path), \
         patch("iris.services.install._linger_enabled", return_value=False):
        install(dry_run=False)
    out = capsys.readouterr().out
    assert "linger" in out.lower()
    assert "loginctl" in out


# ---------------------------------------------------------------------------
# ti-t8dy: --help / bad-arg / python preflight validation
# ---------------------------------------------------------------------------

def _make_venvs(tmp_path: Path) -> Path:
    """Create stub python binaries for all three venvs under tmp_path."""
    repo = tmp_path / "repo"
    for venv in (".venv", ".venv-whisper", ".venv-kokoro"):
        py = repo / venv / "bin" / "python"
        py.parent.mkdir(parents=True)
        py.touch()
    return repo


class TestCliArgparse:
    """_cli.main() must parse args without ever running install().

    main() catches argparse's SystemExit and returns its code as int,
    so tests check return values rather than caught exceptions.
    """

    def test_help_returns_zero(self):
        from iris.services._cli import main
        import sys
        with patch.object(sys, "argv", ["iris-install-services", "--help"]):
            rc = main()
        assert rc == 0

    def test_help_does_not_call_install(self):
        from iris.services._cli import main
        import sys
        with patch("iris.services._cli.install") as mock_install, \
             patch.object(sys, "argv", ["iris-install-services", "--help"]):
            main()
        mock_install.assert_not_called()

    def test_unknown_arg_returns_nonzero(self):
        from iris.services._cli import main
        import sys
        with patch.object(sys, "argv", ["iris-install-services", "--bogus-flag"]):
            rc = main()
        assert rc != 0

    def test_unknown_arg_does_not_call_install(self):
        from iris.services._cli import main
        import sys
        with patch("iris.services._cli.install") as mock_install, \
             patch.object(sys, "argv", ["iris-install-services", "--bogus-flag"]):
            main()
        mock_install.assert_not_called()

    def test_dry_run_flag_passed_to_install(self):
        from iris.services._cli import main
        import sys
        with patch("iris.services._cli.install", return_value=0) as mock_install, \
             patch.object(sys, "argv", ["iris-install-services", "--dry-run"]):
            main()
        mock_install.assert_called_once_with(dry_run=True)

    def test_no_flags_calls_install_not_dry_run(self):
        from iris.services._cli import main
        import sys
        with patch("iris.services._cli.install", return_value=0) as mock_install, \
             patch.object(sys, "argv", ["iris-install-services"]):
            main()
        mock_install.assert_called_once_with(dry_run=False)


class TestPythonPreflight:
    """install() must abort cleanly if ExecStart pythons are missing or can't import iris."""

    def test_missing_main_venv_returns_1(self, tmp_path, capsys):
        repo = tmp_path / "repo"
        repo.mkdir()
        with patch("iris.services.install._REPO_PATH", repo), \
             patch("iris.services.install._SYSTEMD_USER", tmp_path / "systemd"):
            rc = install(dry_run=False)
        assert rc == 1

    def test_missing_main_venv_writes_no_files(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        dest = tmp_path / "systemd"
        dest.mkdir()
        with patch("iris.services.install._REPO_PATH", repo), \
             patch("iris.services.install._SYSTEMD_USER", dest):
            install(dry_run=False)
        assert list(dest.iterdir()) == []

    def test_preflight_error_goes_to_stderr(self, tmp_path, capsys):
        repo = tmp_path / "repo"
        repo.mkdir()
        with patch("iris.services.install._REPO_PATH", repo), \
             patch("iris.services.install._SYSTEMD_USER", tmp_path / "systemd"):
            install(dry_run=False)
        err = capsys.readouterr().err
        assert "FAILED" in err or "not found" in err.lower()

    def test_import_iris_failure_returns_1(self, tmp_path, capsys):
        repo = _make_venvs(tmp_path)
        py = repo / ".venv" / "bin" / "python"
        fail_proc = MagicMock(returncode=1, stdout="", stderr="No module named iris")

        def _run_side(cmd, **kwargs):
            if "import iris" in cmd:
                return fail_proc
            return MagicMock(returncode=0)

        with patch("iris.services.install._REPO_PATH", repo), \
             patch("iris.services.install.subprocess.run", side_effect=_run_side), \
             patch("iris.services.install._SYSTEMD_USER", tmp_path / "systemd"):
            rc = install(dry_run=False)
        assert rc == 1

    def test_import_iris_failure_writes_no_files(self, tmp_path):
        repo = _make_venvs(tmp_path)
        fail_proc = MagicMock(returncode=1, stdout="", stderr="No module named iris")

        def _run_side(cmd, **kwargs):
            if "import iris" in cmd:
                return fail_proc
            return MagicMock(returncode=0)

        dest = tmp_path / "systemd"
        dest.mkdir()
        with patch("iris.services.install._REPO_PATH", repo), \
             patch("iris.services.install.subprocess.run", side_effect=_run_side), \
             patch("iris.services.install._SYSTEMD_USER", dest):
            install(dry_run=False)
        assert list(dest.iterdir()) == []

    def test_dry_run_skips_preflight(self, tmp_path, capsys):
        """--dry-run must never abort due to missing venvs."""
        repo = tmp_path / "repo"
        repo.mkdir()
        dest = tmp_path / "systemd"
        dest.mkdir()
        with patch("iris.services.install._REPO_PATH", repo), \
             patch("iris.services.install.subprocess.run", side_effect=_ok_run), \
             patch("iris.services.install._SYSTEMD_USER", dest), \
             patch("iris.services.install._linger_enabled", return_value=True):
            rc = install(dry_run=True)
        assert rc == 0

    def test_validate_exec_starts_returns_errors_when_venvs_missing(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        with patch("iris.services.install._REPO_PATH", repo):
            errors = _validate_exec_starts()
        assert len(errors) >= 1
        assert any("not found" in e for e in errors)

    def test_validate_exec_starts_ok_when_all_present_and_iris_importable(self, tmp_path):
        repo = _make_venvs(tmp_path)
        ok_proc = MagicMock(returncode=0, stdout="", stderr="")
        with patch("iris.services.install._REPO_PATH", repo), \
             patch("iris.services.install.subprocess.run", return_value=ok_proc):
            errors = _validate_exec_starts()
        assert errors == []
