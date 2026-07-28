"""Smoke tests for iris daemon + iris dnd CLI subcommands (ti-gxpt.6).

Tests:
  - iris daemon start/stop/status (smoke: not-running paths without a real daemon)
  - iris dnd on/off/until (smoke: not-running error path)
  - dnd time parser: all 5 input formats
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

from iris.daemon._cli import (
    _daemon_start,
    _dnd_off,
    _dnd_on,
    _dnd_until,
    _parse_until,
    daemon_main,
    dnd_main,
)
from iris.daemon.proxy import DaemonNotRunning

# ---------------------------------------------------------------------------
# _parse_until — time parsing (no daemon required)
# ---------------------------------------------------------------------------


def test_parse_relative_minutes():
    before = time.time()
    result = _parse_until("30m")
    assert result is not None
    assert abs(result - (before + 1800)) < 2


def test_parse_relative_hours():
    before = time.time()
    result = _parse_until("2h")
    assert result is not None
    assert abs(result - (before + 7200)) < 2


def test_parse_relative_hours_and_minutes():
    before = time.time()
    result = _parse_until("2h30m")
    assert result is not None
    assert abs(result - (before + 9000)) < 2


def test_parse_24h_time():
    result = _parse_until("18:00")
    assert result is not None
    import datetime
    dt = datetime.datetime.fromtimestamp(result)
    assert dt.hour == 18
    assert dt.minute == 0


def test_parse_12h_pm():
    result = _parse_until("6pm")
    assert result is not None
    import datetime
    dt = datetime.datetime.fromtimestamp(result)
    assert dt.hour == 18


def test_parse_12h_am():
    result = _parse_until("9am")
    assert result is not None
    import datetime
    dt = datetime.datetime.fromtimestamp(result)
    assert dt.hour == 9


def test_parse_12pm_noon():
    result = _parse_until("12pm")
    assert result is not None
    import datetime
    dt = datetime.datetime.fromtimestamp(result)
    assert dt.hour == 12


def test_parse_12am_midnight():
    result = _parse_until("12am")
    assert result is not None
    import datetime
    dt = datetime.datetime.fromtimestamp(result)
    assert dt.hour == 0


def test_parse_unknown_returns_none():
    assert _parse_until("tomorrow 9am") is None
    assert _parse_until("never") is None
    assert _parse_until("") is None


# ---------------------------------------------------------------------------
# iris dnd: daemon not running path
# ---------------------------------------------------------------------------


def _make_not_running_proxy():
    proxy = MagicMock()
    proxy.connect.side_effect = DaemonNotRunning("Iris daemon is not running.")
    return proxy


def test_dnd_on_not_running(capsys):
    with patch("iris.daemon._cli.DaemonProxy", return_value=_make_not_running_proxy()):
        rc = _dnd_on()
    assert rc == 1
    out = capsys.readouterr().out
    assert "not running" in out.lower() or "not running" in out


def test_dnd_off_not_running(capsys):
    with patch("iris.daemon._cli.DaemonProxy", return_value=_make_not_running_proxy()):
        rc = _dnd_off()
    assert rc == 1


def test_dnd_until_not_running(capsys):
    with patch("iris.daemon._cli.DaemonProxy", return_value=_make_not_running_proxy()):
        rc = _dnd_until("2h")
    assert rc == 1


# ---------------------------------------------------------------------------
# iris dnd: successful round-trips (mock proxy)
# ---------------------------------------------------------------------------


def _make_proxy_for(ack: dict):
    proxy = MagicMock()
    proxy.connect.return_value = None
    proxy.send.return_value = ack
    return proxy


def test_dnd_on_success(capsys):
    with patch("iris.daemon._cli.DaemonProxy",
               return_value=_make_proxy_for({"ok": True, "ack": "dnd",
                                            "posture": {"dnd": True, "expires_in_s": None}})):
        rc = _dnd_on()
    assert rc == 0
    out = capsys.readouterr().out
    assert "DND ON" in out


def test_dnd_off_success(capsys):
    with patch("iris.daemon._cli.DaemonProxy",
               return_value=_make_proxy_for({"ok": True, "ack": "dnd",
                                            "posture": {"dnd": False, "expires_in_s": None}})):
        rc = _dnd_off()
    assert rc == 0
    out = capsys.readouterr().out
    assert "DND OFF" in out


def test_dnd_until_success(capsys):
    future = time.time() + 7200
    import datetime
    expected_time = datetime.datetime.fromtimestamp(future).strftime("%H:%M")
    with patch("iris.daemon._cli.DaemonProxy",
               return_value=_make_proxy_for({"ok": True, "ack": "dnd",
                                            "posture": {"dnd": True, "expires_in_s": 7200}})):
        rc = _dnd_until("2h")
    assert rc == 0
    out = capsys.readouterr().out
    assert "DND ON" in out
    assert expected_time in out


def test_dnd_until_past_time(capsys):
    rc = _dnd_until("0m")
    assert rc == 2
    out = capsys.readouterr().out
    assert "past" in out.lower() or "past" in out


# ---------------------------------------------------------------------------
# iris daemon status: not running path
# ---------------------------------------------------------------------------


def test_daemon_status_not_running(capsys):
    with patch("iris.daemon._cli._daemon_running", return_value=None):
        import sys
        sys.argv = ["iris daemon", "status"]
        rc = daemon_main(["status"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "not running" in out.lower()
    assert "iris daemon start" in out


# ---------------------------------------------------------------------------
# iris daemon status: pid cross-check (ti-qlbi0)
# ---------------------------------------------------------------------------


def _status_ack(pid: int) -> dict:
    return {"ok": True, "ack": "status", "state": {
        "call": "idle", "posture": {"dnd": False, "busy": False}, "clients": 0, "pid": pid,
    }}


def test_daemon_status_pid_match_no_warning(capsys):
    with patch("iris.daemon._cli._daemon_running", return_value=4242), \
         patch("iris.daemon._cli.DaemonProxy", return_value=_make_proxy_for(_status_ack(4242))):
        rc = daemon_main(["status"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "stale" not in out.lower()


def test_daemon_status_pid_mismatch_warns(capsys):
    """The exact stale/orphaned state ti-qlbi0 fixes: pid file and socket disagree."""
    with patch("iris.daemon._cli._daemon_running", return_value=4242), \
         patch("iris.daemon._cli.DaemonProxy", return_value=_make_proxy_for(_status_ack(9999))):
        rc = daemon_main(["status"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "stale" in out.lower()
    assert "4242" in out
    assert "9999" in out


# ---------------------------------------------------------------------------
# iris daemon start: socket-probe pre-flight + pid-matching readiness wait (ti-qlbi0)
# ---------------------------------------------------------------------------


def test_daemon_start_already_running(capsys):
    with patch("iris.daemon._cli._probe_daemon", return_value=4242):
        rc = _daemon_start()
    assert rc == 0
    out = capsys.readouterr().out
    assert "already running" in out.lower()
    assert "4242" in out


def test_daemon_start_success_pid_matches(tmp_path, capsys):
    fake_proc = MagicMock()
    fake_proc.pid = 5555
    with patch("iris.daemon._cli._probe_daemon", side_effect=[None, 5555]), \
         patch("iris.daemon._cli.subprocess.Popen", return_value=fake_proc), \
         patch("iris.daemon._cli._LOG_PATH", tmp_path / "daemon.log"):
        rc = _daemon_start()
    assert rc == 0
    out = capsys.readouterr().out
    assert "5555" in out


def test_daemon_start_pid_mismatch_fails_loudly(tmp_path, capsys):
    """We lost the startup race: a different pid answers than the one we spawned."""
    fake_proc = MagicMock()
    fake_proc.pid = 5555
    with patch("iris.daemon._cli._probe_daemon", side_effect=[None, 9999]), \
         patch("iris.daemon._cli.subprocess.Popen", return_value=fake_proc), \
         patch("iris.daemon._cli._LOG_PATH", tmp_path / "daemon.log"):
        rc = _daemon_start()
    assert rc == 3
    out = capsys.readouterr().out
    assert "9999" in out
    assert "different daemon" in out.lower()


def _instant_clock(step: float = 1.0):
    ticks = [0.0]

    def _tick() -> float:
        ticks[0] += step
        return ticks[0]

    return _tick


def test_daemon_start_timeout_surfaces_log_tail(tmp_path, capsys):
    fake_proc = MagicMock()
    fake_proc.pid = 5555
    log_path = tmp_path / "daemon.log"
    log_path.write_text("iris.daemon ERROR another instance holds the lock (pid 123)\n")
    with patch("iris.daemon._cli._probe_daemon", return_value=None), \
         patch("iris.daemon._cli.subprocess.Popen", return_value=fake_proc), \
         patch("iris.daemon._cli._LOG_PATH", log_path), \
         patch("iris.daemon._cli.time.sleep", lambda _s: None), \
         patch("iris.daemon._cli.time.monotonic", side_effect=_instant_clock()):
        rc = _daemon_start()
    assert rc == 3
    out = capsys.readouterr().out
    assert "socket not ready" in out.lower()
    assert "another instance holds the lock" in out.lower()


# ---------------------------------------------------------------------------
# iris dnd main dispatch
# ---------------------------------------------------------------------------


def test_dnd_main_no_args(capsys):
    rc = dnd_main([])
    assert rc == 0
    out = capsys.readouterr().out
    assert "usage" in out.lower()


def test_dnd_main_unknown_subcommand(capsys):
    rc = dnd_main(["frobnicate"])
    assert rc == 2


def test_daemon_main_no_args(capsys):
    rc = daemon_main([])
    assert rc == 0
    out = capsys.readouterr().out
    assert "usage" in out.lower()


def test_daemon_main_unknown_subcommand():
    rc = daemon_main(["frobnicate"])
    assert rc == 2
