# Release Gate: dispatch-chitchat-ti-dp7p

**Branch:** `fix/dispatch-chitchat-ti-dp7p`  
**Commit:** a446200 (cherry-pick of 26d13eb)  
**Bead:** ti-0q5w.3  
**Date:** 2026-06-25  
**Deployer:** tincan-iris/deployer

---

## Criteria Evaluation

| # | Criterion | Result |
|---|-----------|--------|
| 1 | Review PASS present | **PASS** |
| 2 | Acceptance criteria met | **PASS** |
| 3 | Tests pass | **PASS** (2 pre-existing env failures, see note) |
| 4 | No high-severity review findings open | **PASS** |
| 5 | Final branch is clean | **PASS** |
| 6 | Branch diverges cleanly from main | **PASS** |
| 7 | Single feature theme | **PASS** |

**Overall: PASS**

---

## Evidence

### Criterion 1 — Review PASS

Review bead **ti-wd4s** (closed, PASS):

> Review verdict: PASS  
> Reviewer: tincan-iris/reviewer (2026-06-25T19:52:20Z)  
> Commit: 26d13eb — same content as cherry-pick a446200

### Criterion 2 — Acceptance Criteria

From ti-dp7p:
- [x] `action-vs-conversation` instruction in `_dispatch_prompt()` — present in a446200
- [x] 4 chitchat→none few-shot examples added — present in a446200
- [x] `EchoSkill` removed from `default_registry()` — present in a446200
- [x] 7 new tests: `test_echo_not_in_default_registry`, `test_dispatch_prompt_has_chitchat_bias`, 4×`test_chitchat_dispatches_to_none[…]`, `test_command_dispatches_to_correct_skill` — all confirmed passing

### Criterion 3 — Tests Pass

```
2 failed, 1121 passed, 4 skipped, 3 xpassed, 2 warnings in 9.32s
```

Failures:
- `tests/test_stt.py::test_default_stt_is_faster_whisper`
- `tests/test_tts.py::test_default_tts_uses_kokoro_when_available`

**Note:** Both failures preexist at branch base fd90004 (confirmed by running `pytest tests/test_stt.py tests/test_tts.py` at fd90004 — same 2 failures). These are environment-sensitive tests that fail when the local whisper/kokoro servers are running. They are **not regressions from commit a446200**. Both are already fixed on `origin/main` via commit 1952225 ("Fix environment-sensitive default_stt/tts tests (#94)") and will be resolved once this PR merges from main.

### Criterion 4 — No High-Severity Findings

From ti-wd4s review: Style=CLEAN, Security=NO FINDINGS, Spec compliance=FULLY MET. No HIGH or CRITICAL findings.

### Criterion 5 — Branch Clean

```
On branch fix/dispatch-chitchat-ti-dp7p
nothing added to commit but untracked files present (untracked: .gc/, .gitkeep — not project files)
```

### Criterion 6 — Diverges Cleanly from Main

`git merge-tree` check: no conflict markers. Branch is 5 commits behind `origin/main` (fd90004 base vs 39eab50 tip), but merges cleanly with no conflicts.

### Criterion 7 — Single Feature Theme

Exactly 1 commit on top of main:
```
a446200 fix(dispatch): bias Tier-1 toward none for chitchat; drop echo from default registry (ti-dp7p)
```

Touches: `iris/lanes.py`, `iris/skills.py`, `tests/test_qwen_dispatch.py`, `tests/test_tier0.py` — all within the dispatch/skill subsystem. Single coherent theme.
