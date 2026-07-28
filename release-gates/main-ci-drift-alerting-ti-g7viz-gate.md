# Release Gate: Main-CI-drift alerting — schedule trigger + local watchdog (ti-g7viz)

**Date:** 2026-07-28
**Deploy bead:** ti-g7viz
**Source review bead:** ti-xz84y (PASS, closed)
**Source build bead:** ti-4tq52
**Provenance branch:** `builder/ti-4tq52` (shared builder branch — provenance only, not a push target)
**Commit evaluated:** `530fd8f` (reviewed commit; deploy branch cut from this exact SHA)
**Deploy branch:** `deploy/ti-g7viz-gate`

## Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 6 | Branch diverges cleanly from main | PASS | `merge-base(530fd8f, origin/main)` == `origin/main` tip (`95d0166`) — zero commits of drift. `git merge-tree` produces a clean `merged` result, no conflicts. No self-rebase needed. |
| 1 | Review PASS present | PASS | ti-xz84y closed 2026-07-28, close_reason=`pass`, notes record `verdict: pass` from reviewer tincan-iris/reviewer. |
| 2 | Acceptance criteria met | PASS | Reviewer mapped every acceptance criterion implied by the module docstring to a named covering test (schedule trigger present/interval/off-hour, existing triggers+jobs.test untouched, bootstrap-no-alert, sha-change resets state, single-flake recovers silently, confirmed-drift files bead + alerts both channels, debounce, stale-schedule watchdog-of-the-watchdog, ruff-pin regression). Independently re-verified by reading `scripts/ci_driftwatch.py` in full and re-running the 13 driftwatch/schedule/ruff-pin tests in isolation — all green, behavior matches docstring contract. |
| 3 | Tests pass | PASS | Full suite (isolated clean worktree at `530fd8f`, matching `make test` / CI's `pytest -q`): **1915 passed, 3 xpassed, 1 failed, 0 skipped**. The 1 failure (`tests/test_daemon_call_card_config.py::test_main_passes_loaded_config_to_call_card_host`) is a confirmed pre-existing host-environmental issue, unrelated to this diff: a real long-running `python3.14 -m iris.daemon` process (pid 2276, running since Jul 26) holds this machine's exclusive daemon PID lock outside any test, causing `daemon_main.main()` to exit before constructing `CallCardHost`. Confirmed via `ps -p 2276` (real process) and via bd memory `live-iris-daemon-blocks-call-card-config-test` (same root cause documented on this rig since 2026-07-05). Confirmed the diff range (`merge-base(530fd8f,origin/main)..530fd8f`) touches **zero** files under `tests/test_daemon_call_card_config.py` or `iris/daemon/`. Driftwatch-specific tests run in isolation: `pytest tests/test_ci_driftwatch.py tests/test_ci_workflow_schedule_trigger.py tests/test_ci_workflow_ruff_pin.py` → **13 passed, 0 failed** (6 + 5 + 2, matching reviewer's count). Lint: `ruff check .` (0.15.22, matching CI's version pin) → **0 issues**. Note: the first lint/test pass run from the shared persistent deployer worktree surfaced ~50 ruff errors and 2757 pytest collection errors — these came entirely from stray untracked bead-scratch directories accumulated in that shared worktree from unrelated prior sessions (e.g. `ti-zd5os-.../tests/*`, `ti-03yy3/tests/*`), not from the reviewed commit. Re-ran both commands in a clean isolated `git worktree add --detach` at exactly `530fd8f` to get an uncontaminated, CI-faithful result (recorded above). |
| 4 | No high-severity review findings open | PASS | Reviewer found 1 minor (OWASP A09, insufficient logging on the `gc bd update --assignee=` subprocess call at `ci_driftwatch.py:182-183`), 0 blockers/majors. Independently confirmed by reading the full script: the finding is accurate — that one call lacks `check=True`/error logging unlike every sibling subprocess call in the file — and is genuinely non-blocking (degrades to a stale bead assignee on a rare failure; the mail/notify-fanout alerts in the same code path fire independently and are not affected). |
| 5 | Final branch is clean | PASS | `deploy/ti-g7viz-gate` reset to `530fd8f` exactly; only this gate file is added on top. |
| 7 | Single feature theme | PASS | All changes are one cohesive subsystem — CI-drift detection: `.github/workflows/ci.yml` schedule trigger (+7 lines, `jobs.test` untouched), `scripts/ci_driftwatch.py` (the watchdog), its systemd `.service`/`.timer` units, and their tests. No unrelated surface touched. |

## Test evidence detail

- **Command (CI-equivalent, byte-for-byte per Makefile's NFR1 comment):** `ruff check .` then `pytest -q`, matching `.github/workflows/ci.yml`'s `Lint`/`Run tests` steps and `make verify`.
- **Environment:** isolated `git worktree add --detach <scratch> 530fd8f` — a clean checkout with none of the shared deployer worktree's accumulated untracked cruft.
- **Lint:** `ruff check .` → `All checks passed!` (exit 0).
- **Full suite:** `1915 passed, 3 xpassed, 1 failed, 3 warnings in 104.64s`. The 3 xpassed and remaining warnings (a pre-existing thread-exception in `test_console_app.py`, GI deprecation warnings) are pre-existing/unrelated — diff range confirmed to not touch those files either.
- **Driftwatch-scoped suite:** `pytest -q tests/test_ci_driftwatch.py tests/test_ci_workflow_schedule_trigger.py tests/test_ci_workflow_ruff_pin.py` → `13 passed`.

## Conclusion

**Gate: PASS.** Deploy branch `deploy/ti-g7viz-gate` cut from reviewed commit `530fd8f`, pushed, PR opened against `origin/main`. Merge-request routed to mayor (tincan-iris is a repo we maintain — origin `quad341/tincan-iris`, not an upstream-contributor-only repo).
