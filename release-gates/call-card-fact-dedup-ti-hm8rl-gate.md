# Release Gate: call-card-fact-dedup-ti-hm8rl

**Bead:** ti-hm8rl — needs-deploy: Call Card fact dedup + confirmed-flag guard (from:ti-f34mq)
**Source bead:** ti-f34mq (review bead, CLOSED/PASS)
**Feature bead:** ti-3p688.1 (implementation — Call Card fact dedup + date cue-context)
**Branch:** `deploy-ti-hm8rl`
**Gate commit:** (this commit)
**Date:** 2026-07-13

## Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | **PASS** | ti-f34mq closed (pass) with reviewer VERDICT: PASS. Two rounds: initial REQUEST-CHANGES caught one blocking finding (`upsert_enriched_fact`'s UPDATE matched confirmed and unconfirmed rows alike, letting a post-call L3 re-extraction silently overwrite `raw_text` on an operator-confirmed row while `confirmed` stayed true, reaching `AfterStore` durable writeback under a human-verified flag never actually earned for that text); builder fixed it as commit `36b7a99` (WHERE clause now excludes confirmed rows); re-review independently verified the fix behaviorally in a disposable worktree — confirmed rows survive untouched, divergent later extractions land as new unconfirmed rows — plus checked for the fix moving the bug downstream (no UNIQUE constraint conflict, `confirm_fact` matches by primary key, `finalize_writeback`/`get_call_card` both handle multiple rows per (fact_type, normalized_value) correctly) |
| 2 | Acceptance criteria met | **PASS** | ti-3p688.1's scope (dedupe extracted facts by (fact_type, normalized_value) within a session; date facts carry cue-context) verified against the diff: `CallCardStore.upsert_enriched_fact()` (new, mirrors existing `upsert_enriched_action_item` pattern) is called from `PostCallEnricher._apply_result()` instead of unconditional `add_fact()`. Scope deliberately excludes L1's `add_fact()` path (session.py) — reviewer confirmed this is sound because `test_thread_safety_concurrent_add_facts` deliberately reuses one (fact_type, normalized_value) across 80 concurrent inserts and would break under a blanket dedup. Upsert-refresh (not skip-if-duplicate) confirmed correct for the cue-context requirement: L1's bare date-phrase capture is refreshed in place by L3's richer text rather than L1 winning permanently |
| 3 | Tests pass | **PASS** | 1843 passed, 3 xpassed, 1 failed (full suite, this branch, independently re-run). The 1 failure (`tests/test_daemon_call_card_config.py::test_main_passes_loaded_config_to_call_card_host`, "another instance holds the lock (pid 2353) — exiting") is the same pre-existing daemon PID-lock environmental flake already documented on numerous sibling gates in this rig (e.g. `console-markup-escape-ti-4sy3b-gate.md`) and independently confirmed by the reviewer to reproduce identically on unmodified `origin/main`. Numbers match exactly across builder's self-report, reviewer's first-pass, reviewer's re-review, and this independent gate run: 1843/3/1, zero regressions. `ruff check iris tests scripts`: all checks passed |
| 4 | No high-severity findings open | **PASS** | The one blocking finding (confirmed-flag overwrite) was resolved by `36b7a99` and independently re-verified PASS via behavioral testing, not just diff inspection. One pre-existing (not a regression from this diff) sibling gap was found and correctly filed separately as `ti-vfvcu` (`upsert_enriched_action_item` has the analogous confirmed-overwrite gap) — P3, open, non-blocking, tracked, does not gate this deploy |
| 5 | Final branch is clean | **PASS** | `git status --short` clean, no uncommitted changes |
| 6 | Branch diverges cleanly from main | **PASS** | Built directly on current `origin/main` tip (`3071105`); exactly 2 commits ahead, 0 behind (`git rev-list --left-right --count origin/main...HEAD` → `0 2`). No cherry-pick/rebase needed — commits were authored directly on this branch off a current tip |
| 7 | Single feature theme | **PASS** | Both commits implement one fix (Call Card L3 enrichment fact-dedup + confirmed-flag durable-writeback guard) touching only `iris/capture/store.py` and `iris/capture/enricher.py` — one subsystem (Call Card capture/enrichment layer). 54 insertions/11 deletions + 6 insertions total |

## Verdict: PASS

## Commits on branch (vs origin/main)

| SHA | Message |
|-----|---------|
| `3bb4da5` | fix(call-card): dedupe extracted facts + add date cue-context (ti-3p688.1) |
| `36b7a99` | fix(call-card): guard confirmed facts from L3 enrichment overwrite (ti-3p688.1) |

## Review summary (ti-f34mq)

**Correctness:** `upsert_enriched_fact` (store.py:234-272) mirrors the existing `upsert_enriched_action_item` shape (UPDATE-then-conditional-INSERT-under-lock-then-commit), docstring documents the one deliberate divergence (layer-agnostic match). `enricher.py`'s `CapturedFact` import removal confirmed safe (no remaining references).
**Findings:** one blocking finding (confirmed-flag overwrite on durable writeback path), fixed and re-verified PASS via independent behavioral script, not just re-reading the diff. No new issues introduced by the fix. One non-blocking sibling gap filed separately (`ti-vfvcu`, P3, pre-existing, not a regression).
**Test coverage:** no new tests committed with this fix — validator bead `ti-3p688.4` (open, unblocked, notes updated with the reviewer's requested case: "an already-confirmed fact is not silently overwritten by a later enrichment pass") tracks test authoring separately, consistent with this rig's established builder/validator split. Full suite independently re-run at both review passes and at gate time with identical results.

## OWASP / security surface

All queries use `?` placeholders with tuple-bound params; no injection surface. No externally-facing input handling changed by this diff.
