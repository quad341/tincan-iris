# Release Gate: MessageEventSource ANCS/MAP D-Bus wiring (ti-9js11)

**Bead:** ti-9js11  
**Source bead:** ti-hg6rl (review)  
**Branch:** `feat/call-card-deps-ti-rnlqo-2-2`  
**Commit:** `8b681c8`  
**Gate result:** ❌ FAIL  
**Gate run:** 2026-06-30 by deployer  

---

## Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | ✅ PASS | ti-hg6rl closed `close_reason=pass`; PASS verdict in notes |
| 2 | Acceptance criteria met | ✅ PASS | 11/11 ti-s9mm.4.3 validator tests pass (per review); security invariant (body never → Brain), ProactiveStore kwargs correct, engine wiring correct — all confirmed by reviewer |
| 3 | Tests pass | ✅ PASS | Committed suite: 1430 passed, 32 skipped, 0 failed on `8b681c8`. Untracked test files (`test_capture_store.py`, `test_call_card_pure.py`) not part of this commit — not evaluated. |
| 4 | No high-severity findings open | ❌ **FAIL** | HIGH advisory in ti-hg6rl: `NotesStore(db_path)` passes SQLite roster.db path to a JSON store — corrupts roster.db on first note capture. Fix tracked at P1 in **ti-nf1r9** (status: in_progress). Branch MUST NOT merge before ti-nf1r9 closes. |
| 5 | Final branch clean | ✅ PASS | Builder worktree is clean (untracked test files only; no staged/unstaged diffs to committed content) |
| 6 | Diverges cleanly from main | ✅ PASS | Not verified by push attempt; no apparent conflict vectors from diff scan |
| 7 | Single feature theme | ✅ PASS | MessageEventSource ANCS/MAP D-Bus → ProactiveStore → broadcast. One subsystem, one author, coherent scope. |

---

## FAIL details — criterion #4

**File:** `iris/daemon/__main__.py`, line 85  
**Bug:** `notes = NotesStore(db_path)` — `db_path` is `~/.local/share/iris/roster.db` (SQLite binary). `NotesStore` is a JSON file store (`_DEFAULT_PATH = notes.json`). SQLite binary fails `json.loads()` silently on read; first `_save()` overwrites roster.db with JSON, corrupting contacts, posture, and BRAIN_CONTEXT.  
**Fix (one line):** `notes = NotesStore()` — no-arg uses `~/.local/share/iris/notes.json`.  
**Tracking:** ti-nf1r9 (P1, in_progress, owner: reviewer-gm-5md0l)  
**Introduced by:** commit `8b681c8` (this commit — the MessageEventSource wiring added the `NotesStore` import and construction)

**Reviewer verdict from ti-hg6rl:**
> ADVISORY [HIGH] iris/daemon/__main__.py — NotesStore(db_path) perpetuates ti-hvh8z blocker. THIS BRANCH MUST NOT MERGE TO MAIN BEFORE ti-nf1r9 RESOLVES.

---

## Action required

1. Apply one-line fix: `notes = NotesStore()` at `iris/daemon/__main__.py:85`
2. Confirm ti-nf1r9 is closed (or close it with the fix applied here)
3. Re-submit to deployer

**Do not open or merge a PR for this branch until the fix is in and ti-nf1r9 is closed.**
