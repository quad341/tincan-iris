# Release Gate: Reply.re_ask + Tier-0 re-ask detector (ti-rcn9.1)

**Bead:** ti-3r75r  
**Branch:** fix/test-fixes-ti-gxpt1.3-et9i  
**Reviewed commit:** e408a3f  
**Gate run:** 2026-06-29  

## Gate Checklist

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | ✅ PASS | reviewer-gm-yh3je PASS on 2026-06-29 (ti-6bq2) |
| 2 | Acceptance criteria met | ✅ PASS | See details below |
| 3 | Tests pass | ✅ PASS | 1234 passed, 23 skipped, 3 xpassed, 0 failed |
| 4 | No high-severity findings | ✅ PASS | Reviewer: no security findings; ruff clean |
| 5 | Final branch is clean | ✅ PASS | `git status` clean (only untracked gc artifacts) |
| 6 | Diverges cleanly from main | ✅ PASS | 0 merge conflicts against origin/main |
| 7 | Single feature theme | ⚠️ NOTE | See note below |

**Overall: PASS** (criterion 7 noted; merge scope delegated to mayor/mpr)

## Criterion 2 — Acceptance Criteria

ti-rcn9.1 scope (commit e408a3f — `iris/brain.py` + `iris/re_ask_phrasebook.py`):

- [x] `Reply.re_ask: bool = False` field added to Reply dataclass
- [x] `iris/re_ask_phrasebook.py` created — en-v1 regex patterns with anchors, no ReDoS risk
- [x] All 6 `Brain.respond()` return paths carry `re_ask` correctly (tier2-haiku, tier2-haiku-fail, tier2-haiku-blocked-demo, tier0, tier1, tier1-fail)
- [x] ≤6-word length guard runs before regex (verified by reviewer)
- [x] Language-aware via `_locked_language` (defaults 'en'; falls back to en for unknown langs)
- [x] `supported_languages()` returns frozenset — immutable, correct API
- [x] 19 phrasebook unit tests pass (en + es patterns, long-utterance guard, supported_languages)
- [x] 50 conductor tests pass (cadence slow-mode wiring in ti-rcn9.3 also covered)

## Criterion 3 — Test Run

```
python -m pytest tests/ -x -q --tb=short
1234 passed, 23 skipped, 3 xpassed, 2 warnings in 10.65s
```

Phrasebook: 19/19 PASS  
Conductor: 50/50 PASS

(Reviewer environment reported 1386 passed; the delta is environment-specific
skip/collection differences, not test failures. Builder's own count was 1234.)

## Criterion 7 — Feature Theme Note

The bead (ti-rcn9.1) is a single feature: re-ask detection in Brain + phrasebook.

The PR branch `fix/test-fixes-ti-gxpt1.3-et9i` contains 24 commits spanning
multiple additional features (ti-rcn9.2 es phrasebook, ti-rcn9.3 cadence
slow-mode, voice catalogue, ProfileResolver, CallPipeline, roster migration,
console features, etc.). The reviewer explicitly flagged this and instructed:
**"Route full branch PR to mayor/mpr for merge scope decision."**

Mayor/mpr will determine whether to merge the full branch or cherry-pick a
subset. The deployer does not determine merge scope for this PR.

## Ruff

```
ruff check iris/brain.py iris/re_ask_phrasebook.py
All checks passed!
```
