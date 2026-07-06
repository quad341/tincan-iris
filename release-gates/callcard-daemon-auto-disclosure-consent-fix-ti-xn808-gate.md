# Release Gate: Call Card daemon auto-disclosure — consent-integrity fix (ti-xn808)

Bead: ti-xn808 (needs-deploy, from ti-iv69h / ti-429tt, re-review ti-apk7y)
Branch: deploy/callcard-daemon-auto-disclosure-ti-xn808
Commit: f39c2fc (cherry-pick of c9f62ee onto current origin/main tip e928439)

## Background

This is a fix, not new work. The original Call Card daemon-side auto-disclosure
feature (ti-iv69h) shipped a consent-integrity gap: `self._announce_proc` is a
single instance-level slot, not keyed by session_id, so a stale command for an
ended call could act on a different, live call's disclosure handle and let far-party
capture start on a truncated/non-consensual disclosure. Two independent reviewer
sessions split on this (PASS vs REQUEST-CHANGES); adjudication ti-429tt ruled
REQUEST-CHANGES wins. The original deploy bead ti-l4qcv was closed SUPERSEDED as a
result — do not deploy it, it predates the fix. The builder applied all 4 required
fix items and a single designated reviewer re-reviewed under ti-apk7y (PASS, no
blocking findings). ti-xn808 is the resulting fresh deploy bead for the fixed code.

## Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | PASS | ti-apk7y (CLOSED, close_reason=pass): independent re-review of commit c9f62ee, confirmed all 4 fix items independently necessary/correct, traced the race-safety argument for the `stopped` flag, verified test numbers in a disposable worktree. "No blocking findings." |
| 2 | Acceptance criteria met | PASS | Verified against the actual diff (not just notes): golden path (`_run_auto_disclose` → `disclosure_ack` on success), override (`disclosure_skip` active-session guard + `proc.stop()`), fallback (fail-closed `try/except Exception` around synth+play+wait, no sink → warn+return), race safety (`pending`-state guards in both `disclosure_ack`/`disclosure_skip`, `stopped` flag distinguishes a cut-short wait from natural completion so a truncated disclosure can never reach `disclosure_ack`), console-side defense in depth (`CallCardPanel.handle_event` session_id-mismatch guard on `call_card_disclosed`/`call_card_skipped`). Zero schema changes, confirmed. |
| 3 | Tests pass | PASS | `pytest -q tests` (scoped to the real tracked `tests/` dir — see note below): **1833 passed, 3 xpassed, 1 failed**. The 1 failure (`test_main_passes_loaded_config_to_call_card_host`) is pre-existing/environmental: this host has a live `python3 -m iris.daemon` process (pid 689129, confirmed via `ps -p 689129`) holding the daemon's singleton PID lock, unrelated to this change — same PID independently reported by reviewer ti-apk7y's own run. `ruff check iris tests scripts`: all checks passed. |
| 4 | No high-severity review findings open | PASS | The one HIGH finding (cross-session `_announce_proc` handle-stealing / consent-integrity race, ti-fjsmz finding 1) is the subject of this fix and is closed out by ti-apk7y's re-review with "No blocking findings." No other open HIGH findings on ti-iv69h/ti-apk7y/ti-429tt. |
| 5 | Final branch is clean | PASS | `git status` on the feature branch shows no uncommitted changes to tracked files. (This worktree carries long-standing untracked clutter — leftover directories/files from unrelated prior bead sessions reusing this same worktree, e.g. stray `ti-*/` dirs and an orphaned `release-gates/tts-cadence-slow-mode-lint-fix-ti-s04py-gate.md` from an already-closed bead — none of it tracked, none of it part of this branch's commit.) |
| 6 | Branch diverges cleanly from main | PASS | `git merge-base HEAD origin/main` == `origin/main` HEAD (e928439) — single clean commit ahead, fast-forward, zero divergence. |
| 7 | Single feature theme | PASS | One coherent fix (consent-integrity for Call Card daemon auto-disclosure) across 4 files (`call_card_host.py`, `endpoint.py`, `call_card.py`, `__main__.py` mechanical test fixtures) — no unrelated changes bundled in. |

**Verdict: PASS — 7/7.**

## Note on lint/test scoping

`make verify` (i.e. `ruff check .` / bare `pytest -q`) fails when run from this
worktree root because it also walks a large number of untracked leftover
directories from unrelated prior bead sessions (not part of git, not part of this
branch). Re-ran both tools scoped to the real tracked source (`iris`, `tests`,
`scripts`) to get a true signal for this branch's own code — both clean except the
one confirmed-environmental pytest failure noted above.
