# Release Gate: callcard-disclosure-hardgate-ti-ir12t

**Bead:** ti-p3pd3 — needs-deploy: Call Card disclosure hard-gate channel-split (from:ti-s6kz3)
**Source bead:** ti-s6kz3 — Review: Call Card disclosure hard-gate channel-split (ti-ir12t) — CLOSED/PASS
**Build bead:** ti-ir12t — Call Card: hard-gate far-party capture on disclosure ack/skip — CLOSED
**Reviewed commits:** 6c3fde9 (feature), 546212f (Finding-1 TOCTOU fix)
**Test commit:** 4eab054 (ti-9oguk, cherry-picked onto this branch as 5bacdec)
**Branch:** feat/callcard-disclosure-hardgate-ti-ir12t → origin/main
**Date:** 2026-07-04

## Gate Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | ✅ PASS | ti-s6kz3 notes: "VERDICT: PASS" (reviewer re-review of 546212f), after the original request-changes verdict on Finding 1 was resolved |
| 2 | Acceptance criteria met | ✅ PASS | See below |
| 3 | Tests pass | ✅ PASS | 1644 passed, 1 skipped, 3 xpassed, 0 failed — independently re-run in an isolated venv on the assembled branch |
| 4 | No HIGH-severity findings open | ✅ PASS | Finding 1 (MEDIUM-HIGH, TOCTOU race in `disclosure_ack`) fixed in 546212f and independently re-verified by the reviewer with 4 repro scenarios; no other findings raised |
| 5 | Final branch clean | ✅ PASS | `git status` clean, no uncommitted tracked changes, after the cherry-pick |
| 6 | Branch diverges cleanly | ✅ PASS | 3 commits ahead of origin/main (088b7da); test-commit cherry-pick applied with 0 conflicts |
| 7 | Single feature theme | ✅ PASS | All commits touch only the Call Card disclosure hard-gate feature: daemon (`call_card_host.py`, `api.py`), console (`call_card.py`, `app.py`), capture (`session.py`, `store.py`), plus their tests |

**Overall: PASS**

## Acceptance Criteria Verification (ti-ir12t)

- `DisclosureCard` `[D]`/`[S]` actions now post Messages that `IrisConsole` forwards to the daemon as `disclosure_ack` / `disclosure_skip` — previously nothing sent these; reviewer verified via `git grep` across `origin/main` plus empirical `Message.handler_name` resolution.
- `CaptureSession.start()` split into `start_operator()` / `start_far()`; `start_far()` is only invoked from `disclosure_ack()`.
- New `CallCardHost.disclosure_skip()` mirrors `disclosure_ack` plumbing but never calls `start_far()` — far channel stays off for the rest of that call.
- `CallCardStore` disclosure tracking extended from boolean to tri-state (`pending`/`disclosed`/`skipped`), additive; guarded `ALTER TABLE` migration + backfill verified against a simulated pre-existing database.
- No auto-timeout/auto-disclose fallback anywhere in the diff (confirmed by reviewer).
- Regression tests — far channel never starts before ack; skip permanently prevents far-channel start; call-ends-before-response leaves `CaptureSession.stop()` a safe no-op — covered by the cherry-picked `tests/test_call_card_host.py` + `tests/test_disclosure_card.py` (ti-9oguk suite).
- Finding 1 (TOCTOU race: session torn down mid-`start_far()`) fixed in 546212f via a corrective post-call identity re-check (`self._session is not session`); reviewer independently reproduced 4 scenarios (race / happy-path / stale-id / sequential-teardown), all passing.

**Known non-blocking coverage gap:** no committed regression test yet asserts the Finding-1 corrective-fix behavior specifically (the existing suite covers the rest of the feature and passes). Tracked separately as ti-ofce3 (needs-tests, routed to validator), filed non-blocking per this rig's coverage-check policy — the same policy already applied earlier in this feature chain (ti-9oguk/ti-94lrs).

## Test Run

Ran on `feat/callcard-disclosure-hardgate-ti-ir12t` after cherry-picking 4eab054 (as 5bacdec), inside a disposable venv (`.deploy-venv`, `pip install -e '.[console,call-card]' pytest ruff`) to avoid touching the shared global environment:

```
$ python3 -m pytest tests/ -q
...
1644 passed, 1 skipped, 3 xpassed in 86.33s (0:01:26)

$ ruff check iris/daemon/call_card_host.py iris/console/call_card.py iris/console/app.py \
    iris/capture/session.py iris/capture/store.py iris/daemon/api.py \
    tests/test_call_card_host.py tests/test_disclosure_card.py
All checks passed!
```

Matches the reviewer's independently-verified numbers exactly (ti-s6kz3 notes). One known unrelated intermittent flake (`test_daemon_api.py::test_dnd_on_ack`, DND/posture race, tracked under ti-51vep) did not reproduce this run.

## Commits

```
6c3fde9 feat(daemon,console): hard-gate far-party capture on disclosure ack/skip (ti-ir12t)
 iris/capture/session.py       |  7 +++++++
 iris/capture/store.py         | 33 +++++++++++++++++++++++++++++++--
 iris/console/app.py           | 18 +++++++++++++++++-
 iris/console/call_card.py     | 24 ++++++++++++++++++++++++
 iris/daemon/api.py            | 14 ++++++++++++++
 iris/daemon/call_card_host.py | 22 +++++++++++++++++++---
 6 files changed, 112 insertions(+), 6 deletions(-)

546212f fix(daemon): close TOCTOU race in disclosure_ack far-capture start (ti-s6kz3)
 iris/daemon/call_card_host.py | 12 ++++++++++++
 1 file changed, 12 insertions(+)

5bacdec tests(capture,daemon,console): Call Card disclosure hard-gate suite (ti-9oguk)
 6 files changed, 469 insertions(+), 3 deletions(-)
 create mode 100644 tests/test_call_card_host.py
 create mode 100644 tests/test_disclosure_card.py
```

Branch is `feat/callcard-disclosure-hardgate-ti-ir12t`, tip 546212f — itself a clean
2-commit fast-forward off `origin/main` @ 088b7da (verified via `git merge-base`).
Test commit 4eab054 cherry-picked cleanly onto it: independently confirmed via
`git cat-file -p` that both 546212f and 4eab054 share the same single parent
(6c3fde9) before trusting the reviewer's no-contamination claim — this feature area
has seen repeated validator-worktree branch contamination on sibling beads
(ti-1a4xy/ti-94lrs), so this was checked rather than assumed.

## Operator sign-off note

The parent architecture bead (ti-o6y73) remains open pending explicit operator
confirmation of the underlying consent risk posture (`bd human`). This deploy ships
the architect's recommended default (hard-gate, channel-split, matching the existing
ti-rqhn precedent) so the pipeline isn't blocked on that response, per ti-ir12t's own
notes. If the operator's answer changes the policy, follow-up work will be needed.
