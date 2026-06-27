# Release Gate: IrisSTTService + voice/ package (ti-eq6d.1 / ti-vaceb)

**Date:** 2026-06-26
**Bead:** ti-vaceb (deploy) / ti-eq6d.1 (source)
**Branch:** fix/iris-stt-service-ti-eq6d.1
**Source commit:** 183307c (feat(voice): IrisSTTService + convert voice.py to voice/ package)
**Deployer:** tincan-iris/deployer

---

## Criteria Evaluation

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | **PASS** | Review bead ti-qr9w — verdict: PASS |
| 2 | Acceptance criteria met | **PASS** | All three criteria verified — see below |
| 3 | Tests pass | **PASS** | 1338 passed, 3 xpassed, 2 warnings — zero failures |
| 4 | No high-severity review findings | **PASS** | No HIGH or CRITICAL findings in ti-qr9w |
| 5 | Final branch is clean | **PASS** | `git status` shows only untracked non-project files (.gc/, .gitkeep, stale gate file) |
| 6 | Branch diverges cleanly from main | **PASS** | Cherry-pick of 183307c onto fresh origin/main branch applied without conflict |
| 7 | Single feature theme | **PASS** | 2 commits; both within iris/voice/ subsystem — one feature, one test suite |

**Overall: PASS**

---

## Evidence

### Criterion 1 — Review PASS

Review bead **ti-qr9w** (closed, PASS):

> Review verdict: PASS  
> Reviewer: reviewer-gm-wisp-147ar5m (2026-06-26)  
> Commit: 183307c — IrisSTTService + voice.py → voice/ package conversion

Style/lint ruff clean; security (tempfile, unlink, executor) clean; correctness (non-blocking, empty-guard, cleanup) PASS; 7 TDD tests pass.

### Criterion 2 — Acceptance Criteria

From ti-eq6d.1:
- [x] `iris/voice.py` converted to `iris/voice/__init__.py` package — present in fc4bb9a (cherry-pick of 183307c)
- [x] `iris/voice/pipecat_stt.py` implemented with IrisSTTService — present in fc4bb9a; wraps STT in executor, guards empty transcripts, cleans up temp WAV in try/finally, raises ImportError without pipecat-ai
- [x] `tests/test_pipecat_stt.py` — 7 TDD tests all pass (see criterion 3)

### Criterion 3 — Tests Pass

Full suite on `fix/iris-stt-service-ti-eq6d.1`:

```
1338 passed, 3 xpassed, 2 warnings in 33.56s
```

IrisSTTService TDD suite (7 tests):

```
PASSED tests/test_pipecat_stt.py::test_run_stt_returns_transcription_frame_for_non_empty_audio
PASSED tests/test_pipecat_stt.py::test_run_stt_with_empty_transcript_yields_nothing
PASSED tests/test_pipecat_stt.py::test_run_stt_does_not_block_event_loop
PASSED tests/test_pipecat_stt.py::test_set_language_hint_passes_lang_to_stt
PASSED tests/test_pipecat_stt.py::test_set_language_hint_none_resets_language
PASSED tests/test_pipecat_stt.py::test_temp_wav_cleaned_up_on_transcribe_error
PASSED tests/test_pipecat_stt.py::test_import_error_without_pipecat
```

### Criterion 4 — No High-Severity Findings

From ti-qr9w review: Style=CLEAN, Security=NO FINDINGS, Spec compliance=FULLY MET. No HIGH or CRITICAL findings.

### Criterion 5 — Branch Clean

```
On branch fix/iris-stt-service-ti-eq6d.1
Untracked files: .gc/, .gitkeep, release-gates/ruff-gate-ti-mi3z-gate.md
```

No staged or unstaged modifications to tracked files.

### Criterion 6 — Diverges Cleanly from Main

Fresh branch cut from `origin/main`. Cherry-pick of 183307c applied with zero conflicts (rename iris/voice.py → iris/voice/__init__.py + new iris/voice/pipecat_stt.py). `git merge-tree` shows no conflict markers.

### Criterion 7 — Single Feature Theme

Commits on branch vs origin/main:

```
fc4bb9a feat(voice): IrisSTTService + convert voice.py to voice/ package (ti-eq6d.1)
05cb310 tests(voice): IrisSTTService TDD suite (ti-eq6d.1.1)
```

Files changed: `iris/voice/__init__.py`, `iris/voice/pipecat_stt.py`, `iris/voice.py` (renamed), `tests/test_pipecat_stt.py` — all within the voice/ subsystem. One coherent theme: add IrisSTTService as the Pipecat STTService adapter.

**Note on TDD tests:** The TDD suite (test_pipecat_stt.py) was authored in commit 0394525 alongside tests for IrisTTSService and CallPipeline (not yet implemented). Only the IrisSTTService tests were included here; the IrisTTSService and CallPipeline tests are gated on their respective implementation beads (ti-eq6d.2, ti-eq6d.3) and will land with those PRs.
