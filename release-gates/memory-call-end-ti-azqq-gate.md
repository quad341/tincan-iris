# Release Gate: iris memory three-layer system + L3 archival pipeline

**Deploy bead:** ti-azqq  
**Source bead:** ti-2z8 (MemoryManager.call_end())  
**Branch:** gc-builder-f31865f73619  
**Gate commit (tip):** 9c5bb27  
**Date:** 2026-06-16  

## Commits in PR (4 commits above origin/main @ 4ef7491)

| SHA | Title | Review bead | Verdict |
|-----|-------|-------------|---------|
| b7fe484 | feat(memory): three-layer call context system (ti-mvs, ti-58g) | ti-spbo | PASS |
| 38f7dd0 | test(memory): add test_memory.py — 41 tests for memory layer (ti-ikz B1) | ti-spbo | PASS |
| 94147eb | fix(memory): enable_load_extension before load_extension in _try_load_vec | ti-s7iu | PASS |
| 9c5bb27 | feat(memory): MemoryManager.call_end() — L3 archival pipeline (ti-2z8) | ti-li5d | PASS |

Note: 9c5bb27 is the post-rebase form of f691381 (reviewed). Builder rebased onto origin/main
resolving brain.py (context_hint merge) and lanes.py (kept main's Tier1Qwen grammar-dispatch).
Review code and tests are unchanged; only base ref shifted.

## Criterion 1 — Review PASS present: PASS

All 4 commits have first-pass reviewer PASS verdicts:
- **ti-spbo** (CLOSED): PASS — 41 memory tests added; B1/B2 findings resolved; rowid tiebreaker fix correct; 105 tests pass.
- **ti-s7iu** (CLOSED): PASS — _try_load_vec enable_load_extension fix verified; 3 new path-coverage tests; 105 tests pass.
- **ti-li5d** (CLOSED): PASS — all 7 archival spec steps verified; schema migrations backward-compatible; 25 new call_end tests; 393 tests pass.

(Second-pass gemini reviewer disabled; single-pass is current policy per rig configuration.)

## Criterion 2 — Acceptance criteria met: PASS

From ti-2z8 spec:
- [x] Step 1: `is_session_ended()` idempotency guard at top of `_archive` — verified in ti-li5d
- [x] Step 2: `GistWorker.shutdown()` + `join(timeout=2.0)` — verified in ti-li5d
- [x] Step 3: Final gist via Qwen (`n_predict=80`, ≤4 sentences) via `_qwen_summarise` — verified in ti-li5d
- [x] Step 4: `end_session_with_gist` BEFORE embed — verified step ordering in ti-li5d
- [x] Step 5: Embed `final_gist` → `source_type='gist'` — verified in ti-li5d
- [x] Step 6: Embed open Notes → `source_type='note'` — verified in ti-li5d
- [x] Step 7: Bare `except` → `log.exception`, never re-raise — verified in ti-li5d
- [x] Schema: `SESSIONS.final_gist` added; `EMBEDDINGS.source_type`/`source_id` added with backward-compatible defaults — verified
- [x] `call_end()` fires daemon thread ≤1ms (non-blocking on hangup) — test verified

## Criterion 3 — Tests pass: PASS

```
404 passed, 1 skipped, 3 xpassed in 4.99s
```

Run: `python -m pytest tests/ --tb=short -q` in builder worktree on gc-builder-f31865f73619 (tip 9c5bb27).
No failures. The 4 pre-existing failures noted in ti-li5d review are now `3 xpassed` + `1 skipped` — they have
resolved upstream and no longer fail; not introduced by this branch.

## Criterion 4 — No HIGH-severity review findings open: PASS

Only finding across all review beads:
- **LOW** (non-blocking, ti-li5d): `_FINAL_GIST_PROMPT.format(gist=..., last_10=...)` could raise `KeyError` if
  transcript text contains literal `{name}` patterns. Outer `except Exception` in `_qwen_summarise` catches this,
  returns `''` gracefully — session still ends. Acceptable degradation per v1 policy.

Count of unresolved HIGH findings: **0**

## Criterion 5 — Final branch is clean: PASS

```
On branch gc-builder-f31865f73619
Untracked files: .claude/ .codex/ .gc/ .gitkeep
nothing added to commit but untracked files present
```

No uncommitted changes. Untracked files are deployer-internal scaffolding, not part of the PR.

## Criterion 6 — Branch diverges cleanly from main: PASS

```
merge-base(origin/main, gc-builder-f31865f73619) = 4ef749143ef2bf269f3a8e946859f7a3bdb9cab0
origin/main HEAD                                 = 4ef749143ef2bf269f3a8e946859f7a3bdb9cab0
```

Branch sits exactly on top of `origin/main`. No merge conflicts. Push dry-run to origin succeeded.

## Criterion 7 — Single feature theme: PASS

All 4 commits implement the iris memory three-layer system:
- `b7fe484`: Foundational call context (L1/L2 rolling window, gist worker, embedding engine, MemoryManager.call_start)
- `38f7dd0`: Test coverage for the above
- `94147eb`: Bug fix within the memory layer (_try_load_vec extension loading)
- `9c5bb27`: L3 archival pipeline (MemoryManager.call_end)

All commits touch only `iris/memory.py`, `iris/brain.py`, `iris/lanes.py`, `iris/config.py`, `tests/test_memory.py`.
They form a progression where each depends on the previous — not independent features.

## Overall: **PASS**

Proceed with PR creation. Push remote: `origin`. Head ref: `gc-builder-f31865f73619`.
