# Release Gate: disclose-by-default DisclosureCard/CallCardPanel redesign (ti-foocd)

**Date:** 2026-07-13
**Deploy bead:** ti-foocd
**Source beads:** ti-cxeb0/ti-n9vey (redesign), builder re-merge round-trip after an earlier gate FAIL
**Branch:** `deploy/disclosure-card-redesign-ti-foocd` (= `origin/gc-builder-c40f9914d66e` at `c4c3594`, already merged with current `origin/main`)
**Commit evaluated:** `c4c3594`

## Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | PASS | ti-cxeb0 reviewed and PASSED by tincan-iris/reviewer after one REQUEST-CHANGES round-trip (resolved: reintroduced border_title markup-injection gap, fixed via merge picking up `fe18725`'s escape) |
| 2 | Acceptance criteria met | PASS | Implements ti-n9vey design doc §1-§4/§7: `DisclosureState` changes, `render()` rewrite, WCAG contrast fix, focus-trap removal, `apply_daemon_state`, `suppress_active_disclosure` |
| 3 | Tests pass | PASS | `pytest -q tests/`: 1843 passed, 1 pre-existing unrelated failure, 3 xpassed — matches builder's independently-reported count exactly (1833 prior + PR #173's 10 new tests) |
| 4 | No high-severity findings | PASS | Five non-blocking review items independently traced and confirmed correct/non-blocking (see ti-cxeb0 notes); no open high-severity findings; ruff clean |
| 5 | Final branch is clean | PASS | Working tree clean at `c4c3594`; no uncommitted content |
| 6 | Branch diverges cleanly from main | PASS | Branch already merged forward with current `origin/main` tip (`3071105`); `git merge-base --is-ancestor origin/main <branch>` confirms up to date, no rebase needed |
| 7 | Single feature theme | PASS | One cohesive theme: disclose-by-default redesign. The merge-forward commit only reconciles one incidental test assertion (WCAG contrast color) with an unrelated already-merged PR; no scope creep |

## Discovery

This bead FAILed an earlier deployer gate pass: `origin/main` had advanced past this branch's reviewed base (`e928439`) to `3071105` via PR #173 (test-only, `tests/test_call_card_markup_escape.py`), and a rebase produced one genuine semantic conflict — this branch's own WCAG-contrast color change (`#cbd5e1`) vs. main's pre-existing assertion (`[yellow]`). That was routed back to builder rather than resolved from the deployer seat, since it required judgment about which assertion should win (this branch's intentional change).

Builder resolved it with `git merge origin/main` (not rebase, to avoid disrupting another live worktree still parked on the pre-merge commit), keeping this branch's `#cbd5e1` assertion and accepting all 10 of PR #173's new tests verbatim. Result pushed as a fast-forward to `origin/gc-builder-c40f9914d66e` (merge commit `c4c3594`, parents `400ac9b` + `3071105`) and re-submitted as `needs-deploy`.

Re-verified fresh in this gate pass (not reusing builder's self-reported numbers): re-fetched `origin/main` and `origin/gc-builder-c40f9914d66e`, confirmed both still at the same SHAs as the builder's fix (no further drift), confirmed `origin/main` is still an ancestor of the branch tip. `ruff check iris/ tests/ scripts/` clean. `pytest -q tests/` (top-level `tests/` explicitly, avoiding the sibling `ti-*-needs-deploy-*` nested worktree directories in this shared deployer worktree) → **1843 passed, 1 failed, 3 xpassed**, matching the builder's own count exactly. The one failure, `tests/test_daemon_call_card_config.py::test_main_passes_loaded_config_to_call_card_host`, is the same pre-existing environmental daemon-PID-lock issue already confirmed unrelated in prior gates (already filed as ti-8wtzr).

`ti-tk06c` (validator's follow-up test coverage for this redesign, 4 scenarios from design doc §6, commit `a40f3c8`) is a separate, not-yet-integrated branch and was never a gating dependency — sequencing its merge is independent of this deploy.

## Conclusion

Gate **PASS**. Opening PR against `main` carrying `c4c3594` (already-merged-forward branch, no cherry-pick needed).
