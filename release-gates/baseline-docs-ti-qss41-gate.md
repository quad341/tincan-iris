# Release Gate: docs/BASELINE.md — what green means (ti-qss41)

**Date:** 2026-07-13
**Deploy bead:** ti-qss41
**Source beads:** ti-pugo3.4 (build), ti-9ryel (review)
**Branch:** deploy/baseline-docs-ti-qss41
**Commit evaluated:** eb1f8da (cherry-picked from c714c98 on docs/baseline-health-ti-pugo3-4)

## Criteria

| # | Criterion | Result |
|---|-----------|--------|
| 1 | Review PASS present | ✅ Reviewed + PASSED by tincan-iris/reviewer (ti-9ryel), first pass, no request-changes round |
| 2 | Acceptance criteria met | ✅ Every specific claim in the doc (check names, required/optional flags, aggregation rule, notification edge-trigger semantics incl. 24h red re-remind, console pill/panel behavior, owner quote) independently verified by reviewer against real source across three branches |
| 3 | Tests pass | ✅ 1843 passed, 1 pre-existing unrelated failure (ti-8wtzr), 3 xpassed — exact match to today's verified main baseline (see Discovery) |
| 4 | No open HIGH findings | ✅ None. One non-blocking completeness nitpick (doc doesn't mention doctor.py's dynamic required=False downgrade for tincand-dependent checks) — explicitly non-blocking per reviewer, doc's own "Source of truth" section already defers to doctor.py as canonical |
| 5 | Final branch clean | ✅ Single new file, docs/BASELINE.md, 191 insertions, no other changes |
| 6 | Branch diverges cleanly from main | ✅ `git merge-base --is-ancestor origin/main HEAD` confirmed — branch is main + exactly 1 commit, fast-forward-able |
| 7 | Single feature theme | ✅ Docs-only, single file, single topic (baseline health system reference doc) |

## Discovery

Cherry-picked `c714c98` cleanly onto a fresh branch off current `origin/main` (tip `3071105`, unchanged since this deploy pass began). `ruff check iris/ tests/ scripts/` clean. Full suite: 1843 passed / 1 failed / 3 xpassed — this is an exact match to the plain-main baseline independently established earlier this session (via a disposable scratch worktree, documented in the ti-26ad0 gate), which is the expected result for a docs-only change that adds zero tests.

**Content-accuracy note:** this doc describes daemon-broadcast, degradation-notify, and console health-panel behavior (ti-pugo3.2/.3) that is reviewed and gated PASS this session but was **not yet merged to origin/main** at commit-authorship time, and is still not merged as of this gate (merge authority is mayor/mpr; PRs #181/#182/#183 remain open). The bead carries a builder-originated deploy-sequencing flag (previously raised to mayor via mail gm-wisp-6o5dph) recommending this doc not land on main before that behavior does, to avoid main temporarily documenting behavior that isn't live. This gate evaluates the commit on its own technical merits (all 7 criteria pass independently of merge order); the sequencing concern is a merge-order instruction for mayor, not a gate failure — flagged explicitly in the merge-request mail below.

## Conclusion

**Gate: PASS**

Next action: push branch, open PR against `main`, close bead, mail mayor a merge-request that explicitly carries forward the sequencing flag — this PR must merge **after** #181 (ti-26ad0), #182 (ti-dy06r), and #183 (ti-0lw2d), not before.
