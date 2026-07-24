# Release Gate: tests/conftest.py store+log path isolation (ti-flg49)

**Date:** 2026-07-13
**Deploy bead:** ti-flg49
**Source bead:** ti-j773i (review) / ti-c4z98 (builder)
**Origin branch:** `fix/test-isolation-conftest-ti-c4z98` (commits `e003075` + `f682013`)
**Deploy branch:** `deploy-ti-flg49`, cut from `origin/main`, same content applied as `f393a44` + `28da924`

## Change summary

Adds one autouse fixture to `tests/conftest.py` (new file, 72 lines total)
that monkeypatches every on-disk `_DEFAULT_*` path constant (CallCardStore,
RosterStore, AfterStore, TranscriptStore, NotesStore, PreferencesStore,
daemon PostureManager, daemon singleton-lock `_PID_PATH`) plus the console's
`IRIS_LOG_FILE` env var to `tmp_path`-derived files. Test-only change, no
production source touched.

## Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | PASS | ti-j773i: 1st pass request-changes (console.log not isolated), builder fixed in `f682013`, 2nd pass REVIEWER VERDICT: PASS |
| 2 | Acceptance criteria met | PASS | Single new file `tests/conftest.py`; reviewer independently re-derived correctness of all 7 direct patches + 3 import-time aliases against source; confirmed via before/after control that the real console.log stops growing |
| 3 | Tests pass | PASS | `python3 -m pytest -q tests/` on `deploy-ti-flg49`: 1844 passed, 3 xpassed, 0 failed (104s). Count is 10 higher than the review's 1834 because `origin/main` gained tests from unrelated PRs (#170, #171, #173) merged since review — 0 failures either way |
| 4 | No high-severity review findings open | PASS | The single blocking finding (console.log leak) from pass 1 was fixed and confirmed resolved in pass 2; no new findings raised. One non-blocking `ruff format` nit noted explicitly as outside this repo's CI contract |
| 5 | Final branch is clean | PASS | `git status --porcelain=v1 --untracked-files=no` empty on `deploy-ti-flg49` |
| 6 | Branch diverges cleanly from main | PASS | `git merge-base --is-ancestor origin/main HEAD` true; branch is `origin/main` + 2 commits, no conflicts |
| 7 | Single feature theme | PASS | Both commits touch only `tests/conftest.py`; single theme (on-disk test isolation) |

## Additional verification (deployer, independent of reviewer)

- `git show --stat` on both commits confirms content matches exactly what
  ti-j773i's notes describe (64 + 8 lines, `tests/conftest.py` only).
- `ruff check tests/conftest.py`: clean.
- Warnings seen during the deployer's own full-suite run (background-thread
  `ValueError` in `_far_binding_watchdog`, PyGObject deprecation notices)
  match the exact pre-existing/unrelated warnings the reviewer already
  flagged as non-gating — `tests/conftest.py` does not touch those files.

## Conclusion

All 7 criteria PASS. Proceeding to push `deploy-ti-flg49` and open a PR;
merge-request routed to mayor per deployer guardrails (deployer never merges).
