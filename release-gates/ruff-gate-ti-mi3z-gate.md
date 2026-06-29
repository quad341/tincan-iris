# Release Gate: ruff lint gate + 105 violation cleanup (ti-mi3z / ti-2mmj)

**Date:** 2026-06-26
**Bead:** ti-2mmj (deploy) / ti-mi3z (source)
**Branch:** fix/test-fixes-ti-gxpt1.3-et9i
**Target commit:** 7a49143 (chore(lint): add ruff gate to CI + fix all 105 violations)

## Gate Result: FAIL

---

## Criteria Evaluation

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | PASS | Reviewer PASS in bead ti-2mmj notes |
| 2 | Acceptance criteria met | PASS | ruff exits clean, gate fails on deliberate unused import, 1104 tests passing |
| 3 | Tests pass | NOT RUN | Blocked by criterion 6 failure |
| 4 | No high-severity review findings | PASS | No unresolved HIGH findings per bead notes |
| 5 | Final branch clean | NOT RUN | Blocked by criterion 6 failure |
| 6 | Branch diverges cleanly from main | **FAIL** | Cherry-pick of 7a49143 onto origin/main has genuine conflicts |
| 7 | Single feature theme | PASS | Pure lint cleanup — no behavior changes |

---

## Criterion 6 Failure Detail

`7a49143` cannot be cherry-picked cleanly onto `origin/main`. The lint commit
modifies test files that were added by parent commits on `fix/test-fixes-ti-gxpt1.3-et9i`
but have not yet landed on `origin/main`.

**Conflicts encountered:**

```
CONFLICT (modify/delete): tests/test_call_pipeline.py
  — deleted in HEAD (origin/main), modified in 7a49143
CONFLICT (modify/delete): tests/test_pipecat_stt.py
  — deleted in HEAD (origin/main), modified in 7a49143
CONFLICT (modify/delete): tests/test_pipecat_tts.py
  — deleted in HEAD (origin/main), modified in 7a49143
CONFLICT (modify/delete): tests/test_ride_along_console.py
  — deleted in HEAD (origin/main), modified in 7a49143
CONFLICT (content): iris/console/app.py
CONFLICT (content): tests/test_roster_migration.py
```

**Root cause:** The ruff lint commit was authored on top of several TDD stub commits
(`0394525`, `85957ac`, `580aca4`) that created these test files but have not been
deployed to `origin/main`. The lint commit fixes violations in those files, making
it a dependent cherry-pick — it cannot land independently.

**Resolution path:** The builder must either:

1. **Rebase approach:** Create a deploy branch that includes the prerequisite
   commits (TDD stubs: `0394525`, `85957ac`, `580aca4`) before `7a49143`, so
   the ruff gate lands with its dependencies. These commits will need their own
   review beads first.

2. **Standalone approach:** Re-author the ruff gate commit against `origin/main`
   HEAD directly, so it only touches files that already exist on main (skipping
   lint fixes for files not yet on main). The gate CI addition can still land
   independently; the file-specific fixes can land as part of each feature's
   own PR.

Either path requires a new review cycle before re-deploy.
