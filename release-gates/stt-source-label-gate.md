# Release Gate: stt-source-label (ti-nt6 / ti-ccc.1)

**Branch:** `feature/stt-source-label-ti-nt6`  
**Cherry-picked commit:** `84836d989917e1c45c64e2e0e78f74e90eaa7ecf`  
**Base:** `origin/main` @ `ec95796`  
**Gate evaluated:** 2026-06-15

## Result: PASS

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | **PASS** | `ti-gmf` notes: "REVIEW VERDICT: PASS" (first-pass reviewer, second-pass disabled) |
| 2 | Acceptance criteria met | **PASS** | See checks below |
| 3 | Tests pass | **PASS** | 63 passed, 1 skipped (see below) |
| 4 | No high-severity findings open | **PASS** | One non-blocking observation (dead code len guard); no HIGH findings |
| 5 | Final branch is clean | **PASS** | `git status` clean (untracked gc-internal dirs excluded) |
| 6 | Branch diverges cleanly from main | **PASS** | Cherry-pick applied with 0 conflicts; 1 commit ahead of `origin/main` |
| 7 | Single feature theme | **PASS** | One commit; one subsystem (STT stream tagging); touches `streaming.py`, `app.py`, `test_streaming.py` |

## Acceptance Criteria Verification (ti-ccc.1)

> Both streams transcribed independently with a source label + a test proving two tagged streams.

- [x] `StreamingTranscriber` gains `label: str = ""` constructor param (`iris/audio/streaming.py:36`)
- [x] `on_text` callback signature changed to `(text, label)` — emits `self.label` per utterance (`streaming.py:110`)
- [x] Console creates operator stream with `label="operator"` (`app.py:200`)
- [x] Console creates far-end stream with `label="far"` (`app.py:219`)
- [x] All call sites updated atomically (reviewer confirmed)
- [x] `test_read_loop_dispatches_text_and_label_and_sets_ready` — verifies label flows through (`test_streaming.py:51`)
- [x] `test_read_loop_two_tagged_streams` — exercises simultaneous op/far streams with independent routing (`test_streaming.py:65`)

## Test Run

```
$ python -m pytest tests/ -x --tb=short -q
...............................................................  [100%]
63 passed, 1 skipped in 1.29s
```

Note: reviewer observed 65 passed on the full `iris/tincan-sco` branch (which also carries the subsequent `ti-ccc.2` commit adding `test_conductor.py` cases). On this cherry-picked branch (ti-ccc.1 only), 63 is the correct expected count.

## Review Findings Summary

| Severity | Finding | Resolution |
|----------|---------|-----------|
| Non-blocking | `len(ev) > 2` backward-compat guard in `app.py:110-112` is dead code (always 3-tuples now) | Not a blocker; tracked for cleanup at leisure |

No HIGH findings open.
