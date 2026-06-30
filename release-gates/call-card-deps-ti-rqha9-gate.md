# Release Gate: call-card-deps-ti-rqha9

**Bead:** ti-rqha9 — needs-deploy: call-card optional extra — phonenumbers+dateparser
**Review bead:** ti-nju9a — Review: pyproject.toml call-card extra (ti-rnlqo.2.2) — CLOSED/PASS
**Reviewed commit:** 394bbc1 (cherry-picked as 6a7e08c on feat/call-card-deps-ti-rqha9)
**Branch:** feat/call-card-deps-ti-rqha9 → origin/main
**Date:** 2026-06-30

## Gate Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | ✅ PASS | ti-nju9a notes: `verdict: PASS` by reviewer gm-aq7u3 (2026-06-30T20:43Z) |
| 2 | Acceptance criteria met | ✅ PASS | See below |
| 3 | Tests pass | ✅ PASS | 1557 passed, 3 xpassed (0 failures) on superset branch |
| 4 | No HIGH-severity findings | ✅ PASS | Reviewer: "findings: none — clean change" |
| 5 | Final branch clean | ✅ PASS | 1 commit ahead of origin/main; no uncommitted tracked changes |
| 6 | Branch diverges cleanly | ✅ PASS | Clean cherry-pick onto origin/main; no conflicts |
| 7 | Single feature theme | ✅ PASS | One file changed (pyproject.toml), one subsystem (build/packaging) |

**Overall: PASS**

## Acceptance Criteria Verification

**pyproject.toml [call-card] optional-dependency group:**
```toml
[project.optional-dependencies]
console = ["textual>=8"]
call-card = [
    "phonenumbers>=8.13",
    "dateparser>=1.2",
]
```
- `phonenumbers>=8.13` and `dateparser>=1.2` are explicitly called out in
  `docs/designs/call-card-fact-catalog.md:77-78` as the required L1 extractor libs.
- Zero-core-deps principle preserved — the group is optional, not in `dependencies`.
- Pattern follows existing `[console]` optional group convention in the file.

**Version bounds:** phonenumbers>=8.13 (current: 9.0.33), dateparser>=1.2 (current: 1.4.1) — sensible
lower bounds per reviewer.

## Test Run

Ran on `feat/call-card-deps-ti-rnlqo-2-2` (builder branch, superset of this change):

```
$ python3 -m pytest tests/ -x -q
...
1557 passed, 3 xpassed, 2 warnings in 69.29s
```

The pyproject.toml change is additive (new optional group, no existing test coverage
touching it). The full suite confirms no regressions in core/daemon/console/capture
subsystems.

## Commit

```
6a7e08c feat(build): add call-card optional extra with phonenumbers + dateparser (ti-rnlqo.2.2)
 pyproject.toml | 4 ++++
 1 file changed, 4 insertions(+)
```

Cherry-picked cleanly from 394bbc1 (builder commit on feat/call-card-deps-ti-rnlqo-2-2).
Branch cut fresh off origin/main (0199986) — only this one commit ahead.
