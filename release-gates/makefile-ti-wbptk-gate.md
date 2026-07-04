# Release Gate: makefile-ti-wbptk

**Bead:** ti-9bwv1 — needs-deploy: unified Makefile dev/ops entry point (from:ti-tbo2x)
**Source bead:** ti-wbptk — Implement the Makefile — unified dev/ops entry point (ti-62n8k/ti-dhe7g)
**Review bead:** ti-tbo2x — Review: unified Makefile dev/ops entry point (ti-wbptk) — CLOSED/PASS
**Reviewed commit:** 3e8658b on `feat/makefile-ti-wbptk`
**Branch:** feat/makefile-ti-wbptk → origin/main
**Date:** 2026-07-03

## Gate Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | ✅ PASS | ti-tbo2x notes: `REVIEW VERDICT: PASS` by tincan-iris/reviewer, "No blockers." |
| 2 | Acceptance criteria met | ✅ PASS | See below — independently re-verified, not just trusting review notes |
| 3 | Tests pass | ✅ PASS | `ruff check .` clean; `pytest -q` 1615 passed, 1 skipped, 3 xpassed (0 failed) on branch merged into current origin/main. See Test Run below for a flaky, unrelated, pre-existing failure encountered and ruled out. |
| 4 | No HIGH-severity findings | ✅ PASS | Reviewer: "No blockers. Passing to deploy." |
| 5 | Final branch clean | ✅ PASS | `git status` clean on `feat/makefile-ti-wbptk`; no uncommitted tracked changes |
| 6 | Branch diverges cleanly | ✅ PASS | `git merge-tree` + an actual scratch merge onto current `origin/main` (088b7da) produced zero conflicts |
| 7 | Single feature theme | ✅ PASS | One commit, 3 files (Makefile, README.md, AGENTS.md), one subsystem (dev/ops tooling) |

**Overall: PASS**

## Acceptance Criteria Verification (independently re-run, not just trusting builder/reviewer notes)

- `make` / `make help` (bare, clean checkout): re-ran in a scratch copy — lists
  exactly the 17 documented (`##`-commented) targets, alphabetically sorted,
  aliases `stt`/`tts`/`run` correctly hidden (ADR-2). Runs nothing else.
- `make verify` = `lint test` (Makefile:26), same order as `ci.yml`'s
  Lint-then-Run-tests steps.
- `make daemon` / `make daemon-callcard` idempotency: **not** independently
  re-verified here (requires a live daemon); builder/reviewer already tested
  this and surfaced a pre-existing, out-of-scope idempotency bug, correctly
  filed as ti-6w9pt rather than papering over it. Not a defect in this
  Makefile and not blocking.
- `make callcard`: re-ran in a scratch copy — prints
  `make callcard: not wired yet — see ti-913rw` to stderr, exits nonzero
  (`make: *** [Makefile:43: callcard] Error 1`), attempts nothing else.
- README.md "Running Iris" section now points at `make doctor` / `make up`;
  new "More" bullet links `AGENTS.md` as the canonical command map (FR18).
  `AGENTS.md` (new) documents all 17 targets + guardrails.
- `.github/workflows/ci.yml`: `git diff origin/main...HEAD -- .github/workflows/ci.yml`
  is empty — untouched, as required.
- `install`/`lint`/`test` recipes: `lint` (`ruff check .`) and `test`
  (`pytest -q`) are byte-identical to `ci.yml`'s steps. `install` is a
  superset of `ci.yml`'s install line (`.[console,call-card]` vs. `.[console]`)
  per the original ti-wbptk target list — this was already true of the spec
  before this bead and is unaffected by it (see Test Run note below for why
  it doesn't threaten NFR1 in practice).

## Test Run

`origin/main` advanced by one commit (088b7da, "AEC bridge on call + L1
capture core deps") after `feat/makefile-ti-wbptk` was branched — landed
between builder handoff and this gate run. That commit moves
`phonenumbers`/`dateparser` from the `call-card` extra into core
`dependencies`, which is why the two runs below differ.

**Run 1 — `feat/makefile-ti-wbptk` as branched (pre-088b7da pyproject.toml),
ci.yml's exact install (`pip install -e '.[console]' pytest ruff`):**
```
ERROR tests/test_capture_session_sourcing.py
ModuleNotFoundError: No module named 'dateparser'
```
Root-caused to a pre-existing gap on `origin/main` predating this bead
(`iris/capture/processor.py` has imported `dateparser`/`phonenumbers`
unconditionally since #129; `ci.yml` never installed the extra that carried
them). Not caused by, or fixable within, this Makefile bead — and moot,
because:

**Run 2 — `feat/makefile-ti-wbptk` merged into current `origin/main`
(088b7da included), same ci.yml-exact install:**
```
$ ruff check .
All checks passed!
$ pytest -q
1 failed, 1614 passed, 1 skipped, 3 xpassed in 71.85s
FAILED tests/test_daemon_api.py::test_dnd_off_ack - assert True is False
```
`test_dnd_off_ack` is a known flaky, order-dependent daemon-socket test,
already tracked at **ti-v6lc6** ("[flaky] test_daemon_api.py::test_dnd_off_ack
— intermittent under-load failure"), unrelated to this bead (this branch
touches no daemon/posture code). Confirmed flaky, not a regression:
- Isolated re-run (`pytest tests/test_daemon_api.py::test_dnd_off_ack`):
  passed 3/3.
- Full-suite re-run: `1615 passed, 1 skipped, 3 xpassed in 70.38s` — zero
  failures, matching the builder's and reviewer's own reported numbers
  exactly.
- GitHub Actions ran CI green on `origin/main`@088b7da itself minutes before
  this gate run (`gh run list`), confirming the merge target is healthy.

Conclusion: this bead introduces zero test regressions; the two anomalies
encountered both pre-exist on `main`, are already tracked separately
(ti-6w9pt, ti-v6lc6), and are correctly out of scope here.

## Commit

```
3e8658b feat(devops): add unified Makefile entry point (ti-wbptk)
 AGENTS.md | 54 +++++++++++++++++++++++++++++++++++++++++++++++
 Makefile  | 72 +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
 README.md | 13 +++++++-----
 3 files changed, 134 insertions(+), 5 deletions(-)
```

Pushed by the builder directly to `origin/feat/makefile-ti-wbptk`; branch cut
from `origin/main` at f863a84, one commit ahead.
