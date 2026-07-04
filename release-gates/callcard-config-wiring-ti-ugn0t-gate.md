# Release Gate: Wire real Config into CallCardHost at daemon startup

**Bead:** ti-ugn0t (source bug: ti-ajkht, review: ti-1a7wt — PASS)
**Branch:** deploy/callcard-config-wiring-ti-ugn0t @ a307713 (originally committed as
`tests/callcard-config-wiring-ti-sqv1v` on the validator remote; renamed for the
deploy branch only — commit content is unchanged)
**Base:** origin/main @ 088b7da — direct 2-commit ancestor (d015c18 fix + a307713
tests), clean linear fast-forward, no cherry-pick required.

## Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | PASS | ti-1a7wt notes: `REVIEW VERDICT: PASS` (tincan-iris/reviewer, 2026-07-04). Reviewed head-to-head against a duplicate implementation (ti-8mtt9, commit 32b72ce) and chosen for reusing the existing env>config.toml>default precedence machinery, which the duplicate lacked (no env-var override support). |
| 2 | Acceptance criteria met | PASS | Verified directly against the diff (`088b7da..a307713`), not just the bead notes: (a) `iris/daemon/__main__.py::main()` now calls `_load_call_card_config()` and passes `cfg=_load_call_card_config()` instead of `cfg=None`. (b) `CallCardHost._disclosure_script` reads the new flat `cfg.call_card_disclosure_script` field (falling back to `_DEFAULT_DISCLOSURE`) instead of the dead nested `cfg.call_card.disclosure_script` lookup — `test_main_passes_loaded_config_to_call_card_host` proves a real `config.toml` value reaches `CallCardHost` end-to-end via `main()`, not just a directly-constructed `Config()`. (c) `PostCallEnricher._cloud_enrichment_enabled` is legitimately out of scope: it does not exist on `origin/main` yet (ships unmerged on PR #139/ti-z9b84 — confirmed `git merge-base --is-ancestor b09dc88 origin/main` = false); this fix's real, non-None `Config` already makes that field resolve correctly once #139 merges, with zero further change needed. |
| 3 | Tests pass | PASS | Independently re-run in a disposable worktree + isolated venv at `a307713` (not just re-quoting bead/reviewer notes): `1623 passed, 1 skipped (tests/test_tincan_messages.py — missing system dbus module, environment-specific to the throwaway venv), 3 xpassed (pre-existing)`. Matches the reviewer's independently-reported numbers. The 8 new regression tests (`tests/test_daemon_call_card_config.py`, `tests/test_call_card_host.py`) individually re-verified passing. |
| 4 | No high-severity findings open | PASS | Review notes contain no HIGH findings; explicit "Security: no concerns" — fail-closed defaults preserved (4 tests cover `cfg=None` / missing attribute / empty string / non-empty value), the `anthropic_api_key` secret is deliberately kept env/secrets.toml-only and not made config.toml-configurable. |
| 5 | Final branch is clean | PASS | `git status` on the deploy branch is clean (aside from this gate-file commit itself). |
| 6 | Branch diverges cleanly from main | PASS | `git merge-base --is-ancestor 088b7da a307713` = true. `088b7da` (origin/main tip at gate time) is a direct 2-commit ancestor of `a307713` — clean linear fast-forward, zero conflict surface. |
| 7 | Single feature theme | PASS | All 7 touched files (`iris/config.py`, `iris/settings.py`, `iris/daemon/__main__.py`, `iris/daemon/call_card_host.py`, `config.toml.example`, plus 2 new test files) serve one theme: threading a real `Config` into `CallCardHost` at daemon startup. No unrelated changes bundled. |

## Verification detail

- `ruff check` clean on all 6 touched source/test files.
- Independently reproduced the pre-fix/post-fix discrimination the reviewer described: cherry-picking only the test commit onto pre-fix `088b7da` (skipping `d015c18`) fails as expected — the loader tests fail to import (`_load_call_card_config` doesn't exist pre-fix), the cfg-value tests fail with the old nested-lookup mismatch — confirming the new coverage is non-vacuous.
- A companion duplicate fix (ti-8mtt9, commit `32b72ce`, branch `fix/callcardhost-config-wiring-ti-ajkht`) was reviewed side-by-side and closed as superseded; nothing from that branch ships in this PR.
- This deploy worktree's own session branch (`gc-deployer-f3bd6e912272`) carried a stale, unrelated commit from a different bead (disclosure-card-ti-rnlqo-6-1) — the deploy branch above was cut directly from the verified candidate commit instead, not from that session branch.

## Gate verdict: PASS
