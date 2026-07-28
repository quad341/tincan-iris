"""Tests for the schedule: trigger on .github/workflows/ci.yml (ti-4tq52).

These tests FAIL until the builder adds a `schedule:` block under `on:`.
Needed because GitHub Actions never re-evaluates an already-merged tip
without a trigger — a push-triggered-only workflow can go silently red for
days after a dependency changes underneath it with zero commits to main
(see ti-pcqj4). ci_driftwatch.py (see test_ci_driftwatch.py) consumes the
schedule-triggered runs this produces.
"""
from __future__ import annotations

import re
from pathlib import Path

CI_YML = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci.yml"


def _on_block():
    lines = CI_YML.read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "on:")
    end = next(i for i in range(start + 1, len(lines)) if lines[i].strip() == "jobs:")
    return "\n".join(lines[start:end])


def _cron_expr(block):
    match = re.search(r"cron:\s*[\"']([^\"']+)[\"']", block)
    return match.group(1) if match else None


def test_schedule_trigger_present_with_cron():
    block = _on_block()
    assert "schedule:" in block, "expected an `on.schedule` trigger in ci.yml"
    cron = _cron_expr(block)
    assert cron, f"expected a quoted cron expression under schedule:, got:\n{block}"
    assert len(cron.split()) == 5, f"cron {cron!r} must have 5 fields"


def test_schedule_cron_is_off_the_hour():
    cron = _cron_expr(_on_block())
    minute = cron.split()[0]
    assert minute not in ("0", "30"), (
        f"cron {cron!r} lands on a round minute — every repo doing this at "
        "the same clock time hammers GitHub's scheduler simultaneously"
    )


def test_schedule_interval_is_six_hours_or_tighter():
    cron = _cron_expr(_on_block())
    assert cron, "expected a quoted cron expression under schedule:"
    hour_field = cron.split()[1]
    step_match = re.match(r"\*/(\d+)$", hour_field)
    if step_match:
        assert int(step_match.group(1)) <= 6, f"cron {cron!r} runs less often than every 6h"
    else:
        assert hour_field == "*", f"unexpected hour field {hour_field!r} in cron {cron!r}"


def test_push_and_pull_request_triggers_still_present():
    block = _on_block()
    assert "push:" in block
    assert "branches: [main]" in block
    assert "pull_request:" in block


def test_jobs_test_block_is_completely_unchanged():
    """The schedule: trigger must be additive — jobs.test's steps (including
    the ruff pin) must not be touched by this change."""
    lines = CI_YML.read_text().splitlines()
    jobs_start = next(i for i, line in enumerate(lines) if line.strip() == "jobs:")
    jobs_block = "\n".join(lines[jobs_start:])
    assert "ruff==0.15.22" in jobs_block
    assert "pytest -q" in jobs_block
    assert jobs_block.count("- name:") == 3
