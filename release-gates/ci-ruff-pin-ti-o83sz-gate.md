# Release Gate: ci-ruff-pin-ti-o83sz

**Bead:** ti-o83sz — needs-deploy: CI: pin ruff to 0.15.22 (from:ti-0f4d0)
**Source bead:** ti-0f4d0 (review bead, CLOSED/PASS)
**Feature bead:** ti-7z1kj (implementation — CI unpinned-ruff root cause + fix)
**Branch:** `deploy/ti-0f4d0-gate`
**Gate commit:** (this commit)
**Date:** 2026-07-27

## Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | **PASS** | ti-0f4d0 closed (reason: pass); reviewer tincan-iris/reviewer recorded: "PASS: ruff pinned in ci.yml (==0.15.22) with rationale comment; regression test passes. No security/style issues." |
| 2 | Acceptance criteria met | **PASS** | ti-7z1kj's exit_contract (ruff pinned to a version confirmed clean against current main; inline WHY comment naming the chosen resolution path + follow-up bead; follow-up triage bead filed) verified directly against the diff: `.github/workflows/ci.yml` pins `ruff==0.15.22` with an inline comment naming ti-7z1kj (root cause) and ti-mi5wk (follow-up triage, already completed) |
| 3 | Tests pass | **PASS** | Independently re-run in a disposable worktree at the exact reviewed commit (not just re-reading builder/reviewer prose): `uvx ruff==0.15.22 check .` → "All checks passed!"; `pytest tests/test_ci_workflow_ruff_pin.py -q` → 2 passed. Consistent with builder's own recorded full-suite run (1904 passed [+2 new], 1 pre-existing environment-only failure unrelated to this change, 3 xpassed) |
| 4 | No high-severity findings open | **PASS** | Reviewer recorded no security/style issues; no HIGH-severity findings on either bead |
| 5 | Final branch is clean | **PASS** | `git status` clean on the isolated gate worktree checked out at the reviewed commit |
| 6 | Branch diverges cleanly from main | **PASS** | Reviewed commit `96a77af` is a linear 2-commit descendant of `origin/main` (TDD red `f6c9058` + green `96a77af`); `git log 96a77af..origin/main` → 0 commits (zero divergence, trivially fast-forwardable) |
| 7 | Single feature theme | **PASS** | Both commits implement one fix (pin ruff + guard comment in CI; a cosmetic loop-variable rename in the regression test to keep it self-lint-clean) touching only `.github/workflows/ci.yml` and `tests/test_ci_workflow_ruff_pin.py` — one subsystem (CI tooling). 9 insertions/2 deletions + 1 line changed |

## Verdict: PASS

## Commits on branch (vs origin/main)

| SHA | Message |
|-----|---------|
| `f6c9058` | test(ci): red — pin ruff version in CI + require pin rationale (refs ti-7z1kj) |
| `96a77af` | feat: green — pin ruff to 0.15.22 in CI, guard with rationale comment (refs ti-7z1kj) |

## Review summary (ti-0f4d0 / ti-7z1kj)

**Root cause:** ruff 0.16.0 (released 2026-07-23) enabled new default lint rules that flagged ~615 pre-existing sites repo-wide, breaking `ruff check .` in CI for every PR and every push to main with no corresponding code change on our side — discovered while investigating why PR #192 had been stuck red.
**Fix:** pin `ruff==0.15.22` (the last version confirmed clean against current main) with an inline comment stating why and which of 3 resolution paths was chosen (emergency stopgap, not a permanent decision), pointing at follow-up bead ti-mi5wk (already completed) for the long-term triage.
**Findings:** none — no security/style issues.
**Test coverage:** new regression test (`test_ci_workflow_ruff_pin.py`) guards the pin and rationale comment staying in place in `ci.yml`.

## OWASP / security surface

No externally-facing input handling changed; this is a CI tooling/config-only change.
