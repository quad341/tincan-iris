# Release Gate: Call Card AFTER post-call review screen (ti-83qp9)

**Date:** 2026-07-25
**Deploy bead:** ti-83qp9
**Source bead:** ti-qyo3p (Call Card AFTER: PostCallReviewScreen — confirm/edit mode), reviewed under ti-cxfu7
**Shared builder branch:** `feat/callcard-after-data-layer-ti-hb2dx`
**Commit evaluated:** `1481ec3` (feat(capture): Call Card AFTER post-call review screen (ti-qyo3p))
**Deploy branch:** `deploy/ti-83qp9-gate`, cut from `origin/main` @ `1a8ad04`, `1481ec3` cherry-picked (`-x`) as `f0802ad`

## Gate Result: PASS

## Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 6 | Branch diverges cleanly from main | PASS (see Discovery) | Naive "branch at exactly 1481ec3" was UNSAFE — shared branch carries 4 out-of-scope intervening commits. Scoped `git cherry-pick -x 1481ec3` onto fresh `origin/main` applies with zero conflicts and reproduces exactly the reviewed 287-line/2-file diff. |
| 1 | Review PASS present | PASS | ti-cxfu7 (tincan-iris/reviewer, 2026-07-05): full OWASP walk, spec compliance, independent test re-run. "No blocking findings. Advancing to needs-deploy." |
| 2 | Acceptance criteria met | PASS | Reviewer verified against ti-qyo3p's explicit acceptance criteria: trigger events (call_card_recap_ready primary + call_card_ended/2.5s NFR2 fallback), dedup guard, tri-state confirmed handling, focus-on-mount order, non-blocking q/Escape, check_action gate extension. All match. |
| 3 | Tests pass | PASS | Independently re-ran full suite on the constructed deploy branch: 1902 passed, 3 xpassed, 1 failed. The 1 failure (`test_daemon_call_card_config.py::test_main_passes_loaded_config_to_call_card_host`) reproduces identically against bare `origin/main` — root cause is a live `iris.daemon` process (pid 3106) holding this machine's real daemon lock, unrelated to this diff (which touches only `iris/console/app.py` + `iris/console/post_call_review.py`, never `iris/daemon/__main__.py`). |
| 4 | No high-severity findings | PASS | Reviewer's OWASP-focus walk: no blocking findings in this bead's own diff (escape() correctly applied at all dynamic-content sinks in the new file; sub_title path verified non-injectable against installed Textual 8.2.8). One related gap (`ti-hzx44`, P2/security: apply `escape_for_content()` hardening to post_call_review.py's PriorCommitmentCard sink) is already filed and explicitly scoped as intentional post-merge follow-on ("do not start until that deploy lands"), consistent with this bead's other pre-accepted follow-ups (ti-co6cj tests, ti-eppmx pre-existing gap). |
| 5 | Final branch is clean | PASS | Diff is exactly the reviewed 2 files, 287 insertions / 2 deletions. No debug code, no commented-out code, no unrelated changes. |
| 7 | Single feature theme | PASS | Single cohesive feature (PostCallReviewScreen + its app.py event wiring); no bundling of sibling beads' work. |

## Discovery: criterion 6 required a scoped cherry-pick, not the literal SHA recipe

`ti-83qp9`'s own description flagged this as an open risk: "Not independently verified whether 1481ec3 cherry-picks cleanly onto origin/main in isolation... Deployer should verify cherry-pick/merge cleanliness empirically before assuming a clean apply." Prior deploy cycles deferred on a *different*, now-cleared blocker (missing `PriorCommitmentCard`, landed via PR #191). This cycle re-ran the ancestry check from scratch since the shared-branch tip had not been re-examined post-PR #191.

`git log origin/main..1481ec3 --oneline` showed 6 intervening commits on the shared branch `feat/callcard-after-data-layer-ti-hb2dx`. Per-commit file-scope check (`git show --stat`) classified each:

- `e72052b` (ti-6a1y3, recap generator) — **HELD** per ti-zd5os (banned direct-API-key pattern). Must not ship.
- `76237d0` (ti-pkt2r.1, warm ClaudeTuiSession routing) — ships via its own separate open PR #166. Must not be bundled here.
- `60a92dd` (ti-qi76c, eval log store) — confirmed absent from `origin/main` (`iris/capture/eval_log_store.py` does not exist there); not this bead's concern, out of scope.
- `7760814` (ti-llzx9, SENTINEL_CONTACT_ID writeback fix) — confirmed absent from `origin/main` (`grep -c SENTINEL_CONTACT_ID` → 0); out of scope.
- `404e4fc` + `cd53791` (ti-w0dvp, PriorCommitmentCard TDD pair) — content-superseded: `origin/main` already has `class PriorCommitmentCard` (1 occurrence, via squash-merged PR #191) under a different SHA than these originals.

Naively branching "at exactly `1481ec3`" would have silently shipped the HELD recap generator and PR #166's unreviewed-here content alongside this bead. Instead:

```
git checkout -b deploy/ti-83qp9-gate origin/main   # origin/main @ 1a8ad04
git cherry-pick -x 1481ec3                          # → f0802ad, zero conflicts
git diff origin/main --stat
 iris/console/app.py              |  63 ++++++++++-
 iris/console/post_call_review.py | 226 +++++++++++++++++++++++++++++++++++++++
 2 files changed, 287 insertions(+), 2 deletions(-)
```

Exactly the reviewed diff, nothing more, nothing less. Both of `1481ec3`'s own external dependencies resolve cleanly against current `origin/main`:

- `from .call_card import (..., PriorCommitmentCard, ...)` — all 6 imported symbols confirmed present in `origin/main:iris/console/call_card.py` (via PR #191).
- `from ..capture.after_store import AfterStore` / `self._after_store.get_open_commitments(...)` — `AfterStore` class and `get_open_commitments` method confirmed present in `origin/main:iris/capture/after_store.py`, predating and independent of the still-unlanded `7760814` writeback fix.

`python3 -c "import iris.console.app"` on the constructed branch exits 0 — the original hard ImportError blocker is confirmed cleared.

## Conclusion

All 7 criteria pass. `deploy/ti-83qp9-gate` (commit `f0802ad`, cherry-picked from `1481ec3`) is a clean, correctly-scoped, reviewed diff on top of current `origin/main`. Proceeding to push + open PR + route merge-request to mayor.

## Addendum 2026-07-28: gate doc committed late, re-verified

This file was written to disk during the 2026-07-25 gate run and the branch
was correctly pushed with PR #192 opened, but the commit-to-branch step for
*this file* was missed that session — the deploy branch went out with the
right code and no gate evidence attached. Mayor caught this tonight
(2026-07-28 01:40 PT) when declining to merge #192 on an unverifiable gate
citation, and confirmed independently: CI had been red since 2026-07-25 on
an unrelated unpinned-ruff break (fixed via #195), and a fresh, genuinely-new
CI run (30342380406) against this exact head SHA came back green.

Re-verified again now, independently, before committing this file:
- `origin/deploy/ti-83qp9-gate` HEAD = `f0802ad6f06b9500d4832ae884a0b638721a1c02`, matches this doc.
- `gh pr view 192`: MERGEABLE / CLEAN, head SHA as above.
- CI run 30342380406 (head SHA `f0802ad6f06b...`, workflow "CI", job "test"): **1903 passed, 2 skipped, 3 xpassed, 0 failed.** (The single environmental failure noted in the original criterion-3 evidence above — `test_daemon_call_card_config.py::test_main_passes_loaded_config_to_call_card_host`, caused by a stray local `iris.daemon` process holding a real lock on the gate-evaluation machine — does not reproduce in CI's clean container, as expected.)

No re-evaluation of criteria 1/2/4/5/7 was needed: they assess the fixed
commit's content and review history, neither of which changes with time.
Gate result stands: **PASS**, now with the evidence doc actually committed.
