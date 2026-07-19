# Release Gate: priorcommitmentcard-widget-ti-w0dvp

**Bead:** ti-vp8yr — needs-deploy: PriorCommitmentCard widget + commitment resolution (from:ti-w0dvp)  
**Source bead:** ti-w0dvp — Call Card AFTER: PriorCommitmentCard widget + commitment resolution (ti-lvsnh) (CLOSED)  
**Review beads:** ti-ta4ly (round 1, REQUEST-CHANGES), ti-g5asm (round 2, PASS)  
**Branch:** `builder/ti-w0dvp`  
**Gate commit:** `eecdfed8d8ff35fbace8968b3dec83a596198c39`  
**Date:** 2026-07-19

## Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 6 | Branch diverges cleanly from main | **PASS** | Merge-base(HEAD, origin/main) == origin/main tip (`9459d68`); `git merge-tree --write-tree origin/main HEAD` clean, no conflicts. Branch already rebased — no self-rebase needed. |
| 1 | Review PASS present | **PASS** | ti-g5asm closed reason=pass; notes: round-1 blocking finding resolved and independently re-verified round 2 |
| 2 | Acceptance criteria met | **PASS** | Verified directly against `iris/console/call_card.py:733-867`: `can_focus=True`, `aria_role="article"`, `:focus` CSS (`#a5b4fc`, heavy); `-broken`/`-open` CSS classes (`#f87171`/`#818cf8`); icon+word pairing (⚠ BROKEN COMMITMENT / ⏳ OPEN COMMITMENT); `[H]`/`[B]` → `action_honor`/`action_break` → `AfterStore.resolve_commitment(id, "honored"/"broken")` with `_resolved` double-fire guard; `AfterStore` instantiated directly by caller (no new DaemonAPI command) |
| 3 | Tests pass | **PASS\*** | `tests/test_prior_commitment_card.py` + `tests/test_call_card_markup_escape.py`: 54/54 pass. Full suite: 1896 passed, 3 xpassed, 1 failed (pre-existing, see below) |
| 4 | No high-severity findings open | **PASS** | Round-1 HIGH finding (raw `rich.markup.escape()` dropping bracket-shaped text, e.g. `[20% off]`) fixed at all 4 call sites in `render()` — confirmed via grep: zero remaining `rich.markup` usage in the file, all 4 sites now call `escape_for_content()` |
| 5 | Final branch is clean | **PASS** | `git status` clean (only pre-existing untracked `.gc/`/`.gitkeep` worktree scaffolding, not part of this branch's diff) |
| 7 | Single feature theme | **PASS** | Diff confined to `iris/console/call_card.py` (+143) and `tests/test_prior_commitment_card.py` (+352), purely additive, one widget (PriorCommitmentCard), single subsystem (`iris/console/`) |

\* One pre-existing, unrelated test failure:
- `tests/test_daemon_call_card_config.py::test_main_passes_loaded_config_to_call_card_host` — fails with `iris daemon: another instance holds the lock (pid 2353) — exiting`. Independently confirmed environmental: `ps aux` shows a live `/usr/bin/python3.14 -m iris.daemon` process at pid 2353 running since Jul13 in this shared dev environment, matching the PID in the failure output exactly. Same test failed under a different PID (689129, then 2353) in both prior review rounds — pid-lock contention, not a regression from this diff.

## Verdict: PASS

## Commits on branch (vs origin/main)

| SHA | Message |
|-----|---------|
| `a8c61fe` | test(feat): red — Call Card AFTER: PriorCommitmentCard widget + commitment resolution (refs ti-w0dvp) |
| `9283698` | feat: green — Call Card AFTER: PriorCommitmentCard widget + commitment resolution (ti-lvsnh) (refs ti-w0dvp) |
| `eecdfed` | fix(console): use escape_for_content in PriorCommitmentCard (ti-w0dvp) |

## Review summary

**Round 1 (ti-ta4ly):** REQUEST-CHANGES. One HIGH finding: `PriorCommitmentCard.render()` used raw `rich.markup.escape()` instead of the file's hardened `escape_for_content()` helper, silently dropping bracket-shaped commitment text (e.g. "[20% off]") via Textual's `Content.from_markup` tokenizer — the same bug class this file has needed five prior dedicated fixes for. All other acceptance criteria verified clean in round 1 (styling, focus/aria, `[H]`/`[B]` wiring, `AfterStore` direct instantiation, scope).

**Round 2 (ti-g5asm):** PASS. Fix replaced all 4 call sites with `escape_for_content()`, removed the stale import, added 4 regression tests. Independently re-verified (not just trusted bead notes): confirmed zero remaining raw-escape usage, empirically reproduced old-vs-new escaping behavior on all 4 new test strings via `Content.from_markup`, ran tests in an isolated worktree, confirmed ruff-clean and merge-tree-clean.

**Deployer gate (this pass):** Re-ran the targeted and full test suites myself in this worktree, re-verified the escape-site grep, read the widget implementation directly against all five stated acceptance criteria, and independently confirmed the one remaining test failure is the same live-daemon pid-lock environmental issue documented in both review rounds (matching live process pid 2353).

## Downstream unblock

Six `needs-deploy` beads on `feat/callcard-after-data-layer-ti-hb2dx` (ti-83qp9, ti-xr8j5, ti-z4e1g, ti-l9qo8, ti-0xwj3, ti-zd5os) unconditionally import `PriorCommitmentCard` and were blocked pending this landing on `origin/main`. They should be able to proceed once this PR merges.
