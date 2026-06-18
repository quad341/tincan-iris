"""Tests for iris install-services unit file generation (ti-qxel.3).

These tests verify the existing iris/services/install.py and document the
additional behaviors the builder must add (marked with # TDD: builder must...).
All filesystem writes and subprocess calls are controlled via tmp_path + mocks.
"""
from __future__ import annotations

import io
import os
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from iris.services.install import install, UNITS


def _ok_run(cmd, **kwargs):
    """Mock subprocess.run that always succeeds."""
    return MagicMock(returncode=0, stdout="active", stderr="")


# ---------------------------------------------------------------------------
# Template variable substitution
# ---------------------------------------------------------------------------

def test_repo_path_substituted_in_unit_file(tmp_path):
    with patch("iris.services.install.subprocess.run", side_effect=_ok_run), \
         patch("iris.services.install._SYSTEMD_USER", tmp_path), \
         patch("iris.services.install._linger_enabled", return_value=True):
        install(dry_run=False)
    for unit_path in tmp_path.iterdir():
        content = unit_path.read_text()
        assert "{REPO_PATH}" not in content


def test_user_home_substituted_in_unit_file(tmp_path):
    with patch("iris.services.install.subprocess.run", side_effect=_ok_run), \
         patch("iris.services.install._SYSTEMD_USER", tmp_path), \
         patch("iris.services.install._linger_enabled", return_value=True):
        install(dry_run=False)
    for unit_path in tmp_path.iterdir():
        content = unit_path.read_text()
        assert "{USER_HOME}" not in content


def test_python_whisper_substituted(tmp_path):
    with patch("iris.services.install.subprocess.run", side_effect=_ok_run), \
         patch("iris.services.install._SYSTEMD_USER", tmp_path), \
         patch("iris.services.install._linger_enabled", return_value=True):
        install(dry_run=False)
    whisper_unit = tmp_path / "iris-whisper.service"
    if whisper_unit.exists():
        content = whisper_unit.read_text()
        assert "{PYTHON_WHISPER}" not in content
        assert ".venv-whisper" in content or "python" in content.lower()


def test_python_kokoro_substituted(tmp_path):
    with patch("iris.services.install.subprocess.run", side_effect=_ok_run), \
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
    with patch("iris.services.install.subprocess.run", side_effect=_ok_run), \
         patch("iris.services.install._SYSTEMD_USER", tmp_path), \
         patch("iris.services.install._linger_enabled", return_value=True):
        install(dry_run=False)
        capsys.readouterr()  # discard first run output
        install(dry_run=False)
    out = capsys.readouterr().out
    assert "unchanged" in out.lower()


def test_modified_unit_shows_updated(tmp_path, capsys):
    with patch("iris.services.install.subprocess.run", side_effect=_ok_run), \
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
        install(dry_run=True)
    out = capsys.readouterr().out
    assert "[dry-run]" in out


def test_dry_run_does_not_write_files(tmp_path):
    dest = tmp_path / "systemd"
    dest.mkdir()
    with patch("iris.services.install.subprocess.run", side_effect=_ok_run), \
         patch("iris.services.install._SYSTEMD_USER", dest), \
         patch("iris.services.install._linger_enabled", return_value=True):
        install(dry_run=True)
    assert list(dest.iterdir()) == []


# ---------------------------------------------------------------------------
# systemctl invocations
# ---------------------------------------------------------------------------

def test_systemctl_daemon_reload_called(tmp_path):
    called_cmds = []

    def _cap(cmd, **kwargs):
        called_cmds.append(cmd)
        return MagicMock(returncode=0, stdout="active", stderr="")

    with patch("iris.services.install.subprocess.run", side_effect=_cap), \
         patch("iris.services.install._SYSTEMD_USER", tmp_path), \
         patch("iris.services.install._linger_enabled", return_value=True):
        install(dry_run=False)
    assert any("daemon-reload" in cmd for cmd in called_cmds)


def test_systemctl_enable_called_for_each_unit(tmp_path):
    called_cmds = []

    def _cap(cmd, **kwargs):
        called_cmds.append(cmd)
        return MagicMock(returncode=0, stdout="active", stderr="")

    with patch("iris.services.install.subprocess.run", side_effect=_cap), \
         patch("iris.services.install._SYSTEMD_USER", tmp_path), \
         patch("iris.services.install._linger_enabled", return_value=True):
        install(dry_run=False)
    assert any("enable" in cmd for cmd in called_cmds)


def test_systemctl_start_or_enable_now_called(tmp_path):
    called_cmds = []

    def _cap(cmd, **kwargs):
        called_cmds.append(cmd)
        return MagicMock(returncode=0, stdout="active", stderr="")

    with patch("iris.services.install.subprocess.run", side_effect=_cap), \
         patch("iris.services.install._SYSTEMD_USER", tmp_path), \
         patch("iris.services.install._linger_enabled", return_value=True):
        install(dry_run=False)
    assert any("start" in cmd or "--now" in cmd for cmd in called_cmds)


# ---------------------------------------------------------------------------
# Linger warning when linger disabled
# ---------------------------------------------------------------------------

def test_linger_warning_printed_when_linger_disabled(tmp_path, capsys):
    with patch("iris.services.install.subprocess.run", side_effect=_ok_run), \
         patch("iris.services.install._SYSTEMD_USER", tmp_path), \
         patch("iris.services.install._linger_enabled", return_value=False):
        install(dry_run=False)
    out = capsys.readouterr().out
    assert "linger" in out.lower()
    assert "loginctl" in out
