# Release Gate: Iris daemon exclusivity — unify pid/lock scope with flock (ti-qlbi0)

**Date:** 2026-07-03
**Deploy bead:** ti-fcack
**Source bead:** ti-2pbao (review), builds on ti-qlbi0 (architecture: ti-6w9pt)
**Branch:** `fix/iris-daemon-exclusivity-ti-qlbi0`
**Commit evaluated:** `1f4df12a2354a3793f391ce613f198e4d2867b85`

## Gate Result: PASS

## Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | PASS | ti-2pbao notes: "Review verdict (reviewer-gm-wisp-7uy7gf): PASS" |
| 2 | Acceptance criteria met | PASS | Independently spot-checked against the diff: `daemon_pid_path()` in `_socket_path.py` derives from `daemon_socket_path().with_name("daemon.pid")` (one resolver, replaces the old separate `Path.home()` constants); `__main__.py::main()` line 154 calls `_acquire_exclusive_lock(_PID_PATH)` as its literal first statement, before `RosterStore`/`TincanCallControl`/`Brain` construction; `api.py` status response includes `pid`. All 8 acceptance criteria from ti-qlbi0 were mapped line-by-line by the reviewer; re-spot-checked the two most safety-critical (resolver unification, lock-before-D-Bus ordering) directly against source here |
| 3 | Tests pass | PASS | Re-ran independently on `1f4df12` (not just trusting builder/reviewer reports): `ruff check .` — all checks passed; `pytest -q` (full suite, matches CI) — 1624 passed, 3 xpassed, 0 failed in 71.89s, exactly matching builder + reviewer reported counts; targeted run of `test_daemon_exclusivity.py` + `test_daemon_cli.py` + `test_daemon_api.py` — 45 passed |
| 4 | No high-severity findings | PASS | Reviewer recorded one LOW-severity/informational finding only (pre-existing shutdown-unlink race in `__main__.py:276`, unchanged by this diff, no double-subscription hazard in practice) — not a blocker |
| 5 | Final branch is clean | PASS | `git status` clean at `1f4df12` (only pre-existing untracked `.gc/` harness artifacts present in every worktree across this repo, unrelated to this diff) |
| 6 | Branch diverges cleanly from main | PASS | `origin/main` is a clean ancestor of `1f4df12` (1 commit ahead, 0 behind); branch was already present on `origin` at this commit (confirmed via dry-run push) |
| 7 | Single feature theme | PASS | All 7 changed files confined to `iris/daemon/` (pid/lock/socket exclusivity) plus its tests — one subsystem, one theme |

## Notes

- Builder cut this fix from a fresh branch off `origin/main` rather than the original assigned worktree branch, due to an unrelated rebase conflict on `iris/console/call_card.py`; documented in ti-qlbi0 notes and flagged to mayor separately at the time.
- One pre-existing, unrelated intermittent flake (`test_dnd_on_ack`) was reproduced independently by the reviewer on both the fix branch and baseline `origin/main` — confirmed out of scope and already tracked separately in open bead ti-7hwcu (DND ack/mutation TOCTOU race).
- This gate file's commit is the only addition on top of `1f4df12`; the fix itself is exactly the 7-file diff described above.
