# Release Gate: Call Card enricher tests reconciled with fix-1+fix-2 (ti-0xwj3)

**Date:** 2026-07-25
**Deploy bead:** ti-0xwj3
**Source bead:** ti-3p688.6 (reviewer), covering ti-3p688.1 (fact dedup) + ti-3p688.2 (action-item consolidation) + ti-3p688.4 (test authoring/reconciliation)
**Reviewed branch:** `tests/enricher-fact-dedup-cue-context-action-items-ti-3p688-4`
**Commit evaluated:** `87c2eac` (test(enricher): reconcile with shipped fix-1/fix-2, fix turn_ids fixture)
**Deploy branch:** `deploy/ti-0xwj3-gate`, cut from `origin/main` @ `1a8ad04`, net-new `tests/test_enricher.py` content added as `59a2d1f`

## Gate Result: PASS

## Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 6 | Branch diverges cleanly from main | PASS (see Discovery) | Hard prerequisites (PR #175, PR #180) confirmed MERGED. Reviewed branch has 9 intervening commits vs. main, but per the bead's own explicit instructions only 1 file (`tests/test_enricher.py`, net-new) is this bead's actual scope — the rest are the already-separately-shipped fix-1/fix-2 commit pairs plus this branch's now-stale fork point (predates several other since-landed features). Took the file's exact content at `87c2eac` and added it fresh onto current `origin/main`. |
| 1 | Review PASS present | PASS | ti-3p688.6 (tincan-iris/reviewer): merge-conflict reconciliation (0ccbe59) independently verified correct, fixture change traced and confirmed a legitimate contract fix (not test-shaped-to-fit), independent disposable-worktree re-run green. |
| 2 | Acceptance criteria met | PASS | Test file exercises exactly the contracts fix-1 (`upsert_enriched_fact` dedup/cue-context/confirmed-guard) and fix-2 (`ActionItemExtract.transcript_turn_ids` consolidation) were reviewed and merged against (PR #175, PR #180). |
| 3 | Tests pass | PASS | `pytest tests/test_enricher.py -v`: 5/5 pass. Full suite on the constructed deploy branch: 1907 passed, 3 xpassed, 1 failed — the same pre-existing `test_daemon_call_card_config.py` daemon-PID-lock environmental failure independently confirmed unrelated during ti-83qp9's gate this same session (reproduces identically on bare `origin/main`; this branch never touches `iris/daemon/`). `ruff check iris tests scripts`: clean. |
| 4 | No high-severity findings | PASS | Reviewer: fully parameterized SQL in all new store.py methods (already on main via PR #175/#180), no new external input sink, no threading hazard. This deploy adds test code only. |
| 5 | Final branch is clean | PASS | Diff is exactly 1 new file, 182 insertions, nothing else. |
| 7 | Single feature theme | PASS | Single cohesive addition — regression coverage for the already-shipped fact-dedup + action-item-consolidation pair. |

## Discovery: prerequisite PRs merged; scope narrowed to the surviving file

Both hard prerequisites flagged in the bead description are now cleared:

```
gh pr view 175 --json state,mergedAt  → MERGED 2026-07-22T07:35:37Z
gh pr view 180 --json state,mergedAt  → MERGED 2026-07-22T07:41:43Z
```

`git log origin/main..87c2eac --oneline` still shows 9 intervening commits (two merge commits pulling in the PR #175/#180 deploy branches, their gate-PASS chore commits, the fix-1/fix-2 commits themselves, the original test-authoring commit, the cross-fix reconciliation merge, and the final fixture fixup). Per the classic squash-merge-ancestry pattern, none of the fix-1/fix-2 content is missing from `origin/main` — it's there under different SHAs (confirmed: `upsert_enriched_fact` present in `iris/capture/store.py`, `transcript_turn_ids` present ×4 in `iris/capture/enricher.py`). The bead's own description anticipated this exactly: "do NOT push this whole 9-commit branch as-is (it still contains the two already-shipped-separately fix commit pairs)."

A raw two-dot tree diff (`git diff origin/main..87c2eac --stat`) is misleading here — it shows large unrelated deletions (`iris/console/call_card.py`, `tests/test_prior_commitment_card.py`, `tests/test_asr_gate.py`, etc.) because this branch's fork point predates several other features that have since landed on main via separate paths. That diff reflects branch staleness, not deploy scope.

Scoped to just the actual net-new content:

```
git diff origin/main..87c2eac -- tests/test_enricher.py --stat
 tests/test_enricher.py | 182 ++++++++++++++++++++++++ (new file)
```

Confirmed self-contained: all imports (`iris.capture.enricher.{ActionItemExtract,EnrichmentSchema,FactExtract,PostCallEnricher}`, `iris.capture.schemas.{ActionItem,CapturedFact,FactType}`, `iris.capture.store.CallCardStore`) resolve against current `origin/main`. Built the deploy branch by extracting the file's exact content at `87c2eac` (`git show 87c2eac:tests/test_enricher.py`) onto a fresh branch off `origin/main`, rather than cherry-picking any of the 9 commits — the commit-based recipe doesn't apply cleanly to a two-step author-then-fixup history where the intermediate state never existed on main.

## Conclusion

All 7 criteria pass. `deploy/ti-0xwj3-gate` (commit `59a2d1f`) adds exactly the reviewed test coverage on top of current `origin/main`, both its prerequisite fixes already shipped. Proceeding to push + open PR + route merge-request to mayor.

## Addendum 2026-07-28: gate doc committed late, re-verified

Same gap as ti-83qp9's gate (see that file's addendum for the general
pattern): this file was written during the 2026-07-25 gate run and PR #193
was correctly opened at commit `59a2d1f`, but the commit-to-branch step for
this file was missed, leaving the PR's cited gate evidence unreadable from
GitHub. Found while auditing other untracked gate files in this worktree
after the mayor caught the identical issue on PR #192/ti-83qp9 — nobody had
flagged this one yet.

Re-verified independently before committing:
- `origin/deploy/ti-0xwj3-gate` HEAD = `59a2d1f90fd07409aeeabe60213f65dbce0639c6`, matches this doc.
- PR #193 was OPEN, head SHA as above, prior CI run (30149755565) showed
  `fail` — but that run predates the ruff-pin fix (#195) and the branch's own
  `.github/workflows/ci.yml` is pre-pin (confirmed via diff vs `origin/main`),
  same root cause as PR #192's stale-CI red, not a defect in this bead's code.
- Committing this file triggers a fresh `synchronize` run against current
  `origin/main` (which now carries the ruff pin), expected to go green the
  same way PR #192's did.

No re-evaluation of criteria 1/2/4/5/7 needed — they assess fixed commit
content and review history, neither changes with time. Gate result stands:
**PASS**, now with the evidence doc actually committed.
