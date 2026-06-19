"""Integration tests for iris-arm / iris-disarm CLI.

Invokes the entry-point functions via the test interpreter (``sys.executable
-c``) rather than a bare ``iris-arm`` PATH lookup, so the tests exercise THIS
package's code and are immune to a stale console-script earlier on PATH (e.g. an
old ~/.local/bin shim built against a different environment).
"""
from __future__ import annotations

import subprocess
import sys


def _run_cli(entry: str, *args: str) -> subprocess.CompletedProcess:
    """Run ``iris.console.arm:<entry>`` in a subprocess on this interpreter.

    Mirrors the console_script wrapper (``sys.exit(entry())``) so the exit code
    is the entry point's, without depending on an installed script on PATH.
    """
    code = f"import sys; from iris.console.arm import {entry}; sys.exit({entry}())"
    return subprocess.run(
        [sys.executable, "-c", code, *args],
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_iris_arm_exits_nonzero_when_no_console():
    """iris-arm with no console running must print an error and exit non-zero."""
    result = _run_cli("arm_main")
    assert result.returncode != 0
    output = (result.stdout + result.stderr).lower()
    assert "not running" in output or "no console" in output or "not found" in output


def test_iris_disarm_exits_nonzero_when_no_console():
    """iris-disarm with no console running must print an error and exit non-zero."""
    result = _run_cli("disarm_main")
    assert result.returncode != 0
    output = (result.stdout + result.stderr).lower()
    assert "not running" in output or "no console" in output or "not found" in output


def test_iris_arm_ttl_flag_is_accepted():
    """iris-arm --ttl=60 must not crash at the flag-parsing stage (even if no console)."""
    result = _run_cli("arm_main", "--ttl=60")
    # May exit non-zero (no console) but must not crash with "unrecognized argument"
    output = (result.stdout + result.stderr).lower()
    assert "unrecognized" not in output and "invalid" not in output


def test_iris_arm_idempotent_when_already_armed():
    """Running iris-arm twice must behave identically (both see no console)."""
    r1 = _run_cli("arm_main")
    r2 = _run_cli("arm_main")
    assert r1.returncode == r2.returncode
