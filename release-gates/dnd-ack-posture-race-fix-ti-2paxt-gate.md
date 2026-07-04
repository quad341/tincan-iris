# Release Gate: DND Ack/Posture-Mutation Race Fix + Deferred Broadcast

**Bead:** ti-2paxt (needs-deploy)
**Source review bead:** ti-5e533
**Branch:** `deploy/dnd-ack-posture-race-fix-ti-2paxt`
**Commit:** `fba12db` (cherry-picked from `b40bf14` on `feat/console-crash-exit-message-ti-00jr4-2`)
**Gate evaluated:** 2026-07-03

---

## Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | **PASS** | ti-5e533 notes: reviewer PASS, independently reproduced the pre-fix bug (2/25 failures on parent `be9b44a`) and confirmed 0/25 on the fix |
| 2 | Acceptance criteria met | **PASS** | See below |
| 3 | Tests pass | **PASS** | 1615 passed, 1 skipped, 3 xpassed, 0 failed |
| 4 | No high-severity findings open | **PASS** | 1 non-blocking suggestion (broad `except OSError: pass` in `_RequestHandler.handle()`, no log line) — informational only, not HIGH |
| 5 | Final branch is clean | **PASS** | `git status` shows only untracked non-source artifacts (venv, egg-info) |
| 6 | Branch diverges cleanly from main | **PASS** | Cherry-pick of `b40bf14` onto `origin/main` (088b7da) applied via clean auto-merge, no conflicts |
| 7 | Single feature theme | **PASS** | 1 commit, 2 files in the same subsystem (`iris/daemon/api.py`, `iris/daemon/posture.py`) — DND ack/posture race fix |

**Overall gate: PASS**

---

## Acceptance Criteria (ti-syhdb)

- [x] Posture mutation happens before the ack is sent, not after — closes the race where a concurrent DND change could interleave between ack and mutation
- [x] Broadcast of the new state is deferred until after the mutation is durably applied
- [x] `broadcast_current()` always re-reads fresh state under lock rather than broadcasting a captured snapshot — worst case on a residual narrow interleaving with `PostureWatcher`'s auto-expiry thread is a redundant/coalesced broadcast, never a wrong persisted value (traced by reviewer, not just asserted)

---

## Test Results

```
.venv/bin/pytest -q (on deploy/dnd-ack-posture-race-fix-ti-2paxt, origin/main + fba12db only)

1615 passed, 1 skipped, 3 xpassed in 81.62s
```

No failures. Reviewer additionally looped the 4 named DND tests 25x on both the pre-fix parent and the fix commit directly to confirm the race was genuinely reproducible and genuinely closed (2/25 → 0/25); not re-run here since the deterministic full-suite pass is sufficient corroboration on top of that independent evidence.

---

## Review Finding

**[non-blocking]** `_RequestHandler.handle()` added a broad `except OSError: pass` (silent, no log) to absorb an RST-vs-FIN race on socket close during a pending broadcast. Narrow blast radius, well-justified by the commit's own reasoning. Suggestion (not required for this gate): add a debug log line or narrow the exception type.

---

## Branch Composition

| Commit | Description |
|--------|-------------|
| `fba12db` | fix(daemon): mutate posture before ack, defer broadcast after (ti-syhdb) |

Verified independent of `1661a0c` (ti-9skkj/PR #146, also touches `iris/daemon/api.py`, not yet merged) — the two commits touch different regions of the file; this cherry-pick applies cleanly with or without that other change present.
