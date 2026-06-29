# Release Gate: voice-catalogue-config-path-ti-xsgx3

**Branch:** `fix/test-fixes-ti-gxpt1.3-et9i`  
**Reviewed commit:** `714093a` (fix(voice-catalogue): use settings.config_path() instead of CWD-relative Path)  
**Bead:** ti-xsgx3  
**Source bead:** ti-8g014 (review: PASS by reviewer-gm-wisp-fdw498i)  
**Date:** 2026-06-27  
**Deployer:** deployer-gm-wisp-8q7p2ht (tincan-iris/deployer)

---

## Criteria Evaluation

| # | Criterion | Result |
|---|-----------|--------|
| 1 | Review PASS present | **PASS** |
| 2 | Acceptance criteria met | **PASS** |
| 3 | Tests pass | not evaluated (gate failed earlier) |
| 4 | No high-severity review findings open | **PASS** |
| 5 | Final branch is clean | **PASS** (working tree clean) |
| 6 | Branch diverges cleanly from main | **FAIL** — 7 merge conflicts |
| 7 | Single feature theme | not evaluated (gate failed earlier) |

**Overall: FAIL**

---

## Evidence

### Criterion 1 — Review PASS

Review bead **ti-8g014** (closed):

> Review verdict: PASS  
> Reviewer: reviewer-gm-wisp-fdw498i  
> Commit: 714093a on fix/test-fixes-ti-gxpt1.3-et9i  
> "9/9 voice_catalogue tests pass. 1163 others pass. Ruff clean. Deploy bead ti-xsgx3 created."

### Criterion 2 — Acceptance Criteria

From ti-8g014 (review of the MEDIUM finding fix from ti-mk6rf):
- [x] `iris/audio/voice_catalogue.py:38`: `Path('config.toml')` → `settings.config_path()` — confirmed in 714093a
- [x] Test fixtures updated to use `IRIS_CONFIG` env var — confirmed in 714093a
- [x] Ruff clean — confirmed by reviewer
- [x] 9/9 voice_catalogue tests pass — confirmed by reviewer

### Criterion 4 — No High-Severity Findings

From ti-8g014: No HIGH or CRITICAL findings. The MEDIUM finding (CWD-relative path) was fixed in 714093a.

### Criterion 5 — Branch Clean

Working tree in deployer worktree is clean. The local branch `fix/test-fixes-ti-gxpt1.3-et9i` has 5 commits not yet pushed to origin (eac6c2f, 664ce16, 97ad740, 714093a, 7c97e74).

### Criterion 6 — FAIL: Branch Diverges From Main With Conflicts

`git merge-tree --write-tree origin/main fix/test-fixes-ti-gxpt1.3-et9i` reports 7 conflict files:

```
CONFLICT (content):   iris/brain.py
CONFLICT (content):   iris/console/app.py
CONFLICT (content):   tests/test_iris_up.py
CONFLICT (add/add):   tests/test_pipecat_stt.py
CONFLICT (content):   tests/test_roster_migration.py
CONFLICT (content):   tests/test_stt.py
CONFLICT (content):   tests/test_tts.py
```

**Root cause:** The branch was cut from `fd90004` (commit #91 on main). Main has since advanced to commit #108+ via squash-merges of multiple features (IrisSTTService, daemon, calls, ride-along, etc.). The branch has not been rebased onto current main, and the divergence creates conflicts in several actively-modified files.

**PR scope issue (criterion 7 — not formally evaluated):** The two-dot PR diff (`git diff origin/main origin/fix/test-fixes-ti-gxpt1.3-et9i`) shows 106 files changed (+3246, -7076 lines), spanning brain, console, daemon removal, docs removal, roster, tests, and more. This is not a single feature theme.

---

## Recommended Builder Action

The voice-catalogue feature (`714093a` and its companion commits) is clean and reviewed. The branch it lives on is not deployable due to age and scope.

**Recommended fix:** Cut a fresh branch off `origin/main` containing only the voice-catalogue commits:

```bash
git checkout -b fix/voice-catalogue-config-path origin/main
git cherry-pick eac6c2f  # feat(voice): voice catalogue + ProfileResolver + lang TTS params
git cherry-pick 664ce16  # tests(voice_catalogue)
git cherry-pick 97ad740  # tests(profile_resolver)
git cherry-pick 714093a  # fix(voice-catalogue): settings.config_path()
# Verify tests pass, then create a new deploy bead
```

Note: `7c97e74` (console wake-word fix) is a separate independent feature and should NOT be cherry-picked into this branch — it belongs in its own PR.
