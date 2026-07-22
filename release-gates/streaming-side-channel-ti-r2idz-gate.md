# Release Gate: StreamingTranscriber confidence side-channel tests (ti-r2idz / ti-qlh6y)

**Date:** 2026-07-14
**Deploy bead:** ti-r2idz
**Source beads:** ti-qlh6y (implementation of tests), ti-3p688.7 (review)
**Branch:** `tests/streaming-side-channel-ti-qlh6y` (built directly on top of `deploy/asr-hallucination-gating-ti-86jub` at `3c352a3` — see Discovery)
**Commit evaluated:** `ba29ee8`
**PR base:** `deploy/asr-hallucination-gating-ti-86jub` (PR #179), **not** `main` — this is a stacked PR (see Discovery)

## Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | PASS | Reviewed + PASSED by tincan-iris/reviewer (ti-3p688.7 notes); independently re-verified below rather than trusted at face value |
| 2 | Acceptance criteria met | PASS | `tests/test_streaming.py` (+64/-0) covers `StreamingTranscriber.last_no_speech_prob`/`last_avg_logprob` side-channel: set-before-`on_text`, per-utterance updates, default-to-`None` when absent, reset-to-`None` after an utterance without confidence fields |
| 3 | Tests pass | PASS | Targeted: `pytest tests/test_streaming.py` → 10/10. Combined targeted (`test_streaming` + `test_capture_hallucination_gating` + `test_asr_gate`) → 28/28. Full suite: `pytest -q tests/` → 1865 passed, 1 pre-existing unrelated failure, 3 xpassed (see Discovery) |
| 4 | No high-severity findings | PASS | None open in ti-3p688.7 or ti-qlh6y notes; `ruff check tests/test_streaming.py iris/audio/streaming.py` clean |
| 5 | Final branch is clean | PASS | Working tree clean at `ba29ee8`; no uncommitted content |
| 6 | Branch diverges cleanly from main | PASS (via stack base) | `ba29ee8` is a direct 1-commit descendant of `deploy/asr-hallucination-gating-ti-86jub`'s tip (`3c352a3`) — trivially zero divergence from its actual PR base. That base branch is itself `MERGEABLE`/CI-green against `origin/main` per `gh pr view 179` (unmerged as of this gate) |
| 7 | Single feature theme | PASS | Single-file, test-only diff (`tests/test_streaming.py`, +64/-0). One theme: confidence side-channel plumbing tests |

## Discovery

**Why this is a stacked PR, not a PR against `main`:** `ba29ee8`'s tests exercise `StreamingTranscriber.last_no_speech_prob`/`last_avg_logprob`, attributes introduced by commit `9ae7510` (ti-3p688.3). That commit is not yet on `origin/main` — it only exists via PR #179 (`deploy/asr-hallucination-gating-ti-86jub`, bead ti-86jub), which is open/MERGEABLE/CI-green but unmerged (confirmed fresh this session: `origin/main` tip is still `3071105`, `git merge-base --is-ancestor 9ae7510 origin/main` fails, PR #179 `updated_at` unchanged since 2026-07-13T17:41Z with `mergedAt: null`).

Two prior deployer sessions held this bead (status=deferred) waiting for #179 to merge rather than opening a PR, on the reasoning that a PR against `main` right now would necessarily carry #179's entire diff along with it. That reasoning missed the documented alternative: `ba29ee8`'s branch is *already* built directly on top of `deploy/asr-hallucination-gating-ti-86jub`'s exact tip (linear history: `ba29ee8` → `3c352a3` → `9ae7510` → `3071105` (origin/main)), so no cherry-pick or rebase is needed — the existing pushed branch can be opened as a stacked PR with `--base deploy/asr-hallucination-gating-ti-86jub` today. This matches the rig's own documented pattern for real cross-bead content dependencies (`bd recall deployer-real-stacked-prs-for-cross-bead-dependencies`): the dependency here is real, not incidental — the new tests directly exercise attributes that don't exist without #179's commit, verified by reading the diffs, not just bead prose.

This does **not** replace the outstanding ask to merge #179 — GitHub won't enforce stack order, so the mayor merge-request explicitly states: merge #179 first, then this PR. Until #179 merges, this PR will show #179's commits in its diff (GitHub stacked-PR UI); that's expected and resolves automatically once #179 lands and this PR's base auto-adjusts to `main`.

**Full-suite reconciliation:** 1865 passed vs. the sibling `ti-86jub` gate's 1861 passed — expected, not a regression; several unrelated commits (e.g. `a6192f1`, `ad49839`, `cd820c1`) landed on `origin/main` between that gate and this one, adding tests. The one failure, `tests/test_daemon_call_card_config.py::test_main_passes_loaded_config_to_call_card_host` ("another instance holds the lock"), is the same pre-existing environmental daemon-PID-lock issue documented in the `ti-86jub` gate and cross-corroborated against ti-n94dj — confirmed present on this branch for the same environmental reason (a stray daemon process holding the lock in this shared box), not caused by this change.

**Mail-verification note:** a prior deployer session (deployer-gm-8m0wm) claimed to have sent and peek-verified a mayor nudge (message id `gm-wisp-sfk9v`) about PR #179. That message ID does not exist under `gc mail peek` or `bd show` as of this session — unverifiable, likely never persisted. A fresh nudge was sent this session (`gm-wisp-v50ze`) and immediately round-tripped via `gc mail peek` to confirm it actually persisted this time. Not gate-relevant to this bead's own criteria, but recorded here since it affects whether mayor was actually informed of the #179 blocker before now.

## Conclusion

Gate **PASS**. Opening a stacked PR: head `tests/streaming-side-channel-ti-qlh6y` @ `ba29ee8`, base `deploy/asr-hallucination-gating-ti-86jub` (PR #179) — **not** `main`. Merge order for mayor/mpr: **#179 first, then this PR.**
