# Release Gate: ti-dkhx — Fix default_stt/tts Environment-Sensitive Tests

**Bead:** ti-dkhx (needs-deploy)
**Source bead:** ti-y5s6 (bug)
**Review bead:** ti-41lc (PASS)
**Branch:** `fix/ti-y5s6-stt-test`
**Commit under review:** `fd54825`
**Gate evaluated:** 2026-06-22

---

## Gate Result: PASS

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | **PASS** | ti-41lc: "REVIEWER VERDICT: PASS (2026-06-22)" |
| 2 | Acceptance criteria met | **PASS** | Both required paths implemented: server-absent → FasterWhisperSTT, server-present → FasterWhisperServerSTT; TTS analogous fix correct; mocks context-scoped |
| 3 | Tests pass | **PASS** | 1104 passed, 4 skipped, 3 xpassed, 0 failures (8.97s) |
| 4 | No high-severity findings open | **PASS** | Zero HIGH findings; minor note on mixed patch/patch.object style accepted as non-blocking |
| 5 | Final branch is clean | **PASS** | `git status` clean; only untracked artifacts (.beads/, docs/plans/, tincan_iris.egg-info/) |
| 6 | Branch diverges cleanly from main | **PASS** | `git merge-tree` shows clean merge; no conflicts |
| 7 | Single feature theme | **PASS** | Tests-only change (test_stt.py, test_tts.py); fixes one bug class: environment-sensitive default_stt/tts factory tests |

---

## Evidence Detail

### Commit
```
fd54825 fix(tests): make default_stt/tts tests environment-independent (ti-y5s6)
  tests/test_stt.py  (+10 lines)
  tests/test_tts.py  (+5 lines)
```
No production code changed.

### Test run (gate)
```
1104 passed, 4 skipped, 3 xpassed, 2 warnings in 8.97s
```
The 3 xpassed are pre-existing in `tests/test_context.py`, unrelated to this diff.

### Review verdict (ti-41lc)
- Spec (ti-y5s6): both required paths implemented
- Patch targets correct: `iris.audio.stt.FasterWhisperServerSTT.available` (string-form) and `patch.object(KokoroServerTTS)` both hit the right method
- Mocks are context-scoped; no test pollution
- No security issues (test-only change)
