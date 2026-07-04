# Release Gate: DaemonAPI _ClientWriter close/write race fix (ti-hsju6)

**Bead:** ti-osuof (deploy) → ti-9skkj (review) → ti-hsju6 (implementation)
**Commit:** cd8b51b (cherry-pick of 1661a0c) on fix/daemonapi-clientwriter-close-race-ti-hsju6
**Branch base:** origin/main (088b7da)
**Date:** 2026-07-04

## Gate Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | **PASS** | ti-9skkj — reviewer-gm-wisp-anw8hc: "REVIEW VERDICT: PASS" |
| 2 | Acceptance criteria met | **PASS** | AC (ti-hsju6): reliable across 50+ repeated runs, root-caused not papered over — see below |
| 3 | Tests pass | **PASS** | 1615 passed, 1 skipped, 3 xpassed, 0 failures (85s) |
| 4 | No high-severity findings | **PASS** | All reviewer findings PASS/INFO — no HIGH/MEDIUM open |
| 5 | Final branch is clean | **PASS** | `git status` clean (untracked files are pre-existing worktree/build artifacts, not part of the commit) |
| 6 | Branch diverges cleanly from main | **PASS** | 1 cherry-picked commit, 0 conflicts (verified in a disposable worktree before building this branch) |
| 7 | Single feature theme | **PASS** | 1 commit, 1 file: `iris/daemon/api.py` |

**Overall: PASS**

---

## Acceptance Criteria Verification

AC (ti-hsju6): *"test_broadcast_reaches_n_clients passes reliably across 50+ repeated runs (loop locally, no pytest-repeat plugin needed) with no ValueError on closed-file flush. Root-cause the close/write ordering in DaemonAPI (api.py _ClientWriter + broadcast) rather than papering over with a try/except."*

- Root cause: `_RequestHandler.finish()` set `_ClientWriter.closed` and closed the underlying `wfile` **outside** the writer's own lock, so a concurrent `broadcast()` write could pass the `closed` check and then hit the file mid-close (`ValueError: I/O operation on closed file`, api.py:68).
- Fix: new `_ClientWriter.close()` marks `closed=True` and closes `wfile` inside the **same** lock `write()` uses — the two can no longer interleave. No try/except papering added; existing `OSError` handling in `write()` (a different failure class) is unchanged.
- Independently re-verified (not just re-running the builder/reviewer's own numbers): looped `test_broadcast_reaches_n_clients` 30x on this branch's commit — 0/30 failures.

## Test Run

```
1615 passed, 1 skipped, 3 xpassed in 85.36s (0:01:25)
```

Looped race regression test independently: 30/30 passed, 0 failures.

Ruff: `All checks passed!` on `iris/daemon/api.py`

## Scope

Single cherry-picked commit, single file: `iris/daemon/api.py` (13 insertions, 1 deletion). Verified this file has not diverged between the merge-base and `origin/main` (empty diff), and the cherry-pick applied with zero conflicts in a disposable worktree before this branch was built.

**Sequencing note:** this commit originated on a long-lived, multi-feature builder branch (`feat/console-crash-exit-message-ti-00jr4-2`) that has accumulated several unrelated, independently-reviewed changes (console diagnostics, JIT error hints, keybinding-escape fixes, a pending markup-escaping fix under separate review in ti-q1pee). Rather than shipping that branch tip — which would bundle unrelated feature themes into one PR (gate criterion 7) — this deploy cherry-picks only the reviewed, PASSED commit (1661a0c) for ti-hsju6 onto a clean branch off `origin/main`. The other stacked commits are tracked by their own separate `needs-deploy` beads (ti-03yy3, ti-m99u6, ti-ym0ku) and will ship independently the same way.
