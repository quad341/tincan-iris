# Release Gate: BrainHost TurnLock fix (ti-1vcay)

**Date:** 2026-06-30
**Bead:** ti-1vcay (deploy) / source bead: ti-b8ttr / review: ti-03wyo (re-review)
**Source commit:** `eaa53ba2095df74c67d89bd1abfd0bb618ed0cad` (local feat/brainhost-ti-s9mm.1.1)
**Deploy branch:** `feat/brainhost-turnlock-fix-ti-1vcay` (single cherry-pick onto main)
**Reviewer:** reviewer-gm-gqam1 (PASS)
**Deployer:** tincan-iris/deployer

**Context:** BrainHost base feature (ti-s9mm.1.1) + DaemonAPI brain commands (ti-s9mm.2.1)
were already deployed to main via PR #114 (squash merge). This bead deploys ONLY the
TurnLock fix (`eaa53ba`) that addresses review advisory L1 from ti-03wyo — not the
original feature (already in main).

---

## Criteria Evaluation

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | **PASS** | reviewer-gm-gqam1: "All blockers from ti-03wyo resolved: M1 test added in 8af468b, L1 TurnLock fix in eaa53ba. 9/9 tests pass, ruff clean." |
| 2 | Acceptance criteria met | **PASS** | TurnLock fix verified in `iris/daemon/brain_host.py` — see below |
| 3 | Tests pass | **PASS** | 1403 passed, 32 skipped, 3 xpassed, 2 warnings — zero failures; 9/9 BrainHost tests pass |
| 4 | No high-severity review findings | **PASS** | "Security PASS (fully parameterized SQL, WAL mode, thread-safe DB ops)" — no HIGH/CRITICAL |
| 5 | Final branch is clean | **PASS** | `git status` clean — only untracked non-project overlays |
| 6 | Branch diverges cleanly from main | **PASS** | Single commit over main, auto-merge on cherry-pick, no conflicts |
| 7 | Single feature theme | **PASS** | One commit, one file (`iris/daemon/brain_host.py`), one fix: TurnLock release on thread start failure |

**Overall: PASS**

---

## Evidence

### Criterion 1 — Review PASS

Bead ti-1vcay notes (from reviewer-gm-gqam1):
> "Style PASS (ruff clean, follows conventions). Security PASS (fully parameterized SQL,
> WAL mode, thread-safe DB ops). Spec PASS (all acceptance criteria met). Coverage PASS
> — 9 tests in tests/test_brain_host.py covering TurnLock busy rejection, event ordering,
> call_context persistence, and restart-recovery. All blockers from ti-03wyo resolved:
> M1 test added in commit 8af468b, L1 TurnLock fix in eaa53ba. 9/9 tests pass, ruff clean."

Verdict: **PASS**

### Criterion 2 — Acceptance Criteria (TurnLock fix, ti-s9mm.1.1 advisory L1)

| AC | Description | Location | Status |
|----|-------------|----------|--------|
| AC1 | `Thread()` creation failure releases TurnLock and re-raises | `brain_host.py` try/except BaseException | ✅ |
| AC2 | `t.start()` failure releases TurnLock and re-raises | same try block | ✅ |
| AC3 | Uses `BaseException` (covers OOM, thread limit, not just `Exception`) | `except BaseException:` | ✅ |
| AC4 | On success, original behavior preserved (lock held, released in `_run` finally) | unchanged `_run` + `finally` | ✅ |
| AC5 | Fix is idempotent — does not double-release on happy path | lock only released in except branch | ✅ |

Fix diff (8 lines net):
```python
-        t = threading.Thread(target=_run, name="brain-turn", daemon=True)
-        t.start()
+        try:
+            t = threading.Thread(target=_run, name="brain-turn", daemon=True)
+            t.start()
+        except BaseException:
+            self._turn_lock.release()
+            raise
```

### Criterion 3 — Tests Pass

```
python -m pytest tests/ -q
1403 passed, 32 skipped, 3 xpassed, 2 warnings in 31.74s

python -m pytest tests/test_brain_host.py -v
9 passed in 0.09s
  ✓ test_turn_lock_busy_rejection
  ✓ test_turn_lock_busy_rejection_does_not_block_caller
  ✓ test_brain_turn_started_fires_before_lock_acquired
  ✓ test_brain_reply_fires_after_all_chunks
  ✓ test_brain_reply_text_accumulates_chunks
  ✓ test_set_call_context_persists_to_db
  ✓ test_clear_call_context_new_instance_starts_empty
  ✓ test_set_call_context_updates_brain_call_context
  ✓ test_clear_call_context_resets_brain_call_context
```

### Criterion 4 — No High-Severity Findings

No HIGH or CRITICAL findings. ruff clean on `iris/daemon/brain_host.py`.
The original security review passed (fully parameterized SQL, WAL mode, thread-safe DB ops).

### Criterion 5 — Branch Clean

```
On branch feat/brainhost-turnlock-fix-ti-1vcay
Untracked files: .gc/, .gitkeep, release-gates/ (deployer overlays)
nothing added to commit but untracked files present
```

### Criterion 6 — Clean Divergence from Main

Single cherry-pick of `eaa53ba` onto `origin/main`. One commit over main, no conflicts.
The BrainHost base feature was already in main via PR #114 (squash merge 2026-06-30).

### Criterion 7 — Single Feature Theme

One commit, one file, one fix. Theme: BrainHost TurnLock safety.
