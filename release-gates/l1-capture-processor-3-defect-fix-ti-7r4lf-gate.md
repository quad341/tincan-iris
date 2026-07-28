# Release Gate — L1CaptureProcessor 3-defect fix (ti-7r4lf)

- **Deploy bead:** ti-7r4lf
- **Source bug bead:** ti-rnlqo.2.5 (L1CaptureProcessor: 3 defects vs. design doc, found in full-suite validation)
- **Molecule:** ti-0z08r (mol-tdd-build), branch `builder/ti-0z08r` (provenance only, not a push target)
- **Reviewed commit (deploy source SHA):** `fe7e44d9d4c5c1df8758aa5be32ccec11fdd4db8` ("feat: green — mol-tdd-build (refs ti-0z08r)")
- **TDD red commit:** `562a2c6857d1a1576c528ea5d1d9bf72f3e01bd7`
- **Deploy branch:** `deploy/ti-7r4lf-gate`, cut directly at the reviewed SHA above

## Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | PASS | Independent reviewer verdict (reviewer-gm-ql27e, 2026-07-28) recorded in ti-rnlqo.2.5 notes: all 3 defects verified fixed against `docs/designs/call-card-fact-catalog.md`, diff scope confirmed, tests read in full and unweakened. |
| 2 | Acceptance criteria met | PASS | Independently re-diffed `1a8ad04..fe7e44d9d4` (merge-base of the deploy SHA vs `origin/main`) and read the resulting patch directly (not just bead prose): (a) both amount-normalization sites drop the `$` prefix, (b) `_PHONE_SCAN_RE` gains `()` to its character class + strip regex, (c) `ActionItem` gains `fact_type: FactType = FactType.ACTION_ITEM` and `FactType` gains `ACTION_ITEM`. Matches the exit_contract exactly. |
| 3 | Tests pass | PASS | `pytest -q tests/` on `deploy/ti-7r4lf-gate`: **1943 passed, 1 xfailed, 4 xpassed, 1 failed** in 107.45s. The 1 failure is `tests/test_daemon_call_card_config.py::test_main_passes_loaded_config_to_call_card_host`, a known environment-only false failure — captured log shows `another instance holds the lock (pid 2276) — exiting`, i.e. a stray already-running `iris.daemon` process on this shared box holding the singleton lock, unrelated to this diff (`session.py`/daemon lock code is untouched by these 5 files). This is now independently reproduced a 3rd time (bug-bead run: pid 3106; reviewer run: different pid; this run: pid 2276) — consistently environmental, not a regression. `tests/capture/` alone: 41 passed, 1 xfailed (pre-existing KNOWN-HARD case, unrelated), 1 xpassed. |
| 4 | No high-severity review findings open | PASS | `bd search "rnlqo.2.5"` returns only this deploy bead; no separate open Review: bead with unresolved findings. |
| 5 | Final branch is clean | PASS | `git status --short --untracked-files=no` empty prior to committing this gate file. |
| 6 | Branch diverges cleanly from main | PASS | `git merge-base fe7e44d9d4... origin/main` = `1a8ad04` (one commit behind current `origin/main` tip `95d0166`, an unrelated CI-only ruff-pin commit). `git merge-tree --write-tree origin/main fe7e44d9d4...` completed with exit 0 and no conflict markers — clean auto-merge. |
| 7 | Single feature theme | PASS | All 3 fixes are within one subsystem (`iris/capture/processor.py` + `iris/capture/schemas.py`, the L1 deterministic-extractor layer) and one source bead; not independent features. |

## Verdict: **PASS**

Deploy branch `deploy/ti-7r4lf-gate` pushed to `origin`, PR opened against `main`. Merge authority is mayor/mpr — this deployer does not merge.
