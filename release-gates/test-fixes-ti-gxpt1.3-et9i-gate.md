# Release Gate: test-fixes-ti-gxpt1.3-et9i

**Branch:** `fix/test-fixes-ti-gxpt1.3-et9i`  
**Commits:** 64e2e45 (cherry-pick of 43f287f), ac0d818 (cherry-pick of 648cf3f)  
**Bead:** ti-0q5w.5  
**Date:** 2026-06-25  
**Deployer:** tincan-iris/deployer

---

## Criteria Evaluation

| # | Criterion | Result |
|---|-----------|--------|
| 1 | Review PASS present | **PASS** |
| 2 | Acceptance criteria met | **PASS** |
| 3 | Tests pass | **PASS** (19 pre-existing TDD failures; 2 env-sensitive failures fixed) |
| 4 | No high-severity review findings open | **PASS** |
| 5 | Final branch is clean | **PASS** |
| 6 | Branch diverges cleanly from main | **PASS** |
| 7 | Single feature theme | **PASS** |

**Overall: PASS**

---

## Evidence

### Criterion 1 — Review PASS

Review bead **ti-0q5w.4** (closed, PASS):

> REVIEW VERDICT: PASS  
> Reviewer: tincan-iris/reviewer (2026-06-25)  
> Commits: 43f287f (test_roster_migration.py F-COV-04—F-COV-13) + 648cf3f (test_stt.py / test_tts.py server.available() mock fix)  
> "Ready to deploy: fix/test-fixes-ti-gxpt1.3-et9i"

### Criterion 2 — Acceptance Criteria

From ti-0q5w.4 bead:
- [x] `test_roster_migration.py` — 19 TDD tests covering F-COV-04 through F-COV-13 (v2 enum renames, posture, schedules stub) — confirmed present in 64e2e45
- [x] `test_stt.py` / `test_tts.py` — `server.available()` mocked via `patch.object` to isolate fallback-path tests — confirmed in ac0d818; both tests now pass
- [x] `python -m pytest tests/test_roster_migration.py tests/test_stt.py tests/test_tts.py` — all non-TDD tests pass; TDD failures are intentional pending v2 implementation

### Criterion 3 — Tests Pass

```
19 failed, 1117 passed, 4 skipped, 3 xpassed, 2 warnings in 9.07s
```

**19 failing tests** — all in `tests/test_roster_migration.py`, all v2 TDD tests for F-COV-04 through F-COV-13:

**Key finding:** `git diff origin/main HEAD -- tests/test_roster_migration.py` shows only ONE test function change — `test_v2_migration_transactional_rollback_on_failure` had a `monkeypatch` parameter added. All other 18 failing tests pre-exist on `origin/main` and were already failing there (v2 implementation not yet landed). **This branch introduces zero net new failures.**

**2 tests fixed** — `test_stt.py::test_default_stt_is_faster_whisper` and `test_tts.py::test_default_tts_uses_kokoro_when_available` were failing on `origin/main` when live servers are running. Commit ac0d818 mocks `server.available()` to isolate the fallback path; both now pass (confirmed: `12 passed` on STT/TTS suite).

### Criterion 4 — No High-Severity Findings

From ti-0q5w.4 review: mock correctness verified, no flakiness, no anti-patterns. No HIGH or CRITICAL findings.

### Criterion 5 — Branch Clean

```
On branch fix/test-fixes-ti-gxpt1.3-et9i
nothing added to commit but untracked files present (untracked: .beads/, docs/plans/, tincan_iris.egg-info/ — not project source)
```

### Criterion 6 — Diverges Cleanly from Main

`git merge-tree` check: no conflict markers. Branch is based on fd90004 (5 commits behind origin/main at 39eab50), but merges cleanly with no conflicts.

### Criterion 7 — Single Feature Theme

Two commits on top of main — both in `tests/`:
```
ac0d818 fix(tests): mock server.available() to isolate stt/tts fallback path tests
64e2e45 tests(roster_migration): v2 migration suite — enum renames, posture, schedules stub (ti-gxpt.1.3)
```

Both touch only test files (`tests/test_roster_migration.py`, `tests/test_stt.py`, `tests/test_tts.py`). Single coherent theme: test-suite quality fixes. No production code changes.
