# Release Gate: wake-word-source-ti-ke27h

**Branch:** `feat/wake-word-source-ti-s9mm-5-2`  
**Bead:** ti-ke27h  
**Source bead:** ti-20p82 (review PASS by reviewer-gm-xete3)  
**Date:** 2026-06-30  
**Deployer:** deployer-gm-yihej (tincan-iris/deployer)

---

## Criteria Evaluation

| # | Criterion | Result |
|---|-----------|--------|
| 1 | Review PASS present | **PASS** |
| 2 | Acceptance criteria met | **PASS** — 6/6 spec criteria verified by reviewer |
| 3 | Tests pass | **PASS** — 1569 passed, 3 xpassed, 2 warnings |
| 4 | No high-severity review findings open | **PASS** — INF1/INF2 are informational only |
| 5 | Final branch is clean | **PASS** |
| 6 | Branch diverges cleanly from main | **PASS** — origin/main is direct ancestor |
| 7 | Single feature theme | **PASS** — WakeWordSource only, 3 files |

**Overall: PASS**

---

## Evidence

### Criterion 1 — Review PASS

Review bead **ti-20p82** (closed):

> REVIEW VERDICT: PASS  
> Reviewer: reviewer-gm-xete3 (claude-sonnet-4-6)  
> Commits: 6367b13 (WakeWordSource impl + F1/F2 fixes), 4ba600b (tests)  
> Style/Security/Spec/Coverage: all PASS

### Criterion 2 — Acceptance Criteria

From ti-20p82 review notes (6/6 spec criteria):

- [x] confidence < 0.85 → `async_turn` NOT called — verified at commit 6367b13
- [x] confidence ≥ 0.85 → `async_turn` IS called — verified
- [x] `in_call=True` → entire wake response muted (chime + turn both suppressed) — verified
- [x] Chime fires before `async_turn` — verified
- [x] `IRIS_HEADLESS_TTS=1` + `in_call=True` → Kokoro TTS not called — verified
- [x] `IRIS_HEADLESS_TTS=1` + `in_call=False` → Kokoro TTS called with reply text — verified

### Criterion 3 — Tests Pass

Ran on branch `feat/wake-word-source-ti-s9mm-5-2` in builder worktree:

```
python -m pytest --tb=no -q
```

Result: **1569 passed, 3 xpassed, 2 warnings** in 59.55s

Wake-word suite specifically:

```
python -m pytest tests/test_wake_word_source.py -v
```

Result: **12/12 passed** (0.04s)

2 collection warnings are pre-existing/unrelated to this PR.

### Criterion 4 — No High-Severity Findings

From ti-20p82: no HIGH or CRITICAL findings.

Informational (non-blocking):
- INF1: `_play_chime` temp file may leak if `WaveObject.from_wave_file` raises; impact is a tiny WAV in /tmp that the OS cleans up.
- INF2: `on_reply` not wired to BrainHost in `__main__.py` — expected scaffold gap; headless TTS with real VAD deferred to a future PR.

### Criterion 5 — Branch Clean

`git status` on builder worktree: clean (nothing to commit).

### Criterion 6 — Branch Diverges Cleanly From Main

```
git merge-base --is-ancestor origin/main feat/wake-word-source-ti-s9mm-5-2
→ true — origin/main is a direct ancestor
```

Branch was cut directly off `origin/main`. No conflicts.

### Criterion 7 — Single Feature Theme

Two commits above main, both exclusively WakeWordSource:

| SHA | Title |
|-----|-------|
| 6367b13 | feat(daemon): WakeWordSource — opt-in headless wake-word activation (ti-s9mm.5.2) |
| 4ba600b | tests(wake_word): failing suite for WakeWordSource gates (ti-s9mm.5.3) |

Files changed: `iris/daemon/__main__.py`, `iris/daemon/wake_word.py`, `tests/test_wake_word_source.py`. Single subsystem (wake-word daemon), single feature.
