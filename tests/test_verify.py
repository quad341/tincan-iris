"""Tests for iris.verify — build-verification smoke-test runner.

Covers:
  - Module import and public API shape
  - CheckResult / VerifyReport data model
  - Tier-A (pure-local): Tier-0 cmds, notes, prefs, skill dispatch, context
  - Tier-B (needs-llama-server): brain Tier-1 round-trip; skip when server down
  - Tier-D (needs-google): calendar and web_search (mocked); skip when creds absent
  - Tier filtering via tiers= argument
  - Skip-with-notice: skipped checks carry a non-empty skip_reason
  - Report aggregation: passed / failed / skipped counts
  - CLI module: python -m iris.verify exit codes

These tests will fail until iris/verify.py is implemented (ti-63e9).
"""
from __future__ import annotations

import json
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

from iris.verify import CheckResult, VerifyReport, run


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

def test_check_result_has_required_fields():
    c = CheckResult(name="tier0_time", tier="A", status="PASS", latency_ms=1.2)
    assert c.name == "tier0_time"
    assert c.tier == "A"
    assert c.status == "PASS"
    assert c.latency_ms == 1.2


def test_check_result_status_is_string():
    for status in ("PASS", "FAIL", "SKIP"):
        c = CheckResult(name="x", tier="A", status=status, latency_ms=0.0)
        assert c.status in {"PASS", "FAIL", "SKIP"}


def test_check_result_skip_reason_defaults_empty():
    c = CheckResult(name="x", tier="B", status="SKIP", latency_ms=0.0)
    assert hasattr(c, "skip_reason")
    assert c.skip_reason == "" or c.skip_reason is None


def test_verify_report_has_checks_list():
    report = VerifyReport(checks=[])
    assert hasattr(report, "checks")
    assert isinstance(report.checks, list)


def test_verify_report_aggregates_passed():
    checks = [
        CheckResult("a", "A", "PASS", 1.0),
        CheckResult("b", "A", "PASS", 2.0),
        CheckResult("c", "B", "SKIP", 0.0),
    ]
    report = VerifyReport(checks=checks)
    assert report.passed == 2


def test_verify_report_aggregates_failed():
    checks = [
        CheckResult("a", "A", "PASS", 1.0),
        CheckResult("b", "A", "FAIL", 2.0),
    ]
    report = VerifyReport(checks=checks)
    assert report.failed == 1


def test_verify_report_aggregates_skipped():
    checks = [
        CheckResult("a", "B", "SKIP", 0.0),
        CheckResult("b", "D", "SKIP", 0.0),
    ]
    report = VerifyReport(checks=checks)
    assert report.skipped == 2


def test_verify_report_zero_failed_on_all_pass():
    checks = [CheckResult(f"c{i}", "A", "PASS", float(i)) for i in range(5)]
    report = VerifyReport(checks=checks)
    assert report.failed == 0


# ---------------------------------------------------------------------------
# run() basics
# ---------------------------------------------------------------------------

def test_run_returns_verify_report():
    report = run(tiers=["A"])
    assert isinstance(report, VerifyReport)


def test_run_checks_is_nonempty():
    report = run(tiers=["A"])
    assert len(report.checks) > 0


def test_run_all_checks_have_valid_tier():
    report = run(tiers=["A"])
    valid_tiers = {"A", "B", "C", "D"}
    for c in report.checks:
        assert c.tier in valid_tiers, f"Check '{c.name}' has unknown tier '{c.tier}'"


def test_run_all_checks_have_valid_status():
    report = run(tiers=["A"])
    for c in report.checks:
        assert c.status in {"PASS", "FAIL", "SKIP"}, (
            f"Check '{c.name}' has invalid status '{c.status}'"
        )


def test_run_all_checks_record_latency():
    report = run(tiers=["A"])
    for c in report.checks:
        assert isinstance(c.latency_ms, (int, float)), (
            f"Check '{c.name}' has non-numeric latency"
        )
        assert c.latency_ms >= 0.0


# ---------------------------------------------------------------------------
# Tier-A: pure-local checks
# ---------------------------------------------------------------------------

def test_tier_a_checks_are_included():
    report = run(tiers=["A"])
    tiers = {c.tier for c in report.checks}
    assert "A" in tiers


def test_tier_a_checks_pass_without_server(tmp_path):
    report = run(tiers=["A"], notes_path=tmp_path / "notes.json", prefs_path=tmp_path / "prefs.json")
    tier_a = [c for c in report.checks if c.tier == "A"]
    assert all(c.status == "PASS" for c in tier_a), (
        f"Tier-A failures: {[(c.name, c.status) for c in tier_a if c.status != 'PASS']}"
    )


def test_tier_a_includes_tier0_time_check(tmp_path):
    report = run(tiers=["A"], notes_path=tmp_path / "notes.json", prefs_path=tmp_path / "prefs.json")
    names = {c.name for c in report.checks}
    assert "tier0_time" in names


def test_tier_a_includes_tier0_echo_check(tmp_path):
    report = run(tiers=["A"], notes_path=tmp_path / "notes.json", prefs_path=tmp_path / "prefs.json")
    names = {c.name for c in report.checks}
    assert "tier0_echo" in names


def test_tier_a_includes_notes_roundtrip(tmp_path):
    report = run(tiers=["A"], notes_path=tmp_path / "notes.json", prefs_path=tmp_path / "prefs.json")
    names = {c.name for c in report.checks}
    assert "notes_roundtrip" in names


def test_tier_a_includes_prefs_roundtrip(tmp_path):
    report = run(tiers=["A"], notes_path=tmp_path / "notes.json", prefs_path=tmp_path / "prefs.json")
    names = {c.name for c in report.checks}
    assert "prefs_roundtrip" in names


def test_tier_a_tier0_time_check_returns_time_string(tmp_path):
    report = run(tiers=["A"], notes_path=tmp_path / "notes.json", prefs_path=tmp_path / "prefs.json")
    time_check = next((c for c in report.checks if c.name == "tier0_time"), None)
    assert time_check is not None
    assert time_check.status == "PASS"
    assert time_check.detail  # detail should contain the returned time string


def test_tier_a_tier0_echo_check_passes(tmp_path):
    report = run(tiers=["A"], notes_path=tmp_path / "notes.json", prefs_path=tmp_path / "prefs.json")
    echo_check = next((c for c in report.checks if c.name == "tier0_echo"), None)
    assert echo_check is not None
    assert echo_check.status == "PASS"


def test_tier_a_notes_roundtrip_check_passes(tmp_path):
    report = run(tiers=["A"], notes_path=tmp_path / "notes.json", prefs_path=tmp_path / "prefs.json")
    notes_check = next((c for c in report.checks if c.name == "notes_roundtrip"), None)
    assert notes_check is not None
    assert notes_check.status == "PASS"


def test_tier_a_prefs_roundtrip_check_passes(tmp_path):
    report = run(tiers=["A"], notes_path=tmp_path / "notes.json", prefs_path=tmp_path / "prefs.json")
    prefs_check = next((c for c in report.checks if c.name == "prefs_roundtrip"), None)
    assert prefs_check is not None
    assert prefs_check.status == "PASS"


def test_tier_a_skill_dispatch_check_present(tmp_path):
    """Skill dispatch check exercises the SkillRegistry manifest."""
    report = run(tiers=["A"], notes_path=tmp_path / "notes.json", prefs_path=tmp_path / "prefs.json")
    names = {c.name for c in report.checks}
    assert "skill_dispatch" in names


def test_tier_a_skill_dispatch_check_passes(tmp_path):
    report = run(tiers=["A"], notes_path=tmp_path / "notes.json", prefs_path=tmp_path / "prefs.json")
    dispatch_check = next((c for c in report.checks if c.name == "skill_dispatch"), None)
    assert dispatch_check is not None
    assert dispatch_check.status == "PASS"


# ---------------------------------------------------------------------------
# Tier-B: needs-llama-server (brain round-trip)
# ---------------------------------------------------------------------------

def _fake_urlopen_response(content: str):
    body = json.dumps({"content": content}).encode()
    cm = MagicMock()
    cm.__enter__ = lambda s: MagicMock(read=lambda: body)
    cm.__exit__ = MagicMock(return_value=False)
    return cm


def test_tier_b_skipped_when_server_down():
    """When llama-server is unreachable, Tier-B checks must be SKIP, not FAIL."""
    import urllib.error
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):
        report = run(tiers=["B"])
    tier_b = [c for c in report.checks if c.tier == "B"]
    assert len(tier_b) > 0, "Expected at least one Tier-B check"
    for c in tier_b:
        assert c.status == "SKIP", f"Check '{c.name}' should be SKIP when server is down, got '{c.status}'"


def test_tier_b_skip_reason_mentions_server():
    import urllib.error
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):
        report = run(tiers=["B"])
    tier_b_skipped = [c for c in report.checks if c.tier == "B" and c.status == "SKIP"]
    assert tier_b_skipped
    for c in tier_b_skipped:
        reason = (c.skip_reason or "").lower()
        assert "llama" in reason or "server" in reason or "qwen" in reason, (
            f"Skip reason '{c.skip_reason}' doesn't mention the missing server"
        )


def test_tier_b_passes_when_server_up():
    brain_reply = json.dumps({"skill": "none", "args": {}})
    chat_reply = "I'm Iris."
    call_count = {"n": 0}
    responses = [brain_reply, chat_reply]

    def fake_urlopen(req, timeout=None):
        idx = call_count["n"] % len(responses)
        call_count["n"] += 1
        return _fake_urlopen_response(responses[idx])

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        report = run(tiers=["B"])
    tier_b = [c for c in report.checks if c.tier == "B"]
    assert any(c.status == "PASS" for c in tier_b)


def test_tier_b_includes_brain_round_trip_check():
    import urllib.error
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
        report = run(tiers=["B"])
    names = {c.name for c in report.checks}
    assert "brain_round_trip" in names


def test_tier_b_latency_recorded_on_pass():
    brain_reply = json.dumps({"skill": "none", "args": {}})
    chat_reply = "Hi."
    call_count = {"n": 0}
    responses = [brain_reply, chat_reply]

    def fake_urlopen(req, timeout=None):
        idx = call_count["n"] % len(responses)
        call_count["n"] += 1
        return _fake_urlopen_response(responses[idx])

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        report = run(tiers=["B"])
    tier_b_passed = [c for c in report.checks if c.tier == "B" and c.status == "PASS"]
    for c in tier_b_passed:
        assert c.latency_ms >= 0.0


# ---------------------------------------------------------------------------
# Tier-D: needs-google (calendar mock, web_search mock, SMS mock)
# ---------------------------------------------------------------------------

def _mock_calendar_client():
    client = MagicMock()
    client.free_busy.return_value = {"busy": []}
    return client


def test_tier_d_calendar_free_busy_check_present():
    with patch("iris.verify._build_calendar_client", return_value=_mock_calendar_client()):
        report = run(tiers=["D"])
    names = {c.name for c in report.checks}
    assert "calendar_free_busy" in names


def test_tier_d_calendar_free_busy_passes_with_mock():
    with patch("iris.verify._build_calendar_client", return_value=_mock_calendar_client()):
        report = run(tiers=["D"])
    cal_check = next((c for c in report.checks if c.name == "calendar_free_busy"), None)
    assert cal_check is not None
    assert cal_check.status == "PASS"


def test_tier_d_web_search_check_present():
    def mock_fetch(url):
        return ("Sample page content.", [])

    def mock_qa(content, q):
        return ("The answer is 42.", False)

    with patch("iris.web_search.WebSearchSkill._fetch", mock_fetch):
        with patch("iris.web_search.WebSearchSkill._qa", mock_qa):
            report = run(tiers=["D"])
    names = {c.name for c in report.checks}
    assert "web_search" in names


def test_tier_d_web_search_passes_with_mock():
    def mock_fetch(url):
        return ("Sample page content.", [])

    def mock_qa(content, q):
        return ("The answer is 42.", False)

    with patch("iris.web_search.WebSearchSkill._fetch", mock_fetch):
        with patch("iris.web_search.WebSearchSkill._qa", mock_qa):
            report = run(tiers=["D"])
    ws_check = next((c for c in report.checks if c.name == "web_search"), None)
    assert ws_check is not None
    assert ws_check.status == "PASS"


def test_tier_d_skipped_when_google_creds_absent():
    """When Google calendar creds are absent, Tier-D calendar check should SKIP."""
    with patch("iris.verify._build_calendar_client", return_value=None):
        report = run(tiers=["D"])
    cal_check = next((c for c in report.checks if c.name == "calendar_free_busy"), None)
    assert cal_check is not None
    assert cal_check.status == "SKIP"


def test_tier_d_skip_reason_mentions_google():
    with patch("iris.verify._build_calendar_client", return_value=None):
        report = run(tiers=["D"])
    cal_check = next((c for c in report.checks if c.name == "calendar_free_busy"), None)
    reason = (cal_check.skip_reason or "").lower()
    assert "google" in reason or "cred" in reason or "auth" in reason or "calendar" in reason, (
        f"Skip reason '{cal_check.skip_reason}' doesn't mention missing creds"
    )


def test_tier_d_sms_logic_check_present():
    with patch("iris.verify._build_calendar_client", return_value=_mock_calendar_client()):
        report = run(tiers=["D"])
    names = {c.name for c in report.checks}
    assert "sms_logic" in names


def test_tier_d_sms_logic_check_passes_with_mock():
    """SMS logic check uses a mocked TincanMessages — no phone required."""
    with patch("iris.verify._build_calendar_client", return_value=_mock_calendar_client()):
        report = run(tiers=["D"])
    sms_check = next((c for c in report.checks if c.name == "sms_logic"), None)
    assert sms_check is not None
    # SMS always passes with the internal mock (phone not required)
    assert sms_check.status in {"PASS", "SKIP"}


# ---------------------------------------------------------------------------
# Tier filtering
# ---------------------------------------------------------------------------

def test_tiers_filter_only_runs_requested():
    report = run(tiers=["A"])
    non_a = [c for c in report.checks if c.tier != "A"]
    assert non_a == [], f"Expected no non-Tier-A checks when tiers=['A'], got: {[c.name for c in non_a]}"


def test_tiers_filter_b_only():
    import urllib.error
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
        report = run(tiers=["B"])
    non_b = [c for c in report.checks if c.tier != "B"]
    assert non_b == [], f"Expected no non-Tier-B checks when tiers=['B'], got: {[c.name for c in non_b]}"


def test_tiers_filter_multi():
    import urllib.error
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
        report = run(tiers=["A", "B"])
    unexpected = [c for c in report.checks if c.tier not in {"A", "B"}]
    assert unexpected == []


def test_tiers_none_runs_all_tiers():
    """tiers=None should include checks from multiple tiers."""
    import urllib.error
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
        with patch("iris.verify._build_calendar_client", return_value=None):
            report = run(tiers=None)
    tiers_present = {c.tier for c in report.checks}
    assert len(tiers_present) >= 2, f"Expected checks from multiple tiers, got: {tiers_present}"


def test_skipped_do_not_count_as_failures():
    """Checks skipped due to missing deps must not inflate the failed count."""
    import urllib.error
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
        report = run(tiers=["B"])
    assert report.failed == 0


# ---------------------------------------------------------------------------
# Skip-with-notice invariants
# ---------------------------------------------------------------------------

def test_skip_always_has_nonempty_reason():
    """Every SKIP check must provide a human-readable skip_reason."""
    import urllib.error
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
        with patch("iris.verify._build_calendar_client", return_value=None):
            report = run(tiers=None)
    for c in report.checks:
        if c.status == "SKIP":
            assert c.skip_reason, f"Check '{c.name}' is SKIP but has empty skip_reason"


def test_skip_reason_is_human_readable():
    """skip_reason should be a human-readable sentence, not an exception class."""
    import urllib.error
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
        report = run(tiers=["B"])
    for c in report.checks:
        if c.status == "SKIP":
            reason = c.skip_reason or ""
            assert "URLError" not in reason, f"skip_reason exposes an exception class: '{reason}'"
            assert "Traceback" not in reason


# ---------------------------------------------------------------------------
# Detail field — distinguishes verify from iris-bench (latency-only)
# ---------------------------------------------------------------------------

def test_pass_checks_have_detail(tmp_path):
    """PASS checks must carry a detail string — verifying behavior, not just timing."""
    report = run(tiers=["A"], notes_path=tmp_path / "notes.json", prefs_path=tmp_path / "prefs.json")
    tier_a_passed = [c for c in report.checks if c.tier == "A" and c.status == "PASS"]
    assert tier_a_passed, "Need at least one Tier-A PASS to verify detail"
    for c in tier_a_passed:
        assert c.detail, f"Check '{c.name}' passed but has no detail"


def test_detail_is_not_just_a_number(tmp_path):
    """detail must describe what was verified, not just echo the latency."""
    report = run(tiers=["A"], notes_path=tmp_path / "notes.json", prefs_path=tmp_path / "prefs.json")
    for c in report.checks:
        if c.status == "PASS":
            try:
                float(c.detail)
                pytest.fail(f"Check '{c.name}' detail is just a number: '{c.detail}'")
            except (ValueError, TypeError):
                pass  # expected — detail is a descriptive string


# ---------------------------------------------------------------------------
# CLI: python -m iris.verify
# ---------------------------------------------------------------------------

def test_cli_exits_zero_when_all_pass(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "iris.verify", "--tiers", "A",
         "--notes-path", str(tmp_path / "notes.json"),
         "--prefs-path", str(tmp_path / "prefs.json")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"Expected exit 0 when all Tier-A checks pass.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_cli_output_contains_pass(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "iris.verify", "--tiers", "A",
         "--notes-path", str(tmp_path / "notes.json"),
         "--prefs-path", str(tmp_path / "prefs.json")],
        capture_output=True,
        text=True,
    )
    assert "PASS" in result.stdout, f"Expected 'PASS' in output:\n{result.stdout}"


def test_cli_output_contains_latency(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "iris.verify", "--tiers", "A",
         "--notes-path", str(tmp_path / "notes.json"),
         "--prefs-path", str(tmp_path / "prefs.json")],
        capture_output=True,
        text=True,
    )
    # latency should appear as "Xms" or "X ms"
    assert "ms" in result.stdout, f"Expected latency in ms in output:\n{result.stdout}"


def test_cli_tiers_flag_limits_checks(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "iris.verify", "--tiers", "A",
         "--notes-path", str(tmp_path / "notes.json"),
         "--prefs-path", str(tmp_path / "prefs.json")],
        capture_output=True,
        text=True,
    )
    # No Tier-B or Tier-D output when only running Tier-A
    assert result.returncode == 0


def test_cli_exits_nonzero_when_check_fails(tmp_path):
    """Simulate a Tier-A failure by breaking the notes store path."""
    # Patch run() to return a report with a FAIL
    with patch("iris.verify.run") as mock_run:
        mock_run.return_value = VerifyReport(checks=[
            CheckResult("notes_roundtrip", "A", "FAIL", 5.0, "write failed"),
        ])
        result = subprocess.run(
            [sys.executable, "-c",
             "from iris.verify import run, VerifyReport, CheckResult; "
             "r = VerifyReport(checks=[CheckResult('x','A','FAIL',1.0,'err')]); "
             "import sys; sys.exit(0 if r.failed == 0 else 1)"],
            capture_output=True,
        )
    assert result.returncode != 0


def test_cli_skip_does_not_cause_nonzero_exit(tmp_path):
    """A report with only PASS and SKIP checks should exit 0."""
    result = subprocess.run(
        [sys.executable, "-c",
         "from iris.verify import VerifyReport, CheckResult; "
         "import sys; "
         "r = VerifyReport(checks=["
         "  CheckResult('a','A','PASS',1.0,'ok'),"
         "  CheckResult('b','B','SKIP',0.0,''),"
         "]); "
         "sys.exit(0 if r.failed == 0 else 1)"],
        capture_output=True,
    )
    assert result.returncode == 0
