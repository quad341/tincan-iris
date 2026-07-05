# Release Gate: callcard-focus-edit-wiring-ti-5a8ke

**Bead:** ti-5a8ke — Deploy: Call Card focus/edit/store-wiring (ti-3mpyc)
**Source bead:** ti-3mpyc (implementation, CLOSED)
**Review bead:** ti-6xlis (CLOSED/PASS)
**Branch:** `fix/callcard-focus-edit-wiring-ti-5a8ke`
**Gate commit:** (this commit)
**Date:** 2026-07-05

## Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | **PASS** | ti-6xlis closed with reviewer PASS verdict (reviewer-gm-wisp-anw8hc, 2026-07-05): style clean (ruff), spec compliance, coverage check, security follow-up all recorded |
| 2 | Acceptance criteria met | **PASS** | Independently re-verified against the diff, not just trusting the review: (1) `can_focus = True` on `_FactBaseCard` (covers CriticalFactCard+FactCard) and `ActionItemCard`, `:focus` CSS on all three (`#fbbf24`/`#2dd4bf`/`#a5b4fc` respectively) — matches spec exactly. (2) All 5 handlers (`on_fact_confirmed`/`on_fact_dismissed`/`on_fact_value_override`/`on_action_item_confirmed`/`on_action_item_edited`) added to `IrisConsole`, calling `CallCardStore.confirm_fact()`/`confirm_action_item()` — signatures independently confirmed at `iris/capture/store.py:218` and `:256`. (3) `FactCard` gains inline edit mode (`__init__`, `on_key` editing branch, `_commit_edit`) mirroring `CriticalFactCard`'s shape, posts `FactValueOverride`. New-logic regression tests are deferred to ti-e7sfx (filed, OPEN, routed to validator) — reviewer's COVERAGE CHECK explicitly accepted this as non-blocking per this rig's standing convention |
| 3 | Tests pass | **PASS** | 1751 passed, 3 xpassed, 1 failed (full suite, re-run independently on this branch). The 1 failure (`test_daemon_call_card_config.py::test_main_passes_loaded_config_to_call_card_host`) is the same pre-existing environmental failure the builder and reviewer already identified: error log shows `iris daemon: another instance holds the lock (pid 689129)` — a live daemon process on this shared machine. Zero overlap between this diff's files (`iris/console/app.py`, `iris/console/call_card.py`) and the failing test's module (`iris/daemon/__main__.py`) |
| 4 | No high-severity findings open | **PASS** | One P3/non-blocking finding from review: ti-z1utm (pre-existing Rich-markup-escaping gap in `call_card.py` render() sinks, extended by this diff's new FactCard edit branch following the same pre-existing pattern by explicit instruction to mirror CriticalFactCard exactly). Reviewer explicitly assessed this as systemic/pre-existing, not introduced by this bead, and non-blocking. ti-z1utm has since been fixed independently on the builder's branch (commit `444f886`) — that fix is a separate bead/commit not reviewed under ti-6xlis and is correctly excluded from this deploy; it will ship under its own review/deploy cycle |
| 5 | Final branch is clean | **PASS** | `git status` clean on tracked files. This shared worktree directory carries a large number of untracked directories from unrelated concurrent bead sessions (other roles' nested worktrees, stray scratch dirs) — none are part of this branch or this change |
| 6 | Branch diverges cleanly from main | **PASS** | Built off current `origin/main` tip; exactly 1 commit ahead, 0 behind (`git log origin/main..HEAD` / `git log HEAD..origin/main`); no conflicts |
| 7 | Single feature theme | **PASS** | One commit, two files (`iris/console/app.py`, `iris/console/call_card.py`), single theme: Call Card card keyboard-focus reachability + message-to-store wiring + FactCard edit mode, per ti-3mpyc |

## Verdict: PASS

## Commit on branch (vs origin/main)

| SHA | Message |
|-----|---------|
| `de7b599` | fix(console): Call Card focus reachability + store wiring + FactCard edit (ti-3mpyc) |

This commit is a faithful, content-verified copy of the builder's originally-reviewed commit (`8058275` on `feat/callcard-after-data-layer-ti-hb2dx`, since diverged with unrelated follow-on work) — recreated onto a clean branch off `origin/main` rather than pulling the shared builder branch wholesale, which now carries additional not-yet-gated commits.

## Review summary (ti-6xlis)

**Correctness:** all 4 acceptance criteria verified directly against the diff and against `iris/capture/store.py`'s actual method signatures.
**Coverage:** ti-e7sfx (new-logic regression tests) filed and routed to validator, non-blocking per this rig's standing convention for deploy-time coverage gaps.
**Security:** ti-z1utm (pre-existing markup-escaping gap, extended not introduced by this diff) filed separately, non-blocking, since independently fixed on an unrelated later commit.
