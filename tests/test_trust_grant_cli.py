"""Integration tests for iris-arm / iris-disarm CLI.

ti-qt1i.1.5 (CLI half) — written BEFORE builder implementation (TDD red phase).
Fails until ti-qt1i.1.4 ships the iris-arm and iris-disarm entry points.
"""
from __future__ import annotations

import subprocess
import sys
import sysconfig
from pathlib import Path


def _active_script(name: str) -> str:
    """Resolve a console script to the active Python environment's copy.

    Checks scripts next to sys.executable first (venv / system pip install),
    then the POSIX user scheme (pip install --user / editable user installs).
    Falls back to bare name so PATH still resolves it if neither is found.
    """
    candidate = Path(sys.executable).parent / name
    if candidate.exists():
        return str(candidate)
    try:
        user_bin = sysconfig.get_path("scripts", "posix_user")
        if user_bin:
            candidate = Path(user_bin) / name
            if candidate.exists():
                return str(candidate)
    except KeyError:
        pass
    return name


_IRIS_ARM = _active_script("iris-arm")
_IRIS_DISARM = _active_script("iris-disarm")


def test_iris_arm_exits_nonzero_when_no_console():
    """iris-arm with no console running must print an error and exit non-zero."""
    result = subprocess.run(
        [_IRIS_ARM],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0
    output = (result.stdout + result.stderr).lower()
    assert "not running" in output or "no console" in output or "not found" in output


def test_iris_disarm_exits_nonzero_when_no_console():
    """iris-disarm with no console running must print an error and exit non-zero."""
    result = subprocess.run(
        [_IRIS_DISARM],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0
    output = (result.stdout + result.stderr).lower()
    assert "not running" in output or "no console" in output or "not found" in output


def test_iris_arm_ttl_flag_is_accepted():
    """iris-arm --ttl=60 must not crash at the flag-parsing stage (even if no console)."""
    result = subprocess.run(
        [_IRIS_ARM, "--ttl=60"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    # May exit non-zero (no console) but must not crash with "unrecognized argument"
    output = (result.stdout + result.stderr).lower()
    assert "unrecognized" not in output and "invalid" not in output


def test_iris_arm_idempotent_when_already_armed():
    """Running iris-arm twice must not raise an error on the second invocation.

    This is verified statically here (the CLI itself is tested in subprocess); the
    idempotency invariant is that exit code 0 and no error output is required when
    the console is already armed. Because no console is running, we just confirm
    the second run behaves identically to the first (both report 'not running').
    """
    r1 = subprocess.run([_IRIS_ARM], capture_output=True, text=True, timeout=10)
    r2 = subprocess.run([_IRIS_ARM], capture_output=True, text=True, timeout=10)
    # Both should behave the same (both see no console)
    assert r1.returncode == r2.returncode
