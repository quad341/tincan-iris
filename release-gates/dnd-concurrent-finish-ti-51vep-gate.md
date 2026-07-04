# Release Gate: DND Concurrent-Finish Race Fix (ti-51vep Finding 1)

**Bead:** ti-fzjuv (needs-deploy)
**Source review bead:** ti-t7v5u
**Branch:** `fix/dnd-concurrent-finish-ti-51vep`
**Commits:** `54c4165` (ti-7hwcu ack/mutation TOCTOU split) + `f3a97ab` (ti-51vep Finding 1 fix, seq-based freshness check)
**Gate evaluated:** 2026-07-04

---

## Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | **PASS** | ti-t7v5u notes: `REVIEW VERDICT: pass`, close reason "pass" |
| 2 | Acceptance criteria met | **PASS** | See below |
| 3 | Tests pass | **PASS** | Full suite: 1620 passed, 1 skipped, 3 xpassed. Regression sweep (7 files incl. test_posture.py): 107/107 pass. test_posture.py alone repeated 5x: 5/5 clean every run. |
| 4 | No high-severity findings open | **PASS** | Finding 1 (HIGH) is what this commit fixes. One residual LOW finding filed separately as ti-fyf2t (P3/backlog, non-blocking) — 0 unresolved HIGH |
| 5 | Final branch is clean | **PASS** | `git status` on branch tip shows no modifications (only pre-existing worktree-level untracked cruft: `.gc/`, `.gitkeep`, `tincan_iris.egg-info/`) |
| 6 | Branch diverges cleanly from main | **PASS** | `git merge-tree` of branch tip vs `origin/main` merges clean, no conflict markers |
| 7 | Single feature theme | **PASS** | 2 commits, 3 files (`iris/daemon/posture.py`, `iris/daemon/api.py`, `tests/test_posture.py`), all one subsystem: PostureManager DND state race. `f3a97ab` stacks directly on `54c4165` fixing a race the first commit's own review surfaced — same theme, not independent. |

**Overall gate: PASS**

---

## Acceptance Criteria

**Base (ti-7hwcu, commit `54c4165`, previously reviewed+passed once, re-confirmed here):**
- [x] `PostureManager.set_dnd`/`clear_dnd` split into a state-only mutator (`_set_dnd_state`/`_clear_dnd_state`, lock-protected, no I/O) plus `_finish_dnd_change(snapshot)` (persist+broadcast) — verified directly in diff.
- [x] `DaemonAPI._handle_dnd` (on/off/until): mutates state first, writes ack second, finishes (persist+broadcast) third — verified in `iris/daemon/api.py` diff.
- [x] No behavior change for `PostureWatcher`/`toggle_dnd`/other callers — public `set_dnd`/`clear_dnd` still call both steps immediately.
- [x] `test_dnd_ack_arrives_before_posture_event` unmodified and passing (part of the 107/107 sweep).

**Finding 1 fix (ti-51vep, commit `f3a97ab`):**
- [x] `_State` gained a monotonic `seq: int` field.
- [x] `_set_dnd_state`/`_clear_dnd_state` increment `seq` under the existing lock on every mutation.
- [x] `_finish_dnd_change` re-acquires the lock, no-ops if `snapshot.seq < self._state.seq` (a newer mutation has already superseded it), before running persist/broadcast — verified directly at `iris/daemon/posture.py:177-192`.
- [x] New regression coverage: `tests/test_posture.py` exercises the 2-actor race (delayed finish vs. a completed concurrent mutate+finish, including `PostureWatcher` as the concurrent actor by name) with deterministic `threading.Event` ordering, not sleep-based timing.

---

## Test Results

```
.deploy-gate-venv/bin/pytest -q   (full suite, on origin/fix/dnd-concurrent-finish-ti-51vep @ f3a97ab)
1620 passed, 1 skipped, 3 xpassed in 79.39s

.deploy-gate-venv/bin/pytest tests/test_daemon_api.py tests/test_daemon_api_brain.py \
  tests/test_daemon_cli.py tests/test_incoming_call_panel.py tests/test_roster_migration.py \
  tests/test_daemon_api_cc.py tests/test_posture.py -q
107 passed in 14.14s

tests/test_posture.py -q, repeated 5x: 5 passed each run, no flakes.

ruff check iris/daemon/posture.py iris/daemon/api.py tests/test_posture.py
All checks passed!
```

Isolated throwaway venv (`.deploy-gate-venv`, not the shared global environment) per this rig's verification convention; confirmed `import iris` resolves to this worktree before trusting results.

---

## Review Finding (non-blocking)

**[LOW] residual, filed as ti-fyf2t (P3/backlog)** — the freshness check in `_finish_dnd_change` and the actual `_persist`/`_broadcast` I/O are not atomic with each other (lock released between them). A narrower 3-actor race could in principle still let a checked-but-delayed finisher write stale state last. Requires 3-way concurrent DND mutation (this system normally has at most `PostureWatcher` + one interactive client) and a raw scheduler-preemption-scale window, not a real I/O-delay-scale window like the bug this commit fixes. Independently identified twice (reviewer + a concurrent builder session), which is why it was filed as a tracked follow-up rather than dropped — does not block this deploy per this rig's coverage policy for races that can't be deterministically exercised at the demonstrated-bug tier.

---

## Branch Composition

| Commit | Description |
|--------|-------------|
| `54c4165` | fix(daemon): close DND ack/mutation TOCTOU race (ti-7hwcu) |
| `f3a97ab` | fix(daemon): close concurrent DND finish race (ti-51vep Finding 1) |
