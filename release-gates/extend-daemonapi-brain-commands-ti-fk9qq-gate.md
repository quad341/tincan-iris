# Release Gate: Extend DaemonAPI with turn/stream_turn/call_context

**Bead:** ti-fk9qq  
**Branch:** feat/brainhost-ti-s9mm.1.1  
**Commit:** bad0224  
**Date:** 2026-06-30  
**Deployer:** tincan-iris/deployer

---

## Gate Criteria

| # | Criterion | Result |
|---|-----------|--------|
| 1 | Review PASS present | ✅ PASS |
| 2 | Acceptance criteria met | ✅ PASS |
| 3 | Tests pass | ✅ PASS |
| 4 | No HIGH severity review findings open | ✅ PASS |
| 5 | Final branch is clean | ✅ PASS |
| 6 | Branch diverges cleanly from main | ✅ PASS |
| 7 | Single feature theme | ✅ PASS |

**Overall: PASS**

---

## Criterion 1 — Review PASS Present

Review bead: **ti-wdu23** (closed)  
Reviewer: tincan-iris/reviewer (gm-j1wg2)  
Verdict: **PASS** — 33/33 tests green, ruff clean, all 5 AC satisfied, no security issues.  
Date: 2026-06-30

---

## Criterion 2 — Acceptance Criteria

Source bead: ti-s9mm.2.1

- [x] **turn dispatches to BrainHost.async_turn, returns correct ack**  
  `_handle_turn()` in `iris/daemon/api.py:263–270` calls `self._brain_host.async_turn(text, speaker)` and writes the result. No-brain fallback returns `{"ack": "turn", "ok": False, "error": "no brain"}`.

- [x] **stream_turn produces brain_chunk events then brain_reply (via broadcast to all clients)**  
  `_handle_stream_turn()` (`api.py:272–280`) takes the same `async_turn` path; brain_chunk/brain_reply events are broadcast to all clients by BrainHost's event loop. Ack key is `"stream_turn"`.

- [x] **call_context returns contact_id, contact_name, in_call (bool)**  
  `_handle_call_context()` (`api.py:282–287`) calls `self._brain_host.call_context_snapshot()` which returns `{contact_id, contact_name, contact_number, in_call}` with `in_call` typed as bool (`brain_host.py:110–116`).

- [x] **DaemonAPI with brain_host=None still handles dnd/status/choose unchanged**  
  `__init__` now accepts `brain_host: BrainHost | None = None`; existing handlers (`_handle_choose`, `_handle_dnd`, `_handle_status`) are unchanged; only brain commands short-circuit with `ok=False` when `_brain_host is None`.

- [x] **ruff check passes**  
  `ruff check iris/daemon/api.py iris/daemon/brain_host.py` → All checks passed.

---

## Criterion 3 — Tests Pass

Command: `python -m pytest tests/ -x -q`

```
1557 passed, 3 xpassed, 2 warnings in 59.30s
```

Feature-specific:
- `tests/test_daemon_api_brain.py` — 8/8 passed
- `tests/test_daemon_api.py` — 16/16 passed  
- `tests/test_brain_host.py` — 9/9 passed (33/33 total feature tests)

Zero regressions in existing suite.

---

## Criterion 4 — No HIGH Severity Findings Open

Review findings:
- **LOW** (non-blocking): `_ctx` dict updated from D-Bus thread, read from socket-handler thread — no explicit lock. CPython GIL protects single `dict.update()` calls; worst case is a stale snapshot. Accepted as-is (matches existing pattern in the class).

No HIGH findings. ✅

---

## Criterion 5 — Final Branch Is Clean

`git status` on `feat/brainhost-ti-s9mm.1.1` (builder worktree):

```
nothing added to commit but untracked files present
```

Tracked files: clean. No uncommitted changes.

---

## Criterion 6 — Branch Diverges Cleanly from main

```
$ git merge-base --is-ancestor origin/main HEAD
→ exit 0 (branch is descendant of origin/main)
```

Diff from main: 4 commits, 851 insertions across `iris/daemon/api.py`, `iris/daemon/brain_host.py`, `tests/test_brain_host.py`, `tests/test_daemon_api_brain.py`. No conflicts.

---

## Criterion 7 — Single Feature Theme

All 4 commits on this branch belong to the ti-s9mm BrainHost+DaemonAPI feature arc:
- `bb581ca` — BrainHost class (ti-s9mm.1.1)
- `8af468b` — BrainHost tests (ti-s9mm.1.3)
- `2f7a99d` — DaemonAPI brain handler tests (ti-s9mm.2.2)
- `bad0224` — DaemonAPI turn/stream_turn/call_context (ti-s9mm.2.1)

Single subsystem (`iris/daemon`), single functional theme (always-on Brain lifetime + socket API). ✅
