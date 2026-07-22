# Release Gate: ASR hallucination gating (ti-86jub / ti-3p688.3)

**Date:** 2026-07-13
**Deploy bead:** ti-86jub
**Source beads:** ti-tf6z7 (review), ti-3p688.3 (implementation)
**Branch:** `deploy/asr-hallucination-gating-ti-86jub` (cut from `origin/main` at `3071105`, carrying commit `ff7dd8b` cherry-picked from its original shared branch)
**Commit evaluated:** `9ae7510`

## Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | PASS | ti-tf6z7 (reviewer tincan-iris/reviewer) closed PASS, independently verified in a disposable worktree — full correctness trace (audit-trail ordering, thread-safety, speaker→source mapping, console pipeline non-interference), not just a style pass |
| 2 | Acceptance criteria met | PASS | Whisper transcription hallucinations gated before fact/action-item extraction (`is_hallucinated_segment`), wired into `CaptureSession._on_utterance` after `TranscriptStore.append` (audit trail preserved) and before `processor.process()` (extraction suppressed) |
| 3 | Tests pass | PASS | `pytest -q tests/`: 1861 passed, 1 pre-existing unrelated failure, 3 xpassed, 0 skipped (see Discovery for the skip-count reconciliation) |
| 4 | No high-severity findings | PASS | No open high-severity findings; ruff clean on all touched/new files |
| 5 | Final branch is clean | PASS | Working tree clean at `9ae7510`; no uncommitted content |
| 6 | Branch diverges cleanly from main | PASS | Cut directly from current `origin/main` tip (`3071105`); cherry-pick applied with zero conflicts |
| 7 | Single feature theme | PASS | One cohesive theme: ASR hallucination gating (`asr_gate.py` + its `session.py`/`streaming.py`/`_whisper_stream.py` wiring) plus its own pinned tests. No unrelated content — see Discovery for why this single commit is safely severable from its original branch |

## Discovery

`ff7dd8b` originally lived on the shared branch `fix/call-card-action-item-dedup-ti-3p688-2`, sandwiched between two commits from an unrelated, not-yet-fully-approved sub-task (`10091a0`/`f32a11c`, ti-3p688.2 Call Card action-item dedup, still under re-review as ti-nv20g at gate time). The reviewer explicitly verified and documented that this is safe to sever: file sets are completely disjoint (`10091a0`/`f32a11c` touch only `iris/capture/enricher.py`/`store.py`; `ff7dd8b` touches only `iris/audio/_whisper_stream.py`, `iris/audio/streaming.py`, `iris/capture/asr_gate.py` (new), `iris/capture/session.py`, and its two new test files), and there is no functional dependency in either direction (grepped every file `ff7dd8b` touches for `enricher` references — none; the real-time capture path never calls into the enrichment stage inline).

Cherry-picked `ff7dd8b` alone onto a fresh branch cut from current `origin/main` (confirmed unchanged at `3071105` since the reviewer's writeup) rather than branching off the shared feature branch — applied with zero conflicts, matching the reviewer's file-disjointness analysis exactly (6 files: the 4 listed above plus 2 new test files).

Full suite: `pytest -q tests/` (top-level `tests/` explicitly, avoiding the sibling `ti-*-needs-deploy-*` nested worktree directories in this shared deployer worktree) → **1861 passed, 1 failed, 3 xpassed, 0 skipped**. The reviewer's own full-suite run (on the full shared branch, ff7dd8b + the excluded `10091a0`) reported 1860 passed + 1 skipped; re-ran with `-rs` here and confirmed 0 skips on this isolated cherry-pick — the counts fully reconcile (1860+1 = 1861+0) once `10091a0`'s absence is accounted for: without its enricher.py changes, one test that was conditionally skipped on the full branch simply runs (and passes) here instead. Not a regression, and expected precisely because `10091a0` was deliberately excluded from this deploy. The one failure, `tests/test_daemon_call_card_config.py::test_main_passes_loaded_config_to_call_card_host`, is the same pre-existing environmental daemon-PID-lock issue confirmed unrelated in every prior gate this session. `ruff check iris/ tests/ scripts/` clean.

`ti-qlh6y` (validator's follow-up test coverage for the `StreamingTranscriber` side-channel plumbing itself) is a separate, not-yet-integrated bead and was never a gating dependency for this review — sequencing its merge is independent of this deploy.

`f32a11c` (which landed on the shared branch after this bead's reviewed commit, addressing ti-3p688.2 REQUEST-CHANGES findings) is correctly excluded from this deploy — it is under separate, not-yet-passed re-review (ti-nv20g) and touches only `enricher.py`, disjoint from this bead's scope.

## Conclusion

Gate **PASS**. Opening PR against `main` carrying `ff7dd8b` only.
