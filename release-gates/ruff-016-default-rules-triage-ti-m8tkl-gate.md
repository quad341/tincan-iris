# Release Gate: Triage ruff 0.16.0's new default rules (ti-m8tkl)

**Date:** 2026-07-28
**Deploy bead:** ti-m8tkl
**Source bead:** ti-6w7c6 (Review: Triage ruff 0.16.0's new default rules — 615 sites — fix-and-unpin or adopt deliberately)
**Branch (provenance only, not push target):** `builder/ti-mi5wk`
**Commit evaluated:** `d7405d37626698784e6180f357c8990801110638`

## Gate Result: PASS

## Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 6 | Branch diverges cleanly from main | PASS | `git merge-base --is-ancestor origin/main d7405d3` confirms current `origin/main` (`9170576`) is a clean ancestor of the deploy tip — the branch is main plus additive commits only, no divergent content |
| 1 | Review PASS present | PASS | ti-6w7c6 closed with VERDICT: PASS (style/security/spec findings all green) |
| 2 | Acceptance criteria met | PASS | `tests/test_ruff_ci_policy.py::test_ci_yaml_declares_ruff_policy` + `::test_declared_ruff_invocation_passes_clean` re-run in isolation on the evaluated commit — 2/2 pass |
| 3 | Tests pass (documented CI-equivalent command) | PASS | Clean disposable worktree + isolated venv: `pip install -e '.[console,call-card]' pytest ruff`, then `ruff check .` → All checks passed (both ruff 0.16.0 pinned and latest); `pytest -q` → 1914 passed, 1 failed, 1 skipped, 3 xpassed (see Test Evidence Detail) |
| 4 | No open HIGH findings | PASS | Review's `security_findings: none found`; no HIGH-severity findings anywhere in the review notes |
| 5 | Final branch is clean | PASS | Deploy branch cut directly from `d7405d3` with no additional commits; working tree clean |
| 7 | Single feature theme | PASS | 145 files changed, all mechanical ruff-0.16.0 triage (unused-import/blank-line fixes, centralized ignore-code policy in `pyproject.toml`, deleted superseded `test_ci_workflow_ruff_pin.py`, added `test_ruff_ci_policy.py`), plus one small in-theme fix (2× UP017 + 1× PLW1510 in `scripts/ci_driftwatch.py` — code that landed via an unrelated bead after this triage began, folded in because it's newly-introduced ruff-0.16.0 debt within the same theme) |

## Test Evidence Detail

Independently re-verified in a clean disposable git worktree — not the shared deployer working directory, which carries ~40 unrelated leftover scratch subdirectories from prior unrelated work that would otherwise pollute `ruff check .` / `pytest`'s file discovery — and an isolated venv, to avoid repointing the shared editable `tincan-iris` install (which currently points at the builder's own worktree) at a disposable location.

- `uvx ruff@0.16.0 check .` → All checks passed!
- `uvx ruff@latest` (currently resolves to 0.16.0 too) → All checks passed!
- `pytest -q`: 1914 passed, 1 failed, 1 skipped, 3 xpassed in ~90s
  - FAIL: `tests/test_daemon_call_card_config.py::test_main_passes_loaded_config_to_call_card_host` — pre-existing environmental flake, a PID-lock collision with a live daemon process (pid 2276) on this shared box. Documented non-regression; reproduced with the identical signature across multiple independent sessions on this exact bead and against clean main.
  - SKIP: `tests/test_tincan_messages.py:221` — `pytest.importorskip("dbus")`; this clean venv has no system `dbus` Python bindings available. Confirmed `.github/workflows/ci.yml` has no apt/system-package provisioning step, so actual GitHub Actions CI (fresh `ubuntu-latest` + `actions/setup-python@v5`) would skip this identically — not a gap introduced by this evaluation.
  - The builder's own last self-reported count (1915 passed, 0 skipped) reflects the shared local dev environment, which happens to already have system dbus bindings installed. The 1-test delta is fully explained by that environment difference and does not change the gate outcome.

## Conclusion

All 7 criteria PASS on independent re-verification of commit `d7405d37626698784e6180f357c8990801110638`. Cutting deploy branch `deploy/ti-m8tkl-gate` from this commit and opening a PR.
