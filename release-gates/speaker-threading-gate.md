# Release Gate: speaker-threading (ti-xvx / ti-ccc.2)

**Branch:** `feature/speaker-threading-ti-xvx`  
**Cherry-picked commit:** `22cd7e8c1af698f36584e8affe0357ef14642669`  
**Base:** `origin/main` @ `ec95796`  
**Gate evaluated:** 2026-06-15

## Result: PASS

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | **PASS** | `ti-7kn` notes: "REVIEW VERDICT: PASS (commit 22cd7e8)" |
| 2 | Acceptance criteria met | **PASS** | See checks below |
| 3 | Tests pass | **PASS** | 64 passed, 1 skipped (see below) |
| 4 | No high-severity findings open | **PASS** | One non-blocking structural gap (Textual async path untested); no HIGH findings |
| 5 | Final branch is clean | **PASS** | `git status` clean (untracked gc-internal dirs excluded) |
| 6 | Branch diverges cleanly from main | **PASS** | Cherry-pick applied with 0 conflicts (auto-merge of `app.py`); 1 commit ahead of `origin/main` |
| 7 | Single feature theme | **PASS** | One commit; one logical change: speaker field propagated STT→lanes→brain |

## Acceptance Criteria Verification (ti-ccc.2)

> `speaker(operator|far)` added to `LaneResult`/`Reply`; `brain.respond(speaker=)` receives + propagates it; unit tests both values.

- [x] `LaneResult.speaker: str = ""` — `iris/lanes.py:27`
- [x] `Reply.speaker: str = ""` — `iris/brain.py:21`
- [x] `brain.respond(text, *, speaker="")` — keyword-only param, propagated through all 6 reply paths (`iris/brain.py:69,80,83,89,95,98`)
- [x] `Conductor.respond_to(text, *, speaker="")` — threads to `brain.respond(speaker=speaker)` (`conductor.py:81,90`)
- [x] Console extracts `ev[2]` from heard events → `_on_heard_main` / `_on_heard_far_main` → `_dispatch(cmd, speaker)` → `conductor.respond_to(speaker=s)` (`app.py:110,112,127,131`)
- [x] `test_respond_to_threads_speaker_operator` / `_far` — verify speaker keyword reaches `brain.respond()` (`tests/test_conductor.py`)

## Merge ordering note

This commit (`22cd7e8`) was built on top of `84836d9` (ti-ccc.1 / stt-source-label, PR #26). Cherry-pick onto `origin/main` is clean because `app.py` carries a `len(ev) > 2` backward-compat guard (routes empty speaker when events are 2-tuples, i.e., before ti-ccc.1 is merged). Full speaker propagation requires PR #26 to be merged first. **Recommended merge order: PR #26 → this PR.**

## Test Run

```
$ python -m pytest tests/ -x --tb=short -q
................................................................  [100%]
64 passed, 1 skipped in 1.23s
```

Note: reviewer observed 65 passed on `iris/tincan-sco` (which includes the `84836d9` streaming tests from ti-ccc.1). On this standalone cherry-pick onto main, 64 is the correct count.

## Review Findings Summary

| Severity | Finding | Resolution |
|----------|---------|-----------|
| Non-blocking | `_on_heard_main` console path untested (requires Textual async runtime) | Structural gap, acknowledged by reviewer; criterion (c) applies |

No HIGH findings open.
