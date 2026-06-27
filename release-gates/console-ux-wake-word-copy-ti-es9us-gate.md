# Release Gate: console-ux-wake-word-copy-ti-es9us

**Branch:** `fix/test-fixes-ti-gxpt1.3-et9i`  
**Reviewed commit:** `7c97e74` (fix(console): wake-word text 'Hey Iris' + copy-last-reply binding)  
**Bead:** ti-es9us  
**Source bead:** ti-vrhe8 (review: PASS by reviewer-gm-wisp-45x8peo)  
**Date:** 2026-06-27  
**Deployer:** deployer-gm-wisp-8q7p2ht (tincan-iris/deployer)

---

## Criteria Evaluation

| # | Criterion | Result |
|---|-----------|--------|
| 1 | Review PASS present | **PASS** |
| 2 | Acceptance criteria met | **PASS** |
| 3 | Tests pass | not evaluated (gate failed earlier) |
| 4 | No high-severity review findings open | **PASS** |
| 5 | Final branch is clean | **PASS** (working tree clean) |
| 6 | Branch diverges cleanly from main | **FAIL** — 7 merge conflicts |
| 7 | Single feature theme | not evaluated (gate failed earlier) |

**Overall: FAIL**

---

## Evidence

### Criterion 1 — Review PASS

Review bead **ti-vrhe8** (closed):

> REVIEW VERDICT: PASS  
> Reviewer: reviewer-gm-wisp-45x8peo  
> Commit: 7c97e7453a39218cf3f15fcf37e8893ceeed4895 on fix/test-fixes-ti-gxpt1.3-et9i  
> Style/Security/Spec/Coverage: all PASS

### Criterion 2 — Acceptance Criteria

From ti-vrhe8:
- [x] All 5 user-facing 'Iris, …' strings updated to 'Hey Iris, …'
- [x] `action_copy_last` implemented with `[y]` binding; wl-copy → xclip → xsel fallback; clipboard content via stdin (no injection)
- [x] Pre-existing test failures unrelated; 1163 tests pass

### Criterion 4 — No High-Severity Findings

From ti-vrhe8: PASS on style, security, spec, coverage. No HIGH or CRITICAL findings.

### Criterion 5 — Branch Clean

Working tree clean. Commit `7c97e74` is the LOCAL tip of `fix/test-fixes-ti-gxpt1.3-et9i` (not yet pushed to origin).

### Criterion 6 — FAIL: Branch Diverges From Main With Conflicts

Same branch as ti-xsgx3 gate. `git merge-tree --write-tree origin/main fix/test-fixes-ti-gxpt1.3-et9i` reports 7 conflict files:

```
CONFLICT (content):   iris/brain.py
CONFLICT (content):   iris/console/app.py
CONFLICT (content):   tests/test_iris_up.py
CONFLICT (add/add):   tests/test_pipecat_stt.py
CONFLICT (content):   tests/test_roster_migration.py
CONFLICT (content):   tests/test_stt.py
CONFLICT (content):   tests/test_tts.py
```

**Root cause:** Branch was cut from `fd90004` (commit #91). Main is now at #108+. Branch is 17+ commits behind main and conflicts in several actively modified files.

---

## Recommended Builder Action

`7c97e74` is a self-contained, reviewed fix touching only `iris/console/app.py`. It can be deployed independently.

**Recommended fix:** Cut a fresh branch off `origin/main` with just this commit:

```bash
git checkout -b fix/console-wake-word-copy origin/main
git cherry-pick 7c97e74  # fix(console): wake-word text 'Hey Iris' + copy-last-reply binding
# Verify tests pass, then create a new deploy bead
```
