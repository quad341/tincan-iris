# Release Gate: voice-catalogue-config-path-ti-620tr

**Branch:** `fix/voice-catalogue-config-path`  
**Bead:** ti-620tr  
**Source bead:** ti-xsgx3 / ti-8g014 (review PASS by reviewer-gm-wisp-fdw498i)  
**Date:** 2026-06-27  
**Deployer:** deployer-gm-wisp-dxu23r3 (tincan-iris/deployer)

---

## Criteria Evaluation

| # | Criterion | Result |
|---|-----------|--------|
| 1 | Review PASS present | **PASS** |
| 2 | Acceptance criteria met | **PASS** |
| 3 | Tests pass | **PASS** — 1296 passed, 13 skipped, 3 xpassed |
| 4 | No high-severity review findings open | **PASS** |
| 5 | Final branch is clean | **PASS** |
| 6 | Branch diverges cleanly from main | **PASS** — clean merge-tree |
| 7 | Single feature theme | **PASS** — voice catalogue subsystem only |

**Overall: PASS**

---

## Evidence

### Criterion 1 — Review PASS

Review bead **ti-8g014** (closed):

> Review verdict: PASS  
> Reviewer: reviewer-gm-wisp-fdw498i  
> Commit: 714093a (original) → cherry-picked as 44c882f on fix/voice-catalogue-config-path  
> 9/9 voice_catalogue tests pass. 1163 others pass. Ruff clean. All prior blockers resolved.

### Criterion 2 — Acceptance Criteria

From ti-8g014 (fix of MEDIUM finding from ti-mk6rf):
- [x] `iris/audio/voice_catalogue.py:38`: `Path('config.toml')` → `settings.config_path()` — confirmed in 44c882f
- [x] Test fixtures updated to use `IRIS_CONFIG` env var (monkeypatch.setenv) — confirmed in 44c882f
- [x] Ruff clean — confirmed by reviewer
- [x] 9/9 voice_catalogue tests pass — confirmed and re-verified in criterion 3

### Criterion 3 — Tests Pass

Ran on branch `fix/voice-catalogue-config-path` at `/tmp/cherry-voice`:

```
python -m pytest tests/ -x -q \
  --ignore=tests/test_profile_pipeline_integration.py \
  --ignore=tests/test_pipecat_stt.py \
  --ignore=tests/test_pipecat_tts.py
```

Result: **1296 passed, 13 skipped, 3 xpassed** in 29.84s

Ignored tests:
- `test_profile_pipeline_integration.py` — intentional TDD red for ti-d3lr (noted in bead description)
- `test_pipecat_stt.py`, `test_pipecat_tts.py` — pre-existing missing pipecat deps, unrelated to this feature

### Criterion 4 — No High-Severity Findings

From ti-8g014: No HIGH or CRITICAL findings. The MEDIUM finding (CWD-relative path) was the subject of this fix and is resolved in 44c882f.

### Criterion 5 — Branch Clean

`git status` on `/tmp/cherry-voice` (before gate commit): clean.

### Criterion 6 — Branch Diverges Cleanly From Main

```
git merge-base origin/main origin/fix/voice-catalogue-config-path
→ 60454d32a60d35f498705f2962bcf0adb176a8eb  (current main tip)
```

Branch was cut directly off current `origin/main`. `git merge-tree --write-tree` returned clean SHA with no conflict markers.

### Criterion 7 — Single Feature Theme

Four commits on this branch above main:

| SHA | Title |
|-----|-------|
| eb23c3e | feat(voice): voice catalogue + ProfileResolver + lang TTS params |
| 45831a1 | tests(voice_catalogue): validate voice_for_lang() and TOML override path |
| 150be17 | tests(profile_resolver): failing TDD suite for ProfileResolver pipeline integration |
| 44c882f | fix(voice-catalogue): use settings.config_path() instead of CWD-relative Path |

All four commits are within the `iris/audio/voice_catalogue.py` / `iris/audio/profile_resolver.py` / `tests/test_voice_catalogue.py` / `tests/test_profile_resolver.py` subsystem. Single coherent feature: voice catalogue module with settings-aware config path resolution.
