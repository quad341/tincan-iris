# Release Gate: FarEndIdentity state machine + memory archival gating

**Bead:** ti-btj3  
**Source bead (build+review):** ti-6v2m / ti-nr3m.3  
**Branch:** release/farend-identity-ti-btj3 (cherry-pick off origin/main)  
**Base commit (origin/main):** 0487065  
**Cherry-picked commits (in order):**
- `9de5f4c` ← `34664d1` feat(memory): FarEndIdentity state machine + rebind_session + archival gating (ti-nr3m.3)
- `7d20ba0` ← `2b3ec38` fix(far_end): remove unused field import (ti-6v2m F-STYLE-01)
- `7a2254d` ← `b06c39a` test: FarEndIdentity + rebind_session + sentinel gating coverage (ti-fzhp)

**Date:** 2026-06-18  
**Note:** Full sprint branch (`feature/ti-qxel-6qsb-sprint`) not used — ti-4lzj (server providers/doctor/watcher/HomeApp) has HIGH finding open. FarEndIdentity cherry-picked to a clean branch per reviewer instruction.

---

## Gate Checklist

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | ✅ PASS | ti-6v2m notes: "PASS — deploy bead ti-btj3 created (b06c39a, feature/ti-qxel-6qsb-sprint). F-STYLE-01 fixed (2b3ec38), F-COV-01/02/03 tests added (b06c39a), F-SEC-01 deferred to ti-nr3m.6 by design. Full suite: 913 passed." First-pass (claude) reviewer. Second-pass (gemini) disabled per rig policy. |
| 2 | Acceptance criteria met | ✅ PASS | See detail below. |
| 3 | Tests pass | ✅ PASS | 653 passed, 3 skipped, 3 xpassed in 7.10s. 101/101 far_end + memory tests pass. |
| 4 | No high-severity findings open | ✅ PASS | F-STYLE-01 (unused import) fixed in 2b3ec38. F-COV-01/02/03 (coverage) resolved by b06c39a. F-SEC-01 (privacy ordering constraint) deferred to ti-nr3m.6 by design — not a deploy blocker. No HIGH findings. |
| 5 | Final branch is clean | ✅ PASS | `git status` clean on cherry-pick branch. Only untracked items are `.gc/` and prior gate files. |
| 6 | Branch diverges cleanly from main | ✅ PASS | 3 clean cherry-picks onto origin/main (0487065). No conflicts. |
| 7 | Single feature theme | ✅ PASS | FarEndIdentity in-process state machine + memory archival gating. Single subsystem: `iris/far_end.py` (new) + `iris/memory.py` (rebind_session UPSERT, call_start far_end= kwarg, _archive sentinel gating). |

**Overall: PASS**

---

## Acceptance Criteria

| Criterion | Verdict | Evidence |
|-----------|---------|----------|
| `iris/far_end.py` new (3-state FSM) | ✅ | Created at 9de5f4c. 57 lines. UNIDENTIFIED / IDENTIFIED / PRIVATE states. |
| `FarEndState` enum | ✅ | `FarEndState.UNIDENTIFIED`, `IDENTIFIED`, `PRIVATE` |
| `SENTINEL_ID = 0` | ✅ | `SENTINEL_ID = 0` at module level. SQLite AUTOINCREMENT starts at 1, so 0 is permanently free. |
| `FarEndIdentity` frozen dataclass | ✅ | `@dataclass(frozen=True)` with immutable `bind(contact_id, display_name)` and `make_private()` transitions. Private state is terminal (all transitions are no-ops once private). |
| `archival_contact_id` property | ✅ | Returns `str(contact_id)` for IDENTIFIED, `None` for UNIDENTIFIED and PRIVATE. |
| `rebind_session` UPSERT in memory.py | ✅ | `MemoryManager.rebind_session(session_id, contact_id)` present. |
| `call_start` `far_end=` kwarg (backward compat) | ✅ | `call_start(session_id, contact_id='', ..., *, far_end: 'FarEndIdentity | None' = None)` — optional kwarg, defaults to None. |
| `_archive` sentinel gating + `end_session` on skip | ✅ | Archival uses `far_end.archival_contact_id`; PRIVATE/UNIDENTIFIED returns None → skip archival + call `end_session`. |
| F-STYLE-01 unused import removed | ✅ | Commit 2b3ec38 removes unused `field` import from `iris/far_end.py`. |
| 101 coverage tests | ✅ | `python -m pytest tests/test_far_end.py tests/test_memory.py -q` → 101 passed. |

---

## Test Run Detail

```
python -m pytest -q tests/  (release/farend-identity-ti-btj3)
653 passed, 3 skipped, 3 xpassed, 2 warnings in 7.10s

python -m pytest tests/test_far_end.py tests/test_memory.py -q
101 passed in 2.82s
```

Reviewer ran 913 on a fuller branch (includes email/roster + IrisMode); lower count here reflects origin/main + this bead only.

---

## F-SEC-01 Deferred Finding

F-SEC-01: Privacy ordering constraint — calling `make_private()` after the far end has been archived could leave a stale archival reference. By design, `FarEndIdentity` is in-process only and does not enforce cross-call ordering; this is deferred to ti-nr3m.6 where the archival pipeline will add an explicit guard. Not a blocker for this deploy.
