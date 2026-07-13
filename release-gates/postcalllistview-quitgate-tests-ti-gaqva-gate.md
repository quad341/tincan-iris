# Release Gate: check_action quit-gate test coverage for PostCallListView (ti-gaqva / ti-gzyag)

**Date:** 2026-07-13
**Deploy bead:** ti-gaqva
**Source beads:** ti-lyoop (review), ti-gzyag (validator test-authoring, closed)
**Branch:** `deploy/postcalllistview-quitgate-tests-ti-gaqva` (stacked on `deploy/postcalllistview-quitgate-ti-3y4z4`, carrying commit `067db3b` cherry-picked from `feat/baseline-broadcast-ti-pugo3-3-1`)
**Commit evaluated:** `1228e97`

## Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | PASS | ti-lyoop closed PASS by reviewer tincan-iris/reviewer |
| 2 | Acceptance criteria met | PASS | Both required cases from ti-gzyag covered: quit gated while `PostCallListView` is active, and quit still fires normally from a base screen |
| 3 | Tests pass | PASS | `pytest -q tests/`: 1909 passed, 1 pre-existing unrelated failure, 3 xpassed — exactly 1907 (ti-3y4z4's count on this stack) + 2 new tests |
| 4 | No high-severity findings | PASS | No OWASP-relevant surface (pure TUI test code, no external input); ruff clean |
| 5 | Final branch is clean | PASS | Working tree clean at `1228e97`; no uncommitted content |
| 6 | Branch diverges cleanly from main | PASS | Cherry-pick applied with zero conflicts on top of the ti-3y4z4 stacked base |
| 7 | Single feature theme | PASS | One cohesive, single-file, purely-additive test change |

## Discovery

This bead carries an explicit `blocked-by` dependency on ti-3y4z4 in bd: its two new tests require `efd14a6` (the `check_action` isinstance-gate fix deployed via ti-3y4z4, this session) to be present, or they fail RED. Deployed in the correct order — stacked directly on top of `deploy/postcalllistview-quitgate-ti-3y4z4` rather than cut independently. `067db3b` applied with zero conflicts.

Diff scope: `tests/test_console_app.py` only (+62, purely additive) — matches the bead description exactly (single-parent commit on `efd14a6`, no merge, no branch contamination, confirmed via `git log --format=%P`).

**Independently verified meaningfulness** (not just trusting the reviewer's own revert-test claim): reverted `efd14a6` in this worktree and re-ran the two new tests — `test_quit_gated_while_post_call_list_view_active` failed exactly as predicted (`assert app._exit is False` → `AssertionError: assert True is False`, i.e. the app quit when it shouldn't have), while `test_quit_fires_on_base_screen` still passed (confirming it isn't itself dependent on the fix, correctly exercising the unrelated base-screen path). Aborted the revert and reconfirmed both tests green again on the real fix. This proves real regression coverage, not a tautology.

Full suite: `pytest -q tests/` (top-level `tests/` explicitly) → **1909 passed, 1 failed, 3 xpassed** = exactly 1907 (ti-3y4z4's running count) + 2 new tests. The one failure, `tests/test_daemon_call_card_config.py::test_main_passes_loaded_config_to_call_card_host`, is the same pre-existing environmental daemon-PID-lock issue (tracked as ti-8wtzr), confirmed unrelated. `ruff check iris/ tests/ scripts/` clean.

Verified `CallList`/`PostCallListView` constructor usage and the `check_action` isinstance gate directly against source (`iris/list_store.py`, `iris/console/list_view.py`, `iris/console/app.py`) — consistent with the fix this test covers.

This is the last code-bearing bead in the baseline-health epic stack; `ti-qss41` (docs/BASELINE.md) is the remaining bead and is unrelated in content (docs-only), to be gated and PR'd separately with its own sequencing note.

## Conclusion

Gate **PASS**. This PR should be opened against the ti-3y4z4 PR's branch (stacked), carrying `067db3b` only, and merged last in this chain (after ti-26ad0/ti-dy06r/ti-0lw2d/ti-3y4z4 land).
