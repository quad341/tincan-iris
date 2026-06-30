# Release Gate: TincanCallControl wiring to BrainHost (ti-e42v8)

**Date:** 2026-06-30
**Deploy bead:** ti-e42v8
**Source bead:** ti-yb1wl (Review: Move TincanCallControl to daemon startup, wire to BrainHost ti-s9mm.4.1)
**Branch:** `feat/tcc-wiring-ti-e42v8` (cherry-pick of `55c5280` onto `origin/main`)
**Commit evaluated:** `78f14c9` (cherry-pick) / source `55c5280`

## Gate Result: PASS

## Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | PASS | ti-yb1wl closed with `REVIEW VERDICT: PASS` by reviewer gm-950xt (2026-06-30) |
| 2 | Acceptance criteria met | PASS | `_StubCtrl` removed; `TincanCallControl`, `Brain`, `BrainHost` wired; `_on_tcc_event` routes incoming_call/call_connected/call_ended; D-Bus absent emits WARNING with `dbus_absent=True` |
| 3 | Tests pass | PASS | 1403 passed, 32 skipped, 3 xpassed; ruff: all checks passed |
| 4 | No high-severity findings | PASS | Reviewer found only INFO finding: `resolver.resolve()` on D-Bus thread is a pre-existing design constraint, not introduced here |
| 5 | Final branch is clean | PASS | `git status` shows no uncommitted tracked-file changes; one commit ahead of `origin/main` |
| 6 | Branch diverges cleanly from main | PASS | Cherry-pick of `55c5280` applied with zero conflicts; diff is exactly `iris/daemon/__main__.py` (+57/-10) |
| 7 | Single feature theme | PASS | Single-file change to `iris/daemon/__main__.py`; replaces stub with real TCC wiring — one subsystem, one theme |

## Notes

- Source branch `feat/brainhost-ti-s9mm.1.1` (builder) has additional commits (`a656739` iris-brain.service.tmpl fix, ti-s9mm.5.1) stacked after `55c5280`. Those are NOT part of this deploy — they belong to a separate bead/review. A clean cherry-pick branch was cut from `origin/main` to isolate exactly the TCC wiring.
- All prerequisite modules (`BrainHost`, `Brain`, `TincanCallControl`, `DaemonAPI`, `HandlingEngine`) were already merged to `origin/main` via PR #114 and PR #118.
- Test count (1403) matches the reviewer's reported count exactly.
