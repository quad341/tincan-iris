"""Tests for iris/console/diagnostics.py — crash/bug-report diagnostics (ti-oqlyk).

Every function in this module is exception-safe end-to-end by design (it runs
during already-exceptional conditions) -- persist_crash's never-raise test
forces internal failures specifically to prove that guarantee, not just
exercise the happy path.
"""
from __future__ import annotations

import json
import stat
import sys
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from iris.console import diagnostics


@pytest.fixture(autouse=True)
def _reset_active_app():
    yield
    diagnostics.clear_active_app()


@pytest.fixture(autouse=True)
def _restore_hooks():
    orig_sys_hook = sys.excepthook
    orig_thread_hook = threading.excepthook
    yield
    sys.excepthook = orig_sys_hook
    threading.excepthook = orig_thread_hook


# ---------------------------------------------------------------------------
# write_bug_report
# ---------------------------------------------------------------------------

def test_write_bug_report_manual_trigger_omits_crash_record(tmp_path, monkeypatch):
    monkeypatch.setenv("IRIS_HOME", str(tmp_path))
    path = diagnostics.write_bug_report("manual")

    assert path is not None
    assert path.exists()
    assert path.parent == tmp_path / "bug-reports"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600

    report = json.loads(path.read_text())
    assert report["schema"] == "iris-bug-report-v1"
    assert report["trigger"] == "manual"
    assert "crash_record" not in report


def test_write_bug_report_crash_trigger_includes_crash_record(tmp_path, monkeypatch):
    monkeypatch.setenv("IRIS_HOME", str(tmp_path))
    crash_record = {
        "timestamp_iso": "2026-07-04T00:00:00", "source": "main", "traceback": "Traceback...",
    }

    path = diagnostics.write_bug_report("crash:main", crash_record=crash_record)

    report = json.loads(path.read_text())
    assert report["trigger"] == "crash:main"
    assert report["crash_record"] == crash_record


def test_write_bug_report_degrades_to_none_on_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("IRIS_HOME", str(tmp_path))
    monkeypatch.setattr(
        diagnostics.settings, "iris_home", MagicMock(side_effect=OSError("disk gone"))
    )

    path = diagnostics.write_bug_report("manual")

    assert path is None


# ---------------------------------------------------------------------------
# persist_crash
# ---------------------------------------------------------------------------

def test_persist_crash_appends_to_log_and_writes_bug_report(tmp_path, monkeypatch):
    monkeypatch.setenv("IRIS_HOME", str(tmp_path))
    log_path = tmp_path / "console.log"
    diagnostics.set_active_app(
        SimpleNamespace(_logf=None, _logpath=str(log_path), _last_error="")
    )

    try:
        raise ValueError("boom")
    except ValueError as exc:
        diagnostics.persist_crash("main", exc)

    log_text = log_path.read_text()
    assert "CRASH (main)" in log_text
    assert "ValueError: boom" in log_text

    reports = list((tmp_path / "bug-reports").glob("bug-*.json"))
    assert len(reports) == 1
    report = json.loads(reports[0].read_text())
    assert report["trigger"] == "crash:main"
    assert report["crash_record"]["source"] == "main"
    assert "ValueError: boom" in report["crash_record"]["traceback"]


def test_persist_crash_never_raises_when_internals_fail(monkeypatch):
    monkeypatch.setattr(
        diagnostics, "_append_to_log", MagicMock(side_effect=RuntimeError("log broke"))
    )
    monkeypatch.setattr(
        diagnostics, "write_bug_report", MagicMock(side_effect=RuntimeError("report broke"))
    )

    try:
        raise ValueError("boom")
    except ValueError as exc:
        diagnostics.persist_crash("main", exc)  # must not raise


# ---------------------------------------------------------------------------
# install_exception_hooks
# ---------------------------------------------------------------------------

def test_sys_excepthook_persists_crash_and_delegates(monkeypatch):
    persist_mock = MagicMock()
    monkeypatch.setattr(diagnostics, "persist_crash", persist_mock)
    delegate_mock = MagicMock()
    monkeypatch.setattr(sys, "__excepthook__", delegate_mock)

    diagnostics.install_exception_hooks()

    exc = ValueError("boom")
    sys.excepthook(ValueError, exc, None)

    persist_mock.assert_called_once_with("main", exc)
    delegate_mock.assert_called_once_with(ValueError, exc, None)


def test_threading_excepthook_persists_crash_and_delegates(monkeypatch):
    persist_mock = MagicMock()
    monkeypatch.setattr(diagnostics, "persist_crash", persist_mock)
    delegate_mock = MagicMock()
    monkeypatch.setattr(threading, "__excepthook__", delegate_mock)

    diagnostics.install_exception_hooks()

    exc = ValueError("boom")
    args = threading.ExceptHookArgs((ValueError, exc, None, None))
    threading.excepthook(args)

    persist_mock.assert_called_once_with("thread", exc)
    delegate_mock.assert_called_once_with(args)


# ---------------------------------------------------------------------------
# _gather_app_state / _gather_last_error
# ---------------------------------------------------------------------------

def test_gather_app_state_no_active_app_returns_all_none():
    assert diagnostics._gather_app_state() == {
        "mode": None, "in_call": None, "dnd": None, "trust_state": None, "contact_name": None,
    }


def test_gather_last_error_no_active_app_returns_empty_string():
    assert diagnostics._gather_last_error() == ""


def test_gather_app_state_extracts_from_active_app():
    fake_trust = SimpleNamespace(name="FULL")
    fake_app = SimpleNamespace(
        _mode="proxy", _in_call=True, _dnd=False,
        conductor=SimpleNamespace(far_trust=fake_trust),
        _call_contact_name="Mom",
    )
    diagnostics.set_active_app(fake_app)

    assert diagnostics._gather_app_state() == {
        "mode": "proxy", "in_call": True, "dnd": False,
        "trust_state": "FULL", "contact_name": "Mom",
    }


def test_gather_app_state_empty_contact_name_and_no_trust_become_none():
    fake_app = SimpleNamespace(
        _mode="direct", _in_call=False, _dnd=True,
        conductor=SimpleNamespace(far_trust=None),
        _call_contact_name="",
    )
    diagnostics.set_active_app(fake_app)

    state = diagnostics._gather_app_state()
    assert state["contact_name"] is None
    assert state["trust_state"] is None


def test_gather_last_error_extracts_from_active_app():
    diagnostics.set_active_app(SimpleNamespace(_last_error="boom"))
    assert diagnostics._gather_last_error() == "boom"


# ---------------------------------------------------------------------------
# _tail_lines
# ---------------------------------------------------------------------------

def test_tail_lines_returns_last_n_lines(tmp_path):
    log = tmp_path / "console.log"
    log.write_text("\n".join(f"line{i}" for i in range(10)) + "\n")

    assert diagnostics._tail_lines(str(log), 3) == ["line7", "line8", "line9"]


def test_tail_lines_missing_path_returns_empty_list(tmp_path):
    missing = tmp_path / "does-not-exist.log"
    assert diagnostics._tail_lines(str(missing), 10) == []


# ---------------------------------------------------------------------------
# log_path() / last_crash_bug_report() -- public accessors (ti-00jr4.2)
# ---------------------------------------------------------------------------

def test_log_path_delegates_to_internal_log_path(monkeypatch):
    monkeypatch.setattr(diagnostics, "_log_path", lambda: "/tmp/console.log")
    assert diagnostics.log_path() == "/tmp/console.log"


def test_last_crash_bug_report_returns_current_module_state(monkeypatch):
    from pathlib import Path

    monkeypatch.setattr(diagnostics, "_last_crash_bug_report", Path("/tmp/bug-1.json"))
    assert diagnostics.last_crash_bug_report() == Path("/tmp/bug-1.json")


def test_last_crash_bug_report_reflects_most_recent_persist_crash_call(tmp_path, monkeypatch):
    monkeypatch.setenv("IRIS_HOME", str(tmp_path))
    diagnostics.set_active_app(
        SimpleNamespace(_logf=None, _logpath=str(tmp_path / "console.log"), _last_error="")
    )

    try:
        raise ValueError("first")
    except ValueError as exc:
        diagnostics.persist_crash("main", exc)

    first_report = diagnostics.last_crash_bug_report()
    assert first_report is not None
    assert first_report.exists()

    monkeypatch.setattr(diagnostics, "write_bug_report", lambda *a, **kw: None)
    try:
        raise ValueError("second")
    except ValueError as exc:
        diagnostics.persist_crash("main", exc)

    assert diagnostics.last_crash_bug_report() is None
