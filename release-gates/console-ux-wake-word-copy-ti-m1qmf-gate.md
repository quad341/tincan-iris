# Release Gate: console-ux-wake-word-copy-ti-m1qmf

**Branch:** `fix/console-wake-word-copy`  
**Bead:** ti-m1qmf  
**Source bead:** ti-es9us / ti-vrhe8 (review PASS by reviewer-gm-wisp-45x8peo)  
**Date:** 2026-06-27  
**Deployer:** deployer-gm-wisp-dxu23r3 (tincan-iris/deployer)

---

## Criteria Evaluation

| # | Criterion | Result |
|---|-----------|--------|
| 1 | Review PASS present | **PASS** |
| 2 | Acceptance criteria met | **PASS** |
| 3 | Tests pass | **PASS** — 1287 passed, 13 skipped, 3 xpassed |
| 4 | No high-severity review findings open | **PASS** |
| 5 | Final branch is clean | **PASS** |
| 6 | Branch diverges cleanly from main | **PASS** — clean merge-tree |
| 7 | Single feature theme | **PASS** — console UX only, single file |

**Overall: PASS**

---

## Evidence

### Criterion 1 — Review PASS

Review bead **ti-vrhe8** (closed):

> REVIEW VERDICT: PASS  
> Reviewer: reviewer-gm-wisp-45x8peo  
> Commit: 7c97e74 (original) → cherry-picked as 593364d on fix/console-wake-word-copy  
> Style/Security/Spec/Coverage: all PASS

### Criterion 2 — Acceptance Criteria

From ti-vrhe8:
- [x] All 5 user-facing 'Iris, …' strings updated to 'Hey Iris, …' — confirmed in 593364d
- [x] `action_copy_last` implemented with `[y]` binding; wl-copy → xclip → xsel fallback chain — confirmed in 593364d
- [x] Clipboard content passed via stdin (no injection surface) — confirmed by reviewer
- [x] `check_action` gate: binding only active after Iris has replied — confirmed

### Criterion 3 — Tests Pass

Ran on branch `fix/console-wake-word-copy` at `/tmp/cherry-console`:

```
python -m pytest tests/ -x -q \
  --ignore=tests/test_pipecat_stt.py \
  --ignore=tests/test_pipecat_tts.py
```

Result: **1287 passed, 13 skipped, 3 xpassed** in 25.56s

Ignored tests:
- `test_pipecat_stt.py`, `test_pipecat_tts.py` — pre-existing missing pipecat deps, unrelated to this feature

### Criterion 4 — No High-Severity Findings

From ti-vrhe8: PASS on style, security, spec, coverage. No HIGH or CRITICAL findings.

### Criterion 5 — Branch Clean

`git status` on `/tmp/cherry-console` (before gate commit): clean.

### Criterion 6 — Branch Diverges Cleanly From Main

```
git merge-base origin/main origin/fix/console-wake-word-copy
→ 60454d32a60d35f498705f2962bcf0adb176a8eb  (current main tip)
```

Branch was cut directly off current `origin/main`. `git merge-tree --write-tree` returned clean SHA with no conflict markers.

### Criterion 7 — Single Feature Theme

Single commit on this branch above main:

| SHA | Title |
|-----|-------|
| 593364d | fix(console): wake-word text 'Hey Iris' + copy-last-reply binding (ti-dq8w1) |

One file changed: `iris/console/app.py`. Two tightly coupled console UX improvements in the same file — wake-word wording and clipboard copy — ship together as one coherent fix.
