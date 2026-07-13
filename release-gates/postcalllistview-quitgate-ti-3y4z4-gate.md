# Release Gate: quit-gate fix for PostCallListView (ti-3y4z4 / ti-eppmx)

**Date:** 2026-07-13
**Deploy bead:** ti-3y4z4
**Source beads:** ti-zox32 (review), ti-eppmx (origin bug, closed)
**Branch:** `deploy/postcalllistview-quitgate-ti-3y4z4` (stacked on `deploy/baseline-health-console-ti-0lw2d`, carrying commit `efd14a6` cherry-picked from `feat/baseline-broadcast-ti-pugo3-3-1`)
**Commit evaluated:** `5faa1ba`

## Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | PASS | ti-zox32 closed PASS by reviewer tincan-iris/reviewer |
| 2 | Acceptance criteria met | PASS | `check_action()`'s quit isinstance gate now includes `PostCallListView` alongside `HelpScreen`/`HealthScreen`/`ContactsScreen`, closing the gap where the priority `"q"` binding on `PostCallListView` (verified at `iris/console/list_view.py:72`) could be pre-empted by the app-level quit gate |
| 3 | Tests pass | PASS | `pytest -q tests/`: 1907 passed, 1 pre-existing unrelated failure, 3 xpassed — identical to ti-0lw2d's own count on this stack, since this commit adds no tests (coverage is the next bead, ti-gaqva, explicitly blocked-by this one) |
| 4 | No high-severity findings | PASS | No OWASP-relevant surface (pure TUI keybinding-dispatch gate, no external input); ruff clean |
| 5 | Final branch is clean | PASS | Working tree clean at `5faa1ba`; no uncommitted content |
| 6 | Branch diverges cleanly from main | PASS | Cherry-pick applied with zero conflicts on top of the ti-0lw2d stacked base |
| 7 | Single feature theme | PASS | One cohesive, single-file change: extending the quit-gate isinstance check |

## Discovery

`efd14a6` adds `PostCallListView` to the same `check_action()` isinstance gate that `HealthScreen` was added to by ti-0lw2d — a real ordering dependency (the diff's context lines reference the gate as it looks after `HealthScreen` was added), so this was stacked on top of `deploy/baseline-health-console-ti-0lw2d` rather than cut independently from `origin/main`. Applied with zero conflicts.

Diff scope: `iris/console/app.py` only (+9/-7), scoped entirely to the isinstance gate — matches the bead description exactly. `PostCallListView`'s own priority-`True` `"q"` → `app.pop_screen` binding (`iris/console/list_view.py:72`) and its pre-existing import in `app.py` were both verified directly in source per the bead's own evidence.

`PostCallReviewScreen` is confirmed absent from this branch (out of scope for this bead; will reconcile as an ordinary merge conflict whenever `feat/callcard-after-data-layer-ti-hb2dx` lands separately — not a gating concern here).

Full suite: `pytest -q tests/` (top-level `tests/` explicitly) → **1907 passed, 1 failed, 3 xpassed** — identical to ti-0lw2d's count, confirming zero regressions from this single-file change. The one failure, `tests/test_daemon_call_card_config.py::test_main_passes_loaded_config_to_call_card_host`, is the same pre-existing environmental daemon-PID-lock issue (tracked as ti-8wtzr), confirmed unrelated. `ruff check iris/ tests/ scripts/` clean.

No pre-existing test coverage for this gate logic exists yet by design — the follow-up needs-tests bead (ti-gzyag → deploy bead ti-gaqva) is explicitly wired `blocked-by` this bead and stacks directly on top next, per this rig's accepted builders-don't-author-tests convention (same pattern as ti-pugo3.3.2/.3.3).

## Conclusion

Gate **PASS**. This PR should be opened against the ti-0lw2d PR's branch (stacked), carrying `efd14a6` only, and merged after ti-26ad0/ti-dy06r/ti-0lw2d land.
