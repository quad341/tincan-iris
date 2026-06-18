# Release Gate: memory PRIMARY KEY + vec0 DDL fix (ti-2dat)

**Bead:** ti-2dat (deploy acknowledgment) / ti-mwd6 (review source) / ti-59wi, ti-k15u (build sources)
**Commit:** 90276fb on origin/main
**Type:** Post-merge acknowledgment — commit was merged to origin/main before deploy review cycle completed. No PR needed; gate closes the deploy bead.
**Date:** 2026-06-16
**Gate result:** PASS

---

## Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | ✅ PASS | ti-mwd6 notes: first-pass reviewer (claude/tincan-iris/reviewer) PASS. Evidence: enable_load_extension finally-guarded, PRIMARY KEY on session_id, vec0 float[dim] DDL confirmed, all SQL parameterized, contact_id NOT NULL guards, exception swallowing intentional/annotated. |
| 2 | Acceptance criteria met | ✅ PASS | See acceptance evidence below. `iris/memory.py`: `session_id TEXT NOT NULL PRIMARY KEY` present in 90276fb. `_EMBEDDINGS_DDL_VEC` uses `float[{dim}]` (verified via `git show 90276fb -- iris/memory.py`). |
| 3 | Tests pass | ✅ PASS | 484 passed, 2 skipped, 3 xpassed on deployer branch. 79/79 memory-specific tests pass (`python -m pytest tests/test_memory.py`). Reviewer confirmed 81/81 memory tests at origin/main HEAD (including 2 regression tests added by 90276fb itself). |
| 4 | No high-severity findings open | ✅ PASS | Reviewer listed no HIGH findings. One informational note: pre-fix JSON rows in a vec0-enabled DB would fail struct.unpack on migration — not a blocker for clean deployments. |
| 5 | Final branch is clean | ✅ PASS | Post-merge acknowledgment; 90276fb is on origin/main. No uncommitted changes on deploy branch (only untracked .claude/.gc/.codex artifacts). |
| 6 | Branch diverges cleanly from main | ✅ PASS | 90276fb IS on origin/main; no conflicts. Deployer branch diverges but carries no regression against main. |
| 7 | Single feature theme | ✅ PASS | Schema hardening: session_id PRIMARY KEY guard + vec0 DDL type confirmation. Single subsystem (iris/memory.py). |

---

## Acceptance Criteria Evidence (from ti-mwd6 review + commit verification)

### ti-59wi — SESSIONS.session_id PRIMARY KEY (90276fb)
- ✅ `session_id TEXT NOT NULL PRIMARY KEY` added to SESSIONS DDL (git show 90276fb confirms `+    session_id TEXT NOT NULL PRIMARY KEY`)
- ✅ `test_sessions_primary_key_rejects_duplicate_session_id` added to tests/test_memory.py and passing on origin/main (reviewer confirmed 81/81)
- ✅ Prevents ghost rows from duplicate session_id inserts

### ti-k15u — vec0 float[N] DDL confirmation (90276fb)
- ✅ `_EMBEDDINGS_DDL_VEC` uses `float[{dim}]` (confirmed present in iris/memory.py line 70)
- ✅ `test_vec_ddl_uses_float_column_not_blob` added to tests/test_memory.py and passing on origin/main
- ✅ ANN index is active when sqlite-vec is loaded; plain BLOB fallback correctly distinct

### Reviewer checklist (ti-mwd6)
- ✅ enable_load_extension finally-guarded
- ✅ All SQL parameterized (no injection vectors)
- ✅ contact_id NOT NULL guards present
- ✅ Exception swallowing annotated intentional

---

## Test Results

```
python -m pytest tests/ -q  (deployer branch)
484 passed, 2 skipped, 3 xpassed, 2 warnings in 7.24s

python -m pytest tests/test_memory.py  (deployer branch)
79 passed in 2.81s

Reviewer (origin/main at 90276fb):
81/81 memory tests pass. Full suite 528 passed.
```

Note: deployer branch has 79 memory tests; origin/main has 81 (the 2 regression tests added by 90276fb are only on origin/main, not on the deployer feature branch). Both environments pass their complete test suites.

---

## Deploy Notes

90276fb was committed directly to origin/main by the factory before the deploy review cycle completed. This gate is an acknowledgment that the change was reviewed and passed, the tests pass, and the deploy bead can be closed. No PR was opened or needed.
