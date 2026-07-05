# Release Gate: jit-error-hint-ti-03yy3

**Bead:** ti-03yy3 — needs-deploy: JIT error hint toast + status-bar clause (from:ti-dio2z)
**Source bead:** ti-dio2z (review bead, CLOSED/PASS)
**Feature beads:** ti-00jr4.3 (implementation), ti-00jr4.5 (tests)
**Branch:** `deploy/jit-error-hint-ti-03yy3`
**Gate commit:** (this commit)
**Date:** 2026-07-05

## Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | **PASS** | ti-dio2z closed with reviewer PASS verdict (reviewer-gm-wisp-anw8hc, 2026-07-04) |
| 2 | Acceptance criteria met | **PASS** | ti-00jr4.3's 3 AC checked verbatim by reviewer: `notify()` toast text/severity, `_refresh_status` clause shape/wording matching the `_proactive_badge` convention, purely event-driven (no new polling loop). Hard dependency honored: reuses `self._last_error` field ti-oqlyk introduced, doesn't reinvent it |
| 3 | Tests pass | **PASS** | 1740 passed, 3 xpassed, 1 failed (full suite, this branch, re-run independently). The 1 failure (`test_daemon_call_card_config.py::test_main_passes_loaded_config_to_call_card_host`) is a pre-existing environmental flake, not a regression: a genuinely live `iris daemon` process (confirmed via `ps -p`, real PID, real `/usr/bin/python3.14 -m iris.daemon`) holds the daemon's real OS-level `flock` singleton lock, which this un-isolated test depends on being free. Zero file overlap between this bead's 2 commits (`iris/console/app.py`, `tests/test_console_app.py`) and the failing test's module (`iris/daemon/__main__.py`, `tests/test_daemon_call_card_config.py`) — confirmed via `git show --stat` on both commits |
| 4 | No high-severity findings open | **PASS** | One LOW/informational finding from review: pre-existing unescaped Rich markup at app.py:572, all producers traced to internal exception strings (not attacker-controlled) — accepted, non-blocking, out of scope for this diff |
| 5 | Final branch is clean | **PASS** | `git status` clean; only untracked `.gc/`/`.gitkeep` (pre-existing worktree infra, not part of this change) |
| 6 | Branch diverges cleanly from main | **PASS** | Built off current `origin/main` tip (post PR #151 merge, `af2c503`); exactly 2 commits ahead, 0 behind (`git log origin/main..HEAD` / `git log HEAD..origin/main`); no conflicts |
| 7 | Single feature theme | **PASS** | Both commits implement one feature (JIT error hint toast + status-bar clause, ti-00jr4.3) plus its own dedicated test coverage (ti-00jr4.5); touches `iris/console/app.py` + `tests/test_console_app.py` only. The later, separate commit `5142c23` (ti-40baw, bracket-escaping fix for *other* pre-existing call sites) on the shared source branch is deliberately excluded, per the bead's own explicit action plan — it has its own, not-yet-reviewed bead |

## Verdict: PASS

## Commits on branch (vs origin/main)

| SHA | Message |
|-----|---------|
| `45ef105` | feat(console): JIT error hint toast + status-bar clause (ti-00jr4.3) |
| `d8f63a1` | tests(console): JIT error-hint toast + status-bar clause (ti-00jr4.5) |

## Review summary (ti-dio2z)

**Correctness:** `_drain`'s error branch sets `self._last_error`, fires a `notify()` toast, and refreshes the status bar — reusing the existing `_proactive_badge`/`[n]` discoverability pattern exactly.
**Markup safety:** both new strings backslash-escape `[e]`/`[b]` — verified empirically that Rich/Textual's markup parser (`markup=True` by default) silently swallows unescaped lowercase-leading `[x]` tokens; confirmed via a live `run_test()` harness against the real `Toast` + `Static` render, not just the raw string.
**Findings:** 1 LOW (pre-existing unescaped markup elsewhere in the file, unrelated call sites, informational only).
**Test coverage:** 3 new tests in `tests/test_console_app.py`, asserting against `Content.from_markup(...).plain` (not the raw string) so a regression to an unescaped bracket actually fails the test. Reviewer independently simulated the regression and confirmed 2 of 3 tests fail as claimed.

## Deploy sequencing note

This bead was held across roughly 8 deployer sessions over ~29 hours (2026-07-04 14:56 UTC through 2026-07-04 19:26 UTC, then resumed 2026-07-05) waiting on two prerequisites to land: PR #142 (`feat/console-diagnostics-ti-oqlyk`, merged 2026-07-04T14:37:03Z) and PR #151 (ti-m99u6's crash-exit stderr message, `418f24f`/`b321f43`, which `4c57ab1` stacks directly on top of on the shared branch `feat/console-crash-exit-message-ti-00jr4-2`). PR #151 hit a real merge conflict (`mergeStateStatus=DIRTY`) that prior sessions correctly declined to resolve from the deployer seat (it belonged to already-closed ti-m99u6) and escalated to mayor. PR #151 has since merged (`af2c503`, mergedAt 2026-07-04T19:50:00Z). This deploy was built by pinning the exact prerequisite SHAs (`4c57ab1` + `18c0e51`) onto a fresh branch off the post-merge `origin/main` — not by checking out the shared multi-bead branch wholesale, which also carries several other not-yet-gated commits (ti-40baw, ti-hsju6, ti-9s84e, ti-syhdb, ti-1fpil/ti-cha1h — see `[[shared-branch-console-crash-exit-sequential-deploys]]`).
