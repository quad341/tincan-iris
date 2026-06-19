# Release Gate: pin-iris-arm-disarm (ti-2682)

**Branch:** `feature/ti-qxel-6qsb-sprint`  
**Commit:** `0727a5ddd6d0f30e5daa8124a81572977420e8a3`  
**Base:** `origin/main` @ `aae19b7dee0e39d071dec2338714703f19d3e8ad`  
**Gate evaluated:** 2026-06-19

## Result: PASS

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | **PASS** | `ti-c261` closed with "REVIEW VERDICT: PASS" — tincan-iris/reviewer (Claude Sonnet 4.6) |
| 2 | Acceptance criteria met | **PASS** | `_active_script()` replaces bare PATH lookup; 4/4 trust-grant CLI tests green |
| 3 | Tests pass | **PASS** | 633 passed, 3 skipped, 3 xpassed — zero failures (see below) |
| 4 | No high-severity findings open | **PASS** | Reviewer found one non-blocking minor note; no HIGH findings |
| 5 | Final branch is clean | **PASS** | Code tree clean; untracked `.beads/`, `docs/plans/`, `tincan_iris.egg-info/` are local tooling/artifacts, excluded from commit |
| 6 | Branch diverges cleanly from main | **PASS** | `git merge-tree` reports zero conflicts; `tests/test_trust_grant_cli.py` not touched on `origin/main` since fork point `0487065` |
| 7 | Single feature theme | **PASS** | One commit, one file (`tests/test_trust_grant_cli.py`), one subsystem (trust-grant CLI test infra) |

## Acceptance Criteria Verification

> `iris-arm` and `iris-disarm` subprocess calls in `test_trust_grant_cli.py` must resolve to the active Python environment's entry points, not a stale `~/.local/bin/` copy.

- [x] `_active_script(name)` helper defined at module level — checks `Path(sys.executable).parent / name` (venv + system pip), then POSIX user scheme (`sysconfig.get_path("scripts", "posix_user")`), then bare name fallback
- [x] `_IRIS_ARM = _active_script("iris-arm")` and `_IRIS_DISARM = _active_script("iris-disarm")` computed at import time, used in all 4 tests
- [x] `test_iris_arm_exits_nonzero_when_no_console` — PASS
- [x] `test_iris_disarm_exits_nonzero_when_no_console` — PASS
- [x] `test_iris_arm_ttl_flag_is_accepted` — PASS
- [x] `test_iris_arm_idempotent_when_already_armed` — PASS

## Test Run

```
$ cd /home/jaword/projects/tincan-iris-factory && python -m pytest tests/ -v
platform linux -- Python 3.14.5, pytest-9.0.3
rootdir: /home/jaword/projects/tincan-iris-factory
Branch: feature/ti-qxel-6qsb-sprint @ 0727a5d

633 passed, 3 skipped, 3 xpassed in 7.65s
```

No regressions against the test suite at this commit.

## Review Findings Summary

| Severity | Finding | Resolution |
|----------|---------|-----------|
| Minor (non-blocking) | `Path(sys.executable).parent / name` may miss scripts on system Pythons where pip installs to `/usr/local/bin` while `python3` is `/usr/bin`; POSIX user fallback + bare-name fallback cover this gap | Acknowledged; acceptable for test infra |

No HIGH findings open.

## Source bead

- Deploy bead: `ti-2682` — needs-deploy: fix(tests) pin iris-arm/iris-disarm to active Python env  
- Source bead: `ti-c261` — Review: fix(tests) pin iris-arm/iris-disarm to active Python env (closed, PASS)
