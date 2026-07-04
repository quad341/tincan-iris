"""Regression test: daemon exclusivity — flock scoped with the socket (ti-qlbi0).

Two real ``python -m iris.daemon`` subprocesses, sharing one XDG_RUNTIME_DIR but
each with a DIFFERENT $HOME — the exact gc per-agent-sandbox scenario that let
two daemons collide on the same socket / D-Bus session bus while each believed
it was the only instance (a $HOME-scoped pid file diverging from a UID/session-
scoped socket). The flock must serialize them regardless of $HOME: exactly one
wins, the loser exits nonzero having never reached the socket bind.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path


def _daemon_env(tmp_path: Path, home_suffix: str, runtime_dir: Path) -> dict:
    env = os.environ.copy()
    env["XDG_RUNTIME_DIR"] = str(runtime_dir)
    env["HOME"] = str(tmp_path / f"home_{home_suffix}")
    env.pop("IRIS_DAEMON_SOCK", None)
    env.pop("IRIS_DB", None)
    env["IRIS_CALL_CARD"] = "0"  # keep the race focused on the lock, not Call Card startup
    return env


def test_two_subprocesses_race_for_the_lock_exactly_one_wins(tmp_path):
    runtime_dir = tmp_path / "run"
    runtime_dir.mkdir()
    sock_path = runtime_dir / "iris" / "daemon.sock"
    pid_path = runtime_dir / "iris" / "daemon.pid"

    env_a = _daemon_env(tmp_path, "a", runtime_dir)
    env_b = _daemon_env(tmp_path, "b", runtime_dir)
    assert env_a["HOME"] != env_b["HOME"]  # the exact bug scenario: shared scope, different $HOME

    log_a = (tmp_path / "a.log").open("w")
    log_b = (tmp_path / "b.log").open("w")
    procs = {
        "a": subprocess.Popen(
            [sys.executable, "-m", "iris.daemon"], env=env_a, stdout=log_a, stderr=log_a,
        ),
        "b": subprocess.Popen(
            [sys.executable, "-m", "iris.daemon"], env=env_b, stdout=log_b, stderr=log_b,
        ),
    }

    try:
        loser_name = None
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and loser_name is None:
            for name, proc in procs.items():
                if proc.poll() is not None:
                    loser_name = name
                    break
            if loser_name is None:
                time.sleep(0.05)

        assert loser_name is not None, "neither process exited — the lock did not serialize them"
        winner_name = "b" if loser_name == "a" else "a"
        loser, winner = procs[loser_name], procs[winner_name]

        assert loser.returncode not in (0, None), (
            f"loser (subprocess {loser_name}) exited {loser.returncode}, expected nonzero"
        )
        assert winner.poll() is None, "winner exited too — exactly one should survive the race"

        log_a.flush()
        log_b.flush()
        loser_log = (log_a if loser_name == "a" else log_b).name
        loser_text = Path(loser_log).read_text().lower()
        assert "lock" in loser_text, f"expected a lock-conflict message, got: {loser_text!r}"

        # The winner, given time, actually binds the socket and its pid is the one recorded.
        socket_deadline = time.monotonic() + 10.0
        while time.monotonic() < socket_deadline and not sock_path.exists():
            time.sleep(0.1)
        assert sock_path.exists(), "winner never bound the socket"
        assert pid_path.read_text().strip() == str(winner.pid)
    finally:
        for proc in procs.values():
            if proc.poll() is None:
                proc.terminate()
        for proc in procs.values():
            try:
                proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5.0)
        log_a.close()
        log_b.close()
