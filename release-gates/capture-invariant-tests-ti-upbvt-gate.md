# Release Gate: Capture Single-Ownership Regression Guard Tests

**Bead:** ti-upbvt (needs-deploy)
**Source review bead:** ti-p3r1p
**Branch:** `deploy/capture-invariant-tests-ti-upbvt`
**Commit:** `0164579` (cherry-picked from `dcad629` on `tests/console-daemon-capture-invariant-ti-go46m`)
**Gate evaluated:** 2026-07-03

---

## Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | **PASS** | ti-p3r1p notes: reviewer PASS verdict, tests read directly and confirmed non-vacuous |
| 2 | Acceptance criteria met | **PASS** | See below |
| 3 | Tests pass | **PASS** | 1617 passed, 1 skipped, 3 xpassed, 0 failed |
| 4 | No high-severity findings open | **PASS** | No findings recorded against this commit |
| 5 | Final branch is clean | **PASS** | `git status` shows only untracked non-source artifacts (venv, egg-info) |
| 6 | Branch diverges cleanly from main | **PASS** | Cherry-pick of `dcad629` onto `origin/main` (088b7da) applied with no conflicts |
| 7 | Single feature theme | **PASS** | 1 commit, 1 file (`tests/test_console_app.py`, +49 lines), regression coverage for one invariant |

**Overall gate: PASS**

---

## Acceptance Criteria (ti-1fpil / ti-go46m capture single-ownership invariant)

- [x] `test_daemon_event_call_connected_does_not_start_ride_along_capture` — proxy-mode `call_connected` must NOT call `_attach_call_audio`/`_begin_ride_along`
- [x] `test_direct_call_connected_still_starts_ride_along_capture` — contrast test confirms direct-mode path DOES call both, proving the guard is meaningful (not vacuous)

---

## Test Results

```
.venv/bin/pytest -q (on deploy/capture-invariant-tests-ti-upbvt, origin/main + dcad629 only)

1617 passed, 1 skipped, 3 xpassed in 83.62s
```

No failures. Skip/xpass counts are pre-existing environment artifacts, not related to this change.

---

## Branch Composition

| Commit | Description |
|--------|-------------|
| `0164579` | tests(console): regression guard for capture single-ownership invariant (ti-go46m) |

Deliberately shipped independently of ti-cha1h's doc-comment deploy (same feature, ti-1fpil, thematically) — this commit branches directly off `origin/main` with zero dependency on the tangled `feat/console-crash-exit-message-ti-00jr4-2` lineage, so bundling would have added no value and only inherited that branch's sequencing constraints.
