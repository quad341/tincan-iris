# Release Gate: footer-key-hints-80col-ti-6tpmn

**Branch:** `fix/footer-key-hints-ti-ffch2-3-1` (deployed via `deploy/footer-key-hints-ti-6tpmn`, pinned to the same commit)  
**Bead:** ti-6tpmn  
**Source bead:** ti-rvngp (review PASS by reviewer-gm-wisp-anw8hc)  
**Date:** 2026-07-04  
**Deployer:** deployer-gm-wisp-001dbd (tincan-iris/deployer)

---

## Criteria Evaluation

| # | Criterion | Result |
|---|-----------|--------|
| 1 | Review PASS present | **PASS** |
| 2 | Acceptance criteria met | **PASS** |
| 3 | Tests pass | **PASS** — 1616 passed, 3 xpassed, 0 failed |
| 4 | No high-severity review findings open | **PASS** |
| 5 | Final branch is clean | **PASS** |
| 6 | Branch diverges cleanly from main | **PASS** — single commit, merge-base = origin/main tip |
| 7 | Single feature theme | **PASS** — footer key-hint label text only, single file |

**Overall: PASS**

---

## Evidence

### Criterion 1 — Review PASS

Bead ti-6tpmn notes (routed from ti-rvngp):

> Status: Reviewed + PASSED by reviewer tincan-iris/reviewer.

### Criterion 2 — Acceptance Criteria

Per ti-ffch2.3.1 spec: 6 `Binding` description strings in `iris/console/app.py` shortened for 80-column footer legibility. Independently confirmed via diff — `l`→"hear", `V`→"card", `f`→"far", `i`→"stop", `c`→"cmds", `K`→"book". No key, action, or dispatch changes; `show=False` bindings and `priority=True` flags all unchanged.

### Criterion 3 — Tests Pass

Ran independently in a disposable detached worktree (`/tmp/deploy-verify-ti-6tpmn`, commit `dd3ea2c`), not just trusted the reviewer's reported numbers:

```
python3 -m pytest -q
```

Result: **1616 passed, 3 xpassed, 0 failed** in 71.62s — matches the reviewer's reported numbers exactly.

Also ran `ruff check iris/console/app.py` — all checks passed.

### Criterion 4 — No High-Severity Findings

Bead notes report no HIGH/CRITICAL findings; diff independently confirmed to touch only `Binding(...)` description-string arguments (the third positional arg), zero mechanism/dispatch changes.

### Criterion 5 — Branch Clean

`git status` on the deploy branch (before gate commit): clean (only pre-existing, unrelated untracked worktree artifacts: `.gc/`, `.gitkeep`, `tincan_iris.egg-info/`).

### Criterion 6 — Branch Diverges Cleanly From Main

```
git merge-base origin/main dd3ea2c7daf7f33adb3584b2b621de9792ccfde4
→ 088b7da2e0c780a2725cab94ab51a1bd500556b9  (= origin/main tip)
```

Single commit directly on top of current `origin/main`. Trivial fast-forward, zero conflict risk.

### Criterion 7 — Single Feature Theme

One commit, one file:

| SHA | Title |
|-----|-------|
| dd3ea2c | fix(console): shorten footer key-hint labels for 80-col legibility (ti-ffch2.3.1) |

`iris/console/app.py` only — 6 lines changed (12 total, 6 insertions/6 deletions), all within the same `BINDINGS` list. Single, coherent, cosmetic theme.
