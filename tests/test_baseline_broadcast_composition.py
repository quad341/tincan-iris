"""Regression tests for BaselineHeartbeat's on_transition composition and the
daemon-side baseline broadcast shape (ti-pugo3.3.3).

Covers the daemon half of ti-pugo3.3.1: iris/daemon/__main__.py composes
degradation_notify.on_baseline_transition (ti-pugo3.2's desktop notifications)
and DaemonAPI._on_baseline_transition (the console broadcast) by hand into a
single on_transition= closure, since BaselineHeartbeat only accepts one
callback. This is a deliberate regression guard per ti-pugo3.3's DESIGN: a
future refactor could easily reintroduce a single-callback-only bug that
silently drops one of the two consumers. main() itself wires up the whole
daemon process and isn't independently unit-testable, so the composition
guard inspects the closure's AST rather than calling main().

Per this rig's convention, the validator authors these tests; the daemon
composition and broadcast implementation are already complete and unmodified
here.
"""
from __future__ import annotations

import ast
import inspect
from unittest.mock import MagicMock

from iris.daemon import __main__ as daemon_main
from iris.daemon.api import DaemonAPI
from iris.daemon.heartbeat import BaselineStatus
from iris.doctor import AssetCheckResult, DoctorStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dotted_call_name(node: ast.Call) -> str | None:
    """Dotted name of a Call's target, e.g. 'degradation_notify.on_baseline_transition'."""
    func = node.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return f"{func.value.id}.{func.attr}"
    return None


def _find_closure() -> ast.FunctionDef:
    """Locate the _on_baseline_transition closure nested inside main()."""
    source = inspect.getsource(daemon_main.main)
    tree = ast.parse(source)
    closures = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_on_baseline_transition"
    ]
    assert len(closures) == 1, (
        "expected exactly one _on_baseline_transition closure inside main(); "
        f"found {len(closures)} -- has the composition been refactored?"
    )
    return closures[0]


def _api() -> DaemonAPI:
    """A DaemonAPI with no real socket/posture -- only used for its plain
    Python methods (_on_baseline_transition, _status_payload); never started."""
    return DaemonAPI(posture=MagicMock(), engine=MagicMock(), socket_path=None)


# ---------------------------------------------------------------------------
# Source-inspection guard: main()'s composition closure calls BOTH consumers
# ---------------------------------------------------------------------------


def test_baseline_transition_closure_composes_both_consumers():
    """The closure must call both degradation_notify.on_baseline_transition(...)
    and api._on_baseline_transition(...) -- dropping either silently would
    drop a consumer (desktop notifications or the console broadcast)."""
    closure = _find_closure()
    calls = {_dotted_call_name(node) for node in ast.walk(closure) if isinstance(node, ast.Call)}
    assert "degradation_notify.on_baseline_transition" in calls, (
        f"closure no longer calls degradation_notify.on_baseline_transition; calls found: {calls}"
    )
    assert "api._on_baseline_transition" in calls, (
        f"closure no longer calls api._on_baseline_transition; calls found: {calls}"
    )


def test_baseline_transition_closure_passes_new_and_previous_through():
    """Both consumers must receive the same (new, previous) pair the closure
    itself was given, in order -- not a transformed/partial/reordered view."""
    closure = _find_closure()
    calls = [node for node in ast.walk(closure) if isinstance(node, ast.Call)]
    assert len(calls) == 2, f"expected exactly 2 calls in the closure body; found {len(calls)}"
    for call in calls:
        arg_names = [a.id for a in call.args if isinstance(a, ast.Name)]
        assert arg_names == ["new", "previous"], (
            f"expected call to forward (new, previous) unchanged; got args {arg_names} "
            f"for {_dotted_call_name(call)}"
        )


# ---------------------------------------------------------------------------
# Behavioral guard: DaemonAPI._on_baseline_transition's broadcast shape
# ---------------------------------------------------------------------------


def test_on_baseline_transition_broadcasts_baseline_event():
    api = _api()
    api.broadcast = MagicMock()

    checks = [
        AssetCheckResult("iris-whisper", DoctorStatus.OK, required=True, detail="running"),
        AssetCheckResult(
            "iris-kokoro",
            DoctorStatus.DOWN,
            required=True,
            detail="not running",
            fix="systemctl --user start iris-kokoro",
        ),
        AssetCheckResult("call-card-enrichment", DoctorStatus.DOWN, required=False, detail="meh"),
    ]
    status = BaselineStatus(level="red", checks=checks, checked_at=1234.5)

    api._on_baseline_transition(status, None)

    api.broadcast.assert_called_once()
    event = api.broadcast.call_args[0][0]
    assert event == {
        "event": "baseline",
        "level": "red",
        "checked_at": 1234.5,
        # Only required+non-ok checks count as "failing" -- the optional
        # broken check must not appear here.
        "failing": ["iris-kokoro"],
        "checks": [
            {"name": "iris-whisper", "status": "ok", "required": True, "detail": "running", "fix": ""},
            {
                "name": "iris-kokoro",
                "status": "down",
                "required": True,
                "detail": "not running",
                "fix": "systemctl --user start iris-kokoro",
            },
            {
                "name": "call-card-enrichment",
                "status": "down",
                "required": False,
                "detail": "meh",
                "fix": "",
            },
        ],
    }


def test_on_baseline_transition_all_ok_reports_no_failing():
    api = _api()
    api.broadcast = MagicMock()
    checks = [AssetCheckResult("iris-whisper", DoctorStatus.OK, required=True)]
    status = BaselineStatus(level="green", checks=checks, checked_at=1.0)

    api._on_baseline_transition(status, None)

    event = api.broadcast.call_args[0][0]
    assert event["failing"] == []


def test_on_baseline_transition_ignores_previous_arg_in_payload():
    """previous is only used by callers (e.g. degradation_notify) to detect
    edges -- the broadcast payload itself must describe new only."""
    api = _api()
    api.broadcast = MagicMock()
    old_checks = [AssetCheckResult("iris-whisper", DoctorStatus.DOWN, required=True)]
    previous = BaselineStatus(level="red", checks=old_checks, checked_at=1.0)
    new_checks = [AssetCheckResult("iris-whisper", DoctorStatus.OK, required=True)]
    new = BaselineStatus(level="green", checks=new_checks, checked_at=2.0)

    api._on_baseline_transition(new, previous)

    event = api.broadcast.call_args[0][0]
    assert event["level"] == "green"
    assert event["checked_at"] == 2.0
