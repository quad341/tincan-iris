# Release Gate: [?] help screen, always-visible binding + startup hint (ti-00jr4.1)

**Date:** 2026-07-04
**Deploy bead:** ti-hjl8a
**Source bead:** ti-00jr4.1 (build) / ti-04dqq (review, PASS)
**Branch:** `feat/console-help-screen-ti-00jr4-1` (cherry-pick of `2776212` onto `origin/main`)
**Commit evaluated:** `74dd3cf` (cherry-pick) / source `2776212`

## Gate Result: PASS

## Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | PASS | ti-04dqq closed by tincan-iris/reviewer: "All ti-00jr4.1 ACs satisfied" |
| 2 | Acceptance criteria met | PASS | Independently re-checked against the diff: `Binding("question_mark", "help", "help")` first in `BINDINGS`, `show` defaults `True` (confirmed via `inspect.signature(Binding.__init__)` on installed textual); `HelpScreen` q/escape both `priority=True` → `app.pop_screen`; focus moves to `#help-body` on mount, to `#log` on unmount; help text matches design doc Section 2 (COPY & BUG-FILING, then TALK/CALL/OTHER); Shift/Alt terminal-selection tip confirmed to appear exactly once app-wide (`grep -rn` across `iris/`); one new `[dim]` startup-hint line adjacent to the session-log line; `check_action` quit-gate present and scoped to `HelpScreen` only |
| 3 | Tests pass | PASS | `pytest -q`: 1616 passed, 3 xpassed, 2 unrelated deprecation warnings; `ruff check .`: all checks passed |
| 4 | No high-severity review findings open | PASS | No findings (HIGH or otherwise) recorded against this commit in ti-04dqq or ti-hjl8a notes |
| 5 | Final branch is clean | PASS | `git status` shows no uncommitted tracked-file changes |
| 6 | Branch diverges cleanly from main | PASS | Cherry-pick of `2776212` applied with zero conflicts; diff vs `origin/main` is exactly `iris/console/app.py` (+14) and new file `iris/console/help_screen.py` (+90) |
| 7 | Single feature theme | PASS | Single subsystem (console TUI help/discoverability surface); one binding + one screen + one startup hint, all serving the same FR4 "bootstrap key" theme from ti-00jr4 |

## Notes

- The builder's own session branch (`gc-builder-dd400ec40fa5`) and this deployer's own session branch both carry unrelated stacked commits (DisclosureCard widget `cd820c1`, PostCallEnricher validator tests `a6192f1`) beneath the help-screen commit. Neither is "origin/main plus only the intended commit," so a clean branch was cut from `origin/main` and only `2776212` was cherry-picked onto it, isolating exactly this feature.
- Test count (1616) is higher than the reviewer's reported baseline (1557) because `origin/main` has since gained unrelated commits (disclosure card, enricher tests) from other already-shipped work; all pass, zero regressions attributable to this change.
- Out of scope for this deploy bead (noted for tracking, not acted on here): ti-00jr4.4 (validator, CLOSED) added 14 tests for this exact feature on branch `gc-validator-423988ab50e6` (commit `78de176`), verified 14/14 passing against this implementation in a disposable worktree per ti-04dqq's comments — but no `needs-deploy` bead yet exists to ship that test commit. Flagged to mayor; not bundled into this PR since ti-hjl8a's scope is explicitly commit `2776212` only.
