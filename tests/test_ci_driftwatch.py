"""Tests for scripts/ci_driftwatch.py (ti-4tq52).

These tests FAIL until the builder implements scripts/ci_driftwatch.py — that
module does not exist yet. See ti-pcqj4 for the full design (state machine,
trade-offs): a `schedule:`-triggered poller that detects main CI staying red
across ticks with no new commit (which push-triggered CI, and sibling
main-ci-watcher, structurally cannot see), confirms via one automatic rerun
to rule out a flake, then alerts + files a P1 bead.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "ci_driftwatch.py"

REPO = "quad341/tincan-iris"
NOW = datetime(2026, 7, 28, 12, 0, 0, tzinfo=timezone.utc)


class FakeCompleted:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def _fake_run(rules):
    """subprocess.run stand-in: first argv-prefix match in `rules` wins.

    A rule's response is either a canned stdout string or an exception
    instance to raise (mirrors packs/main-ci-watcher/tests's harness).
    Unmatched calls fall back to an empty success — only calls the test
    cares about need an explicit rule.
    """
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        for prefix, response in rules:
            if args[: len(prefix)] == list(prefix):
                if isinstance(response, BaseException):
                    raise response
                return FakeCompleted(stdout=response)
        return FakeCompleted(stdout="")

    run.calls = calls
    return run


def _stub(monkeypatch, rules):
    fake = _fake_run(rules)
    monkeypatch.setattr(subprocess, "run", fake)
    return fake


@pytest.fixture
def dw(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("GC_CITY_ROOT", str(tmp_path / "city"))
    monkeypatch.delenv("CI_DRIFTWATCH_DRY_RUN", raising=False)
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    spec = importlib.util.spec_from_file_location("ci_driftwatch", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_json(database_id, head_sha, conclusion, status="completed", created_at=None, url=None):
    return json.dumps([{
        "databaseId": database_id,
        "headSha": head_sha,
        "conclusion": conclusion,
        "status": status,
        "createdAt": (created_at or NOW).isoformat(),
        "url": url or f"https://github.com/{REPO}/actions/runs/{database_id}",
    }])


def _write_state(dw, **overrides):
    state = {
        "repo": REPO,
        "branch": "main",
        "last_checked_sha": "sha-old",
        "last_conclusion": "success",
        "last_schedule_run_id": 100,
        "last_schedule_run_seen_at": NOW.isoformat(),
        "alerted_for_sha": False,
        "alerted_at": None,
        "rerun_issued_for_sha": None,
        "stale_alerted": False,
        "updated_at": NOW.isoformat(),
    }
    state.update(overrides)
    dw.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    dw.STATE_FILE.write_text(json.dumps(state))
    return state


# ---------------------------------------------------------------------------
# Bootstrap — no state file yet
# ---------------------------------------------------------------------------

def test_bootstrap_creates_state_without_alerting(dw, monkeypatch):
    assert not dw.STATE_FILE.exists()
    rules = [(["gh", "run", "list"], _run_json(111, "sha1", "success"))]
    fake = _stub(monkeypatch, rules)

    rc = dw.run(now=NOW)

    assert rc == 0
    assert dw.STATE_FILE.exists()
    state = json.loads(dw.STATE_FILE.read_text())
    assert state["last_checked_sha"] == "sha1"
    assert state["last_conclusion"] == "success"
    assert state["alerted_for_sha"] is False
    assert not any(c[:2] == ["gc", "bd"] for c in fake.calls)
    assert not any(c[:3] == ["gc", "mail", "send"] for c in fake.calls)
    assert not any(c[:1] == ["notify-fanout"] for c in fake.calls)


# ---------------------------------------------------------------------------
# FR-3 — a new commit resets state; out of scope, never alerts
# ---------------------------------------------------------------------------

def test_sha_changed_resets_state_without_alerting(dw, monkeypatch):
    _write_state(
        dw, last_checked_sha="sha-old", last_conclusion="failure",
        alerted_for_sha=True, rerun_issued_for_sha="sha-old",
    )
    rules = [(["gh", "run", "list"], _run_json(333, "sha-new", "failure"))]
    fake = _stub(monkeypatch, rules)

    rc = dw.run(now=NOW)

    assert rc == 0
    assert not any(c[:3] == ["gh", "run", "rerun"] for c in fake.calls)
    assert not any(c[:2] == ["gc", "bd"] for c in fake.calls)
    assert not any(c[:3] == ["gc", "mail", "send"] for c in fake.calls)
    assert not any(c[:1] == ["notify-fanout"] for c in fake.calls)

    state = json.loads(dw.STATE_FILE.read_text())
    assert state["last_checked_sha"] == "sha-new"
    assert state["alerted_for_sha"] is False
    assert state["rerun_issued_for_sha"] is None


# ---------------------------------------------------------------------------
# FR-4 — one automatic rerun rules out a single-shot flake
# ---------------------------------------------------------------------------

def test_single_flake_recovers_silently(dw, monkeypatch):
    _write_state(
        dw, last_checked_sha="sha1", last_conclusion="failure",
        alerted_for_sha=False, rerun_issued_for_sha=None,
    )
    rules = [
        (["gh", "run", "list"], _run_json(222, "sha1", "failure")),
        (["gh", "run", "rerun", "222", "--failed", "--repo", REPO], ""),
        (
            ["gh", "run", "view", "222", "--repo", REPO, "--json", "status,conclusion"],
            json.dumps({"status": "completed", "conclusion": "success"}),
        ),
    ]
    fake = _stub(monkeypatch, rules)

    rc = dw.run(now=NOW)

    assert rc == 0
    assert any(c[:3] == ["gh", "run", "rerun"] for c in fake.calls)
    assert not any(c[:2] == ["gc", "bd"] for c in fake.calls)
    assert not any(c[:3] == ["gc", "mail", "send"] for c in fake.calls)
    assert not any(c[:1] == ["notify-fanout"] for c in fake.calls)

    state = json.loads(dw.STATE_FILE.read_text())
    assert state["alerted_for_sha"] is False


# ---------------------------------------------------------------------------
# FR-5/FR-6 — confirmed drift: bead filed, both alert channels fire
# ---------------------------------------------------------------------------

def test_confirmed_drift_files_bead_and_alerts_both_channels(dw, monkeypatch):
    _write_state(
        dw, last_checked_sha="sha1", last_conclusion="failure",
        alerted_for_sha=False, rerun_issued_for_sha=None,
    )
    rules = [
        (["gh", "run", "list"], _run_json(222, "sha1", "failure")),
        (["gh", "run", "rerun", "222", "--failed", "--repo", REPO], ""),
        (
            ["gh", "run", "view", "222", "--repo", REPO, "--json", "status,conclusion"],
            json.dumps({"status": "completed", "conclusion": "failure"}),
        ),
        (
            ["gc", "bd", "--rig", "tincan-iris", "create"],
            "Created issue: ti-99abc\n",
        ),
    ]
    fake = _stub(monkeypatch, rules)

    rc = dw.run(now=NOW)

    assert rc == 0
    create_calls = [c for c in fake.calls if c[:4] == ["gc", "bd", "--rig", "tincan-iris"] and "create" in c]
    assert create_calls, f"expected a gc bd create call, got: {fake.calls}"
    assert "main CI red: test on quad341/tincan-iris" in create_calls[0], (
        "bead title must match the main-ci-watcher-compatible contract "
        "'main CI red: {check} on {repo}'"
    )
    assert any(c[:2] == ["gc", "sling"] and "ti-99abc" in c for c in fake.calls)
    assert any(c[:3] == ["gc", "mail", "send"] and "mayor" in c for c in fake.calls)
    assert any(c[:2] == ["notify-fanout", "critical"] for c in fake.calls)

    state = json.loads(dw.STATE_FILE.read_text())
    assert state["alerted_for_sha"] is True


# ---------------------------------------------------------------------------
# FR-7 — debounce: already alerted for this sha, don't re-alert or re-rerun
# ---------------------------------------------------------------------------

def test_already_alerted_debounces(dw, monkeypatch):
    _write_state(
        dw, last_checked_sha="sha1", last_conclusion="failure",
        alerted_for_sha=True, alerted_at=NOW.isoformat(), rerun_issued_for_sha="sha1",
    )
    rules = [(["gh", "run", "list"], _run_json(222, "sha1", "failure"))]
    fake = _stub(monkeypatch, rules)

    rc = dw.run(now=NOW)

    assert rc == 0
    assert not any(c[:3] == ["gh", "run", "rerun"] for c in fake.calls)
    assert not any(c[:2] == ["gc", "bd"] for c in fake.calls)
    assert not any(c[:3] == ["gc", "mail", "send"] for c in fake.calls)
    assert not any(c[:1] == ["notify-fanout"] for c in fake.calls)


# ---------------------------------------------------------------------------
# FR-8 — schedule trigger itself looks stalled (no recent observed run)
# ---------------------------------------------------------------------------

def test_stale_schedule_alerts_and_debounces_on_repeat(dw, monkeypatch):
    old_run_time = NOW - timedelta(hours=20)  # > 2x the 6h schedule interval
    _write_state(
        dw, last_checked_sha="sha1", last_conclusion="success",
        stale_alerted=False, updated_at=old_run_time.isoformat(),
    )
    rules = [(["gh", "run", "list"], _run_json(50, "sha1", "success", created_at=old_run_time))]
    fake = _stub(monkeypatch, rules)

    rc = dw.run(now=NOW)

    assert rc == 0
    assert any(c[:3] == ["gc", "mail", "send"] and "mayor" in c for c in fake.calls)
    assert any(c[:1] == ["notify-fanout"] for c in fake.calls)
    assert not any(c[:2] == ["gc", "bd"] and "create" in c for c in fake.calls), (
        "staleness alone must not file a bead"
    )

    state = json.loads(dw.STATE_FILE.read_text())
    assert state["stale_alerted"] is True

    fake.calls.clear()
    rc2 = dw.run(now=NOW + timedelta(minutes=20))

    assert rc2 == 0
    assert not any(c[:3] == ["gc", "mail", "send"] for c in fake.calls)
    assert not any(c[:1] == ["notify-fanout"] for c in fake.calls)
