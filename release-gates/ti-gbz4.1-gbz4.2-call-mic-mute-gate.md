# Release Gate: ti-gbz4.1 + ti-gbz4.2 — Call Mic Mute + Far-Party Downlink Gate

**Bead:** ti-9dw9 (needs-deploy)
**Source review bead:** ti-scwa
**Branch:** `feature/ti-gbz4.1-gbz4.2-call-mic-mute`
**Commit (feature):** `64d39c8` (cherry-picked from `a1c9bc3`)
**Commit (tests):** `8159637`
**Gate evaluated:** 2026-06-22

---

## Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | **PASS** | ti-scwa notes: `REVIEW: pass` |
| 2 | Acceptance criteria met | **PASS** | See below |
| 3 | Tests pass | **PASS** | 1079 passed, 4 skipped, 3 xpassed; 2 pre-existing failures unrelated to this change |
| 4 | No high-severity findings open | **PASS** | ti-scwa has 1 LOW finding (mute-restore edge case, accepted) — 0 HIGH |
| 5 | Final branch is clean | **PASS** | `git status` shows only untracked non-source files |
| 6 | Branch diverges cleanly from main | **PASS** | Cherry-pick of `a1c9bc3` onto `origin/main` applied with no conflicts |
| 7 | Single feature theme | **PASS** | 2 commits: feature (app.py +19 lines) + tests (test_console_app.py +120 lines); both touch SCO/HFP call privacy in one subsystem |

**Overall gate: PASS**

---

## Acceptance Criteria (ti-gbz4.1 + ti-gbz4.2)

**ti-gbz4.1 — Default call mic to muted at HFP call start**

- [x] On `call_connected`, conductor is toggled to muted if not already muted
- [x] `_pre_call_muted` records the pre-call state before toggling
- [x] On `call_ended`, mic is restored: if conductor is muted and `_pre_call_muted=False`, unmute
- [x] Console shows yellow info line: "call connected — mic muted (press [m] to unmute / push-to-talk)"

**ti-gbz4.2 — Disable far-party transcription by default during SCO calls**

- [x] On `call_connected`, any active `_far_stream` is stopped and cleared
- [x] `_on_heard_far_main()` returns early (no dispatch) when `_in_call=True`
- [x] `action_far()` blocks when `_in_call=True`, logs warning, does not start a far stream
- [x] ADR-0002 compliance confirmed by reviewer: far-party speech cannot reach brain/address() during calls

---

## Test Results

```
python -m pytest tests/ -q (on feature/ti-gbz4.1-gbz4.2-call-mic-mute)

1079 passed, 4 skipped, 3 xpassed, 2 warnings
FAILED tests/test_tts.py::test_default_tts_uses_kokoro_when_available  (pre-existing on main)
FAILED tests/test_stt.py::test_default_stt_is_faster_whisper           (pre-existing on main)
```

Both failures exist on `origin/main` before this change; confirmed by running them against HEAD of main directly.

---

## Review Finding

**[LOW] ti-scwa** — mute restore edge case: if operator was muted pre-call then manually unmutes during the call, the restore gate leaves them unmuted. Primary paths are correct; edge case accepted by reviewer.

---

## Branch Composition

| Commit | Description |
|--------|-------------|
| `64d39c8` | feat(call): mute mic by default on SCO/HFP call connect + suppress far-party transcription (ti-gbz4.1, ti-gbz4.2) |
| `8159637` | tests(console_app): call mic mute + far-party downlink gate (ti-gbz4.1/.2) |
