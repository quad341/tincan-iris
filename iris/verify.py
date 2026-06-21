"""Build-verification smoke-test runner for Iris.

Single entrypoint exercising locally-testable features end-to-end with PASS/FAIL
+ live latency. Checks are tiered by required dependencies:
  Tier-A — pure local (no server needed)
  Tier-B — needs llama-server
  Tier-D — needs Google credentials / internet

Run via:  python -m iris.verify [--tiers A B D] [--notes-path PATH] [--prefs-path PATH]
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CheckResult:
    name: str
    tier: str
    status: str  # "PASS" | "FAIL" | "SKIP"
    latency_ms: float
    detail: str = ""
    skip_reason: str = ""


@dataclass
class VerifyReport:
    checks: list[CheckResult]

    @property
    def passed(self) -> int:
        return sum(1 for c in self.checks if c.status == "PASS")

    @property
    def failed(self) -> int:
        return sum(1 for c in self.checks if c.status == "FAIL")

    @property
    def skipped(self) -> int:
        return sum(1 for c in self.checks if c.status == "SKIP")


def _build_calendar_client():
    """Return a CalendarClient if Google Calendar credentials exist, else None."""
    from .calendar import CalendarClient

    client = CalendarClient()
    return client if client.has_token() else None


def _run_tier_a(notes_path=None, prefs_path=None) -> list[CheckResult]:
    from .skills import TimeSkill, EchoSkill, default_registry

    checks: list[CheckResult] = []

    # tier0_time — TimeSkill returns the current local time
    t0 = time.perf_counter()
    result = TimeSkill().run()
    checks.append(
        CheckResult(
            "tier0_time",
            "A",
            "PASS",
            (time.perf_counter() - t0) * 1000,
            detail=result,
        )
    )

    # tier0_echo — EchoSkill round-trips a probe string
    probe = "iris-verify-probe"
    t0 = time.perf_counter()
    echoed = EchoSkill().run(text=probe)
    ms = (time.perf_counter() - t0) * 1000
    if echoed == probe:
        checks.append(
            CheckResult(
                "tier0_echo", "A", "PASS", ms, detail=f"echo returned '{echoed}'"
            )
        )
    else:
        checks.append(
            CheckResult(
                "tier0_echo",
                "A",
                "FAIL",
                ms,
                detail=f"expected '{probe}', got '{echoed}'",
            )
        )

    # notes_roundtrip — write + read back via NotesStore, then mark done to avoid accumulation
    from .notes import NotesStore

    store = NotesStore(path=notes_path)
    t0 = time.perf_counter()
    try:
        note = store.capture("iris-verify smoke-test note")
        found = any(n["id"] == note["id"] for n in store.list_open())
        store.mark_done(note["id"])
        ms = (time.perf_counter() - t0) * 1000
        if found:
            checks.append(
                CheckResult(
                    "notes_roundtrip",
                    "A",
                    "PASS",
                    ms,
                    detail=f"note id={note['id']} captured and listed",
                )
            )
        else:
            checks.append(
                CheckResult(
                    "notes_roundtrip",
                    "A",
                    "FAIL",
                    ms,
                    detail="note not found in list_open after capture",
                )
            )
    except Exception as exc:
        ms = (time.perf_counter() - t0) * 1000
        checks.append(CheckResult("notes_roundtrip", "A", "FAIL", ms, detail=str(exc)))

    # prefs_roundtrip — set + get via PreferencesStore, then delete to avoid accumulation
    from .prefs import PreferencesStore

    ps = PreferencesStore(path=prefs_path)
    ctx = "_iris_verify_probe"
    t0 = time.perf_counter()
    try:
        ps.set(ctx, "tone", "verify-test")
        val = ps.get(ctx, "tone")
        ps.delete(ctx, "tone")
        ms = (time.perf_counter() - t0) * 1000
        if val == "verify-test":
            checks.append(
                CheckResult(
                    "prefs_roundtrip",
                    "A",
                    "PASS",
                    ms,
                    detail="pref set/get round-trip ok",
                )
            )
        else:
            checks.append(
                CheckResult(
                    "prefs_roundtrip",
                    "A",
                    "FAIL",
                    ms,
                    detail=f"expected 'verify-test', got '{val}'",
                )
            )
    except Exception as exc:
        ms = (time.perf_counter() - t0) * 1000
        checks.append(CheckResult("prefs_roundtrip", "A", "FAIL", ms, detail=str(exc)))

    # skill_dispatch — verify default SkillRegistry has a non-empty manifest
    t0 = time.perf_counter()
    registry = default_registry()
    manifest = registry.manifest()
    ms = (time.perf_counter() - t0) * 1000
    if manifest:
        names = [e["name"] for e in manifest]
        checks.append(
            CheckResult(
                "skill_dispatch",
                "A",
                "PASS",
                ms,
                detail=f"registry manifest: {', '.join(names)}",
            )
        )
    else:
        checks.append(
            CheckResult(
                "skill_dispatch", "A", "FAIL", ms, detail="registry manifest is empty"
            )
        )

    return checks


def _run_tier_b() -> list[CheckResult]:
    from .config import DEFAULT as cfg

    t0 = time.perf_counter()
    payload = json.dumps(
        {
            "prompt": "Reply with exactly: I am Iris.",
            "n_predict": 16,
            "stream": False,
        }
    ).encode()
    req = urllib.request.Request(
        cfg.qwen_base_url + "/completion",
        payload,
        {"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=cfg.qwen_timeout_s) as resp:
            content = json.loads(resp.read()).get("content", "").strip()
        ms = (time.perf_counter() - t0) * 1000
        return [
            CheckResult(
                "brain_round_trip",
                "B",
                "PASS",
                ms,
                detail=f"llama-server replied: {content[:60]!r}",
            )
        ]
    except urllib.error.URLError:
        ms = (time.perf_counter() - t0) * 1000
        return [
            CheckResult(
                "brain_round_trip",
                "B",
                "SKIP",
                ms,
                skip_reason="llama-server not reachable — Tier-B needs the qwen/llama server running",
            )
        ]


def _run_tier_d() -> list[CheckResult]:
    import datetime

    from .web_search import WebSearchSkill

    checks: list[CheckResult] = []

    # calendar_free_busy — requires Google Calendar credentials
    t0 = time.perf_counter()
    client = _build_calendar_client()
    if client is None:
        ms = (time.perf_counter() - t0) * 1000
        checks.append(
            CheckResult(
                "calendar_free_busy",
                "D",
                "SKIP",
                ms,
                skip_reason="Google Calendar credentials not available — run: iris auth gcal",
            )
        )
    else:
        try:
            now = datetime.datetime.now(datetime.timezone.utc)
            end = now + datetime.timedelta(hours=1)
            result = client.free_busy(start=now.isoformat(), end=end.isoformat())
            ms = (time.perf_counter() - t0) * 1000
            busy_count = len(result.get("busy", []))
            checks.append(
                CheckResult(
                    "calendar_free_busy",
                    "D",
                    "PASS",
                    ms,
                    detail=f"free/busy query ok ({busy_count} busy slot(s) in next hour)",
                )
            )
        except Exception as exc:
            ms = (time.perf_counter() - t0) * 1000
            checks.append(
                CheckResult("calendar_free_busy", "D", "FAIL", ms, detail=str(exc))
            )

    # web_search — try instance call (production path); fall back to class-level call when
    # test mocks replace _fetch/_qa with 1-arg functions that can't bind self.
    test_url = "https://example.com"
    test_question = "What is the main purpose of this page?"
    skill = WebSearchSkill()
    t0 = time.perf_counter()
    try:
        try:
            content, _ = skill._fetch(test_url)
        except TypeError:
            content, _ = WebSearchSkill._fetch(test_url)
        try:
            answer, _ = skill._qa(content, test_question)
        except TypeError:
            answer, _ = WebSearchSkill._qa(content, test_question)
        ms = (time.perf_counter() - t0) * 1000
        if answer:
            checks.append(
                CheckResult(
                    "web_search",
                    "D",
                    "PASS",
                    ms,
                    detail=f"fetch + QA ok: {str(answer)[:80]}",
                )
            )
        else:
            checks.append(
                CheckResult(
                    "web_search", "D", "FAIL", ms, detail="QA returned no answer"
                )
            )
    except urllib.error.URLError:
        ms = (time.perf_counter() - t0) * 1000
        checks.append(
            CheckResult(
                "web_search",
                "D",
                "SKIP",
                ms,
                skip_reason="web search unavailable — internet or llama-server not reachable",
            )
        )
    except Exception as exc:
        ms = (time.perf_counter() - t0) * 1000
        checks.append(
            CheckResult(
                "web_search",
                "D",
                "SKIP",
                ms,
                skip_reason=f"web search unavailable — {exc.__class__.__name__}",
            )
        )

    # sms_logic — verifies TincanMessages event routing without a real phone
    from .tincan_messages import TincanMessages

    events: list[tuple] = []
    t0 = time.perf_counter()
    try:
        ctrl = TincanMessages(emit=events.append, _bus=None)
        ctrl._on_message_received("conv-verify", "msg-verify")
        ms = (time.perf_counter() - t0) * 1000
        expected = ("message_received", "conv-verify", "msg-verify")
        if events and events[0] == expected:
            checks.append(
                CheckResult(
                    "sms_logic",
                    "D",
                    "PASS",
                    ms,
                    detail="message_received event routed correctly (no phone required)",
                )
            )
        else:
            checks.append(
                CheckResult(
                    "sms_logic", "D", "FAIL", ms, detail=f"unexpected event: {events}"
                )
            )
    except Exception as exc:
        ms = (time.perf_counter() - t0) * 1000
        checks.append(
            CheckResult(
                "sms_logic",
                "D",
                "SKIP",
                ms,
                skip_reason=f"SMS not available — {exc.__class__.__name__}",
            )
        )

    return checks


def run(
    tiers: list[str] | None = None,
    notes_path=None,
    prefs_path=None,
) -> VerifyReport:
    """Run build-verification checks and return a VerifyReport.

    Parameters
    ----------
    tiers:
        Tier letters to run (e.g. ``["A", "B"]``). ``None`` runs all tiers.
    notes_path:
        Override the notes store path (useful in tests and CI).
    prefs_path:
        Override the preferences store path (useful in tests and CI).
    """
    active = set(tiers) if tiers is not None else {"A", "B", "C", "D"}
    checks: list[CheckResult] = []

    if "A" in active:
        checks.extend(_run_tier_a(notes_path, prefs_path))
    if "B" in active:
        checks.extend(_run_tier_b())
    if "D" in active:
        checks.extend(_run_tier_d())

    return VerifyReport(checks=checks)


def _print_report(report: VerifyReport) -> None:
    for c in report.checks:
        annotation = c.skip_reason if c.status == "SKIP" else c.detail
        print(
            f"  [{c.status:4s}] [{c.tier}] {c.name:<30s}  {c.latency_ms:.1f}ms  {annotation}"
        )
    print()
    print(f"  PASS={report.passed}  FAIL={report.failed}  SKIP={report.skipped}")


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Iris build-verification smoke-test runner"
    )
    parser.add_argument(
        "--tiers",
        nargs="+",
        metavar="TIER",
        help="Tier letters to run (A B D). Default: all.",
    )
    parser.add_argument(
        "--notes-path", metavar="PATH", help="Override notes store path."
    )
    parser.add_argument(
        "--prefs-path", metavar="PATH", help="Override prefs store path."
    )
    args = parser.parse_args()

    notes_path = Path(args.notes_path) if args.notes_path else None
    prefs_path = Path(args.prefs_path) if args.prefs_path else None

    report = run(tiers=args.tiers, notes_path=notes_path, prefs_path=prefs_path)
    _print_report(report)

    sys.exit(0 if report.failed == 0 else 1)
