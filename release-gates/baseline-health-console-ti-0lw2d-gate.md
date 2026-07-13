# Release Gate: Console baseline health pill + Health panel + [H] keybind (ti-0lw2d / ti-pugo3.3.2)

**Date:** 2026-07-13
**Deploy bead:** ti-0lw2d
**Source beads:** ti-0b0l1 (review, both rounds), ti-pugo3.3.3 (validator test coverage, bundled)
**Branch:** `deploy/baseline-health-console-ti-0lw2d` (stacked on `deploy/baseline-broadcast-daemon-ti-dy06r`, carrying commits `9db2950` + `cb82ec4` cherry-picked from `feat/baseline-broadcast-ti-pugo3-3-1`, plus `ec894fd` cherry-picked from `tests/baseline-health-pill-panel-broadcast-ti-pugo3-3-3`)
**Commit evaluated:** `7afb706`

## Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | PASS | ti-0b0l1 closed PASS by reviewer tincan-iris/reviewer, second pass after one request-changes round (round 1: unescaped daemon check data into Textual markup sinks; round 2/`cb82ec4`: fixed via `escape_for_content()`) |
| 2 | Acceptance criteria met | PASS | All 5 acceptance criteria per bead: 5-state pill rendering, `HealthScreen` table + row-collapsing + conditional FIXES section, `[H]` binding + scoped q/esc close, pre-broadcast snapshot seeding, full suite/ruff clean |
| 3 | Tests pass | PASS | `pytest -q tests/`: 1907 passed, 1 pre-existing unrelated failure, 3 xpassed — exactly 1870 (this stack's running baseline) + 37 new tests from the bundled validator commit |
| 4 | No high-severity findings | PASS | Round-1 markup-injection finding fully closed in round 2; manual adversarial bracket-injection check against both fixed call sites (`_format_row()`/`_fixes_text()` in `health_screen.py`) confirms the injection class is closed; ruff clean |
| 5 | Final branch is clean | PASS | Working tree clean at `7afb706`; no uncommitted content |
| 6 | Branch diverges cleanly from main | PASS | Cherry-picks applied with zero conflicts on top of the ti-dy06r stacked base |
| 7 | Single feature theme | PASS | One cohesive theme: console-side baseline health surfacing (pill + panel + keybind) plus its own regression tests. No unrelated content |

## Discovery

`cb82ec4` is the round-2 fix commit on top of the round-1 implementation (`9db2950`) — both cherry-picked in order (`9db2950` then `cb82ec4`), analogous to the `345ea7a`→`3c8297a` pattern already established for ti-26ad0. The original branch had ported `iris/console/_markup.py` forward as a new file because it predates that helper's merge to `origin/main` (via PR #169 / ti-c7d8a); since this stacked deploy branch is built on top of `origin/main`, which already has the real `_markup.py`, the cherry-pick resolved against the already-present file with no conflict and no duplicate — confirmed `iris/console/_markup.py` present and unmodified by this cherry-pick.

Diff scope: `iris/console/app.py` (+52/-5, `[H]` keybind + screen registration + snapshot seeding) and `iris/console/health_screen.py` (new, 204 lines) — matches the bead description.

Following this session's established fix+test bundling precedent (ti-46cnx/ti-1jayi, ti-m7x5v/ti-l9arm), also cherry-picked `ec894fd` — the validator's regression-test commit for this exact feature, posted directly onto this bead's own notes after ti-pugo3.3.3 closed. It covers all 5 pill states, `HealthScreen` table rendering including 5+-row collapsing and the conditional FIXES section, `check_action()`'s quit-gate for `HealthScreen`, and an AST-based guard that the daemon's `on_transition` closure fires both `degradation_notify.on_baseline_transition` and the console broadcast (i.e., regression coverage spanning both this bead and ti-dy06r). Applied with zero conflicts; purely additive (two new test files, 509 lines, no production code touched).

Full suite: `pytest -q tests/` (top-level `tests/` explicitly) → **1907 passed, 1 failed, 3 xpassed** = exactly 1870 (ti-dy06r's running count on this stack) + 37 new tests (32 in `test_health_panel.py` + 5 in `test_baseline_broadcast_composition.py`), matching the validator's own reported count exactly. The one failure, `tests/test_daemon_call_card_config.py::test_main_passes_loaded_config_to_call_card_host`, is the same pre-existing environmental daemon-PID-lock issue (tracked as ti-8wtzr), confirmed unrelated. `ruff check iris/ tests/ scripts/` clean.

**Deploy-sequencing note carried forward:** `ti-3y4z4` (PostCallListView quit-gate fix) adds `PostCallListView` alongside `HelpScreen`/`HealthScreen`/`ContactsScreen` in `app.py`'s `check_action()` isinstance gate — it requires `HealthScreen` to already be part of that gate, which this bead introduces, so it stacks on top of this branch next.

## Conclusion

Gate **PASS**. This PR should be opened against the ti-dy06r PR's branch (stacked), carrying `9db2950` + `cb82ec4` + `ec894fd`, and merged after ti-dy06r (and transitively ti-26ad0) land.
