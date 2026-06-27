# Release Gate: callpipeline-fixes-f1-f4-ti-8conk

**Branch:** `fix/test-fixes-ti-gxpt1.3-et9i` (builder remote)  
**Reviewed commit:** `ecefab1` (fix(voice): call_pipeline review fixes F1–F4 (ti-n8g5y))  
**Bead:** ti-8conk  
**Source bead:** ti-4xpu6 (review: PASS by reviewer-gm-wisp-j0rkdqw)  
**Date:** 2026-06-27  
**Deployer:** deployer-gm-wisp-k5ajwf5 (tincan-iris/deployer)

---

## Criteria Evaluation

| # | Criterion | Result |
|---|-----------|--------|
| 1 | Review PASS present | **PASS** |
| 2 | Acceptance criteria met | **PASS** |
| 3 | Tests pass | not evaluated (gate failed at criterion 6) |
| 4 | No high-severity review findings open | **PASS** |
| 5 | Final branch is clean | not evaluated (gate failed at criterion 6) |
| 6 | Branch diverges cleanly from main | **FAIL** — 2 modify/delete conflicts |
| 7 | Single feature theme | **PASS** — call_pipeline only |

**Overall: FAIL**

---

## Evidence

### Criterion 1 — Review PASS

Review bead **ti-4xpu6** (closed, PASS by reviewer-gm-wisp-j0rkdqw):

> Review verdict: PASS  
> Commit ecefab1 reviewed. F1–F4 all confirmed fixed. Tests: 9/9 pass, ruff clean. No HIGH/CRITICAL findings.

### Criterion 2 — Acceptance Criteria

From ti-4xpu6:
- [x] F1: `runner.run(task)` replaces `__dict__` bypass; 6 test stubs updated to 2-arg
- [x] F2: `TTSStartedFrame → ('state', 'speaking')` added with new test
- [x] F3: pipecat logger suppressed per ADR-0007 FR-5
- [x] F4: `asyncio.set_event_loop(loop)` registered; cleared in finally

### Criterion 4 — No High-Severity Findings

From ti-4xpu6: No OWASP concerns, no HIGH or CRITICAL findings. All findings are CORRECTNESS/SPEC-COMPLIANCE items confirmed fixed in ecefab1.

### Criterion 6 — FAIL: Cherry-pick Conflicts

`ecefab1` cannot be cherry-picked onto `origin/main` (HEAD: `60454d3`):

```
CONFLICT (modify/delete): iris/voice/call_pipeline.py deleted in HEAD and modified in ecefab1
CONFLICT (modify/delete): tests/test_call_pipeline.py deleted in HEAD and modified in ecefab1
```

**Root cause:** `ecefab1` is a fix commit targeting files that don't exist on `origin/main`:
- `iris/voice/call_pipeline.py` — created by `14afb99` (CallPipeline scaffold, not yet on main)
- `tests/test_call_pipeline.py` — created by `0394525` (TDD stubs, not yet on main)

The CallPipeline feature itself hasn't landed on `origin/main` yet. `ecefab1` is a follow-up fix that depends on the original CallPipeline commits being present.

### Criterion 7 — Single Feature Theme

PASS. `ecefab1` touches only `iris/voice/call_pipeline.py` and `tests/test_call_pipeline.py` — pure call_pipeline scope.

---

## Recommended Builder Action

`ecefab1` is a clean, reviewed fix that cannot deploy independently because its prerequisites are not on `origin/main`.

**Blocked on:** The original CallPipeline commits (`14afb99` scaffold, `0394525` TDD stubs) must land on `origin/main` first. Those commits likely require their own review and deploy beads.

**Once CallPipeline lands on main**, the fix can be deployed as:

```bash
git checkout -b fix/callpipeline-fixes-f1-f4 origin/main
git cherry-pick ecefab1  # fix(voice): call_pipeline review fixes F1–F4 (ti-n8g5y)
# Verify 9/9 tests pass, then create a new deploy bead
```
