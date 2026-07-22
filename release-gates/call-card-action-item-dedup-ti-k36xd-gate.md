# Release Gate: Call Card action-item dedup (ti-k36xd / ti-3p688.2)

**Date:** 2026-07-13
**Deploy bead:** ti-k36xd
**Source beads:** ti-nv20g (review), ti-3p688.2 (implementation)
**Branch:** `deploy/call-card-action-item-dedup-ti-k36xd` (cut from `origin/main` at `3071105`, carrying commits `10091a0` + `f32a11c` cherry-picked from their original shared branch)
**Commit evaluated:** `46da0f2`

## Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | PASS | ti-nv20g (reviewer tincan-iris/reviewer) closed PASS after an initial REQUEST-CHANGES round and re-review of the fix-up commit |
| 2 | Acceptance criteria met | PASS | Rephrased/duplicate action items consolidated during L3 enrichment; enrichment LLM prompt now supplies turn IDs + existing action items so the model has the signal needed to dedupe |
| 3 | Tests pass | PASS | `pytest -q tests/`: 1843 passed, 1 pre-existing unrelated failure, 3 xpassed — matches reviewer's own reported numbers exactly |
| 4 | No high-severity findings | PASS | No open high-severity findings; ruff clean on both touched files; SQL fully parameterized; no new external input sink or threading hazard |
| 5 | Final branch is clean | PASS | Working tree clean at `46da0f2`; no uncommitted content |
| 6 | Branch diverges cleanly from main | PASS | Cut directly from current `origin/main` tip (`3071105`); cherry-picks applied with zero conflicts |
| 7 | Single feature theme | PASS | One cohesive theme: L3 enrichment action-item dedup (`enricher.py` + `store.py`). No unrelated content — see Discovery for why these two commits are safely severable from their original branch |

## Discovery

`10091a0` and `f32a11c` originally lived on the shared branch `fix/call-card-action-item-dedup-ti-3p688-2`, with an unrelated commit from a different sub-task (`ff7dd8b`, ti-3p688.3) sandwiched between them. `ff7dd8b` was already reviewed, passed, and shipped separately via ti-86jub (PR #179) earlier this session. The reviewer verified this pair is safe to sever from `ff7dd8b`: file sets are completely disjoint (`10091a0`/`f32a11c` touch only `iris/capture/enricher.py` and `iris/capture/store.py`; `ff7dd8b` touches only the audio-streaming/ASR-gate files and its own tests), and grepping every file `ff7dd8b` touches for `enricher` references turned up none — the real-time capture path never calls into the enrichment stage inline.

Cherry-picked `10091a0` then `f32a11c` (in that order) onto a fresh branch cut from current `origin/main` (confirmed unchanged at `3071105` since the reviewer's writeup) — applied with zero conflicts, independently confirming the reviewer's disjointness analysis. Diff scope: `iris/capture/enricher.py` (66 lines) + `iris/capture/store.py` (16 lines), matching the bead description exactly.

Full suite: `pytest -q tests/` (top-level `tests/` explicitly, avoiding the sibling `ti-*-needs-deploy-*` nested worktree directories in this shared deployer worktree) → **1843 passed, 1 failed, 3 xpassed**, matching the reviewer's own full-suite numbers exactly. The one failure, `tests/test_daemon_call_card_config.py::test_main_passes_loaded_config_to_call_card_host`, is the same pre-existing environmental daemon-PID-lock issue (tracked as ti-8wtzr) confirmed unrelated in every prior gate this session. `ruff check iris/ tests/ scripts/` clean.

Known non-blocking follow-up (not part of this gate): a pinned test for this scenario in ti-3p688.4 needs a one-line fixture update (`transcript_turn_id=40` → `transcript_turn_ids=[40]`) before it can run against this schema — already flagged directly on that bead, does not affect the correctness of what's shipping here. Finding 3 from review (turn-scoped delete has no content filter) was filed as non-blocking follow-up ti-u4e0i (P3), independent of this deploy.

`ff7dd8b` is correctly excluded from this deploy — already shipped separately via ti-86jub (PR #179), not double-shipped here.

## Conclusion

Gate **PASS**. Opening PR against `main` carrying `10091a0` + `f32a11c` only.
