# Release Gate: IrisTTSService Pipecat wrapper (ti-q0f1j)

**Date:** 2026-06-27
**Bead:** ti-q0f1j (deploy) / ti-urd7f (review) / source commit: 989d8a3
**Branch:** feat/iris-tts-service-ti-q0f1j (cut from origin/main @ 60454d3)
**Deployer:** tincan-iris/deployer

---

## Criteria Evaluation

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | **PASS** | Review bead ti-urd7f — verdict: PASS |
| 2 | Acceptance criteria met | **PASS** | All 8 criteria verified in iris/voice/pipecat_tts.py — see below |
| 3 | Tests pass | **PASS** | 1300 passed, 13 skipped, 3 xpassed, 2 warnings — zero failures |
| 4 | No high-severity review findings | **PASS** | No HIGH or CRITICAL findings; two LOW non-blocking observations (see review bead) |
| 5 | Final branch is clean | **PASS** | `git status` clean — only untracked non-project files (.gc/, stale gate files) |
| 6 | Branch diverges cleanly from main | **PASS** | Fresh branch cut from origin/main; both commits cherry-picked without conflict |
| 7 | Single feature theme | **PASS** | 2 commits: IrisTTSService TDD suite + implementation — single Pipecat TTS wrapper theme |

**Overall: PASS**

---

## Evidence

### Criterion 1 — Review PASS

Review bead **ti-urd7f** (closed, PASS):

> Review verdict: PASS
> Reviewer: tincan-iris/reviewer
> Commit: 989d8a3 on fix/test-fixes-ti-gxpt1.3-et9i

Style: ruff clean. Correctness: run_in_executor, WAV header, voice/speed assignment, finally cleanup, chunk framing, import guard — all verified against tests. No HIGH or CRITICAL findings. Two low non-blocking observations (TTSStoppedFrame outside try on error path; voice/speed race on concurrent calls — both acceptable per Pipecat design).

### Criterion 2 — Acceptance Criteria

Verified directly in `iris/voice/pipecat_tts.py` (commit `dbb42a9`):

| Criterion | Location | Result |
|-----------|----------|--------|
| `IrisTTSService(tts, voice, speed)` | line 29 | ✅ |
| Sets `tts.voice`/`tts.speed` before `synth()` | lines 38-39 | ✅ |
| `run_in_executor` — non-blocking | line 43 | ✅ |
| WAV header `sample_rate` (not hard-coded) | lines 47-48 | ✅ |
| 20 ms chunks | line 49 (`_CHUNK_MS = 20`) | ✅ |
| `finally` cleanup of temp WAV | line 60 | ✅ |
| `TTSStartedFrame` / `AudioRawFrame+` / `TTSStoppedFrame` | lines 41, 54-58, 62 | ✅ |
| `ImportError` naming `pipecat` when pipecat-ai absent | lines 12-16 | ✅ |

### Criterion 3 — Tests Pass

```
python -m pytest tests/ -q
1300 passed, 13 skipped, 3 xpassed, 2 warnings in 28.17s
```

IrisTTSService TDD suite (6 tests):

```
tests/test_pipecat_tts.py::test_run_tts_emits_at_least_one_audio_frame PASSED
tests/test_pipecat_tts.py::test_sample_rate_matches_wav_header PASSED
tests/test_pipecat_tts.py::test_run_tts_does_not_block_event_loop PASSED
tests/test_pipecat_tts.py::test_voice_and_speed_forwarded_to_tts PASSED
tests/test_pipecat_tts.py::test_temp_wav_cleaned_up_after_frames_yielded PASSED
tests/test_pipecat_tts.py::test_import_error_without_pipecat PASSED

6 passed in 0.08s
```

### Criterion 4 — No High-Severity Findings

Review bead ti-urd7f: "Findings: None — no blockers." Two LOW observations noted (non-blocking). No HIGH or CRITICAL findings.

### Criterion 5 — Branch Clean

`git status` output on branch `feat/iris-tts-service-ti-q0f1j`:
```
On branch feat/iris-tts-service-ti-q0f1j
Your branch is ahead of 'origin/main' by 2 commits.
  (use "git push" to publish your local commits)

Untracked files: .gc/, .gitkeep, release-gates/ (stale gate files from prior sessions)

nothing added to commit but untracked files present
```

### Criterion 6 — Clean Divergence from Main

Branch cut fresh from `origin/main` @ `60454d3`. Two cherry-picks applied without conflict:
- `dc0bbd9` — `tests/test_pipecat_tts.py` (extracted from builder commit 0394525)
- `dbb42a9` — `iris/voice/pipecat_tts.py` (cherry-pick of 989d8a3)

**Note on source branch:** `fix/test-fixes-ti-gxpt1.3-et9i` has 7 conflicts with origin/main (tracked in prior gate attempts for ti-es9us / ti-xsgx3). The IrisTTSService commits are self-contained and cherry-pick cleanly onto a fresh branch.

### Criterion 7 — Single Feature Theme

2 commits touching 2 files in the `iris/voice/` subsystem:
- `tests/test_pipecat_tts.py` — TDD suite for IrisTTSService
- `iris/voice/pipecat_tts.py` — IrisTTSService implementation

Single theme: Pipecat TTS service wrapper. No other subsystems touched.
