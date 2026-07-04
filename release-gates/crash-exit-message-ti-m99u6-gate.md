# Release Gate: crash-exit-message-ti-m99u6

**Bead:** ti-m99u6 — needs-deploy: crash-exit stderr message (from:ti-vg1q9)
**Source bead:** ti-vg1q9 (review bead, CLOSED/PASS)
**Feature bead:** ti-00jr4.2
**Branch:** `deploy/crash-exit-message-ti-m99u6`
**Gate commit:** (this commit)
**Date:** 2026-07-04

## Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | **PASS** | ti-vg1q9 closed with reviewer PASS verdict; independently re-verified against installed Textual 8.2.7 source (see ti-vg1q9 notes) |
| 2 | Acceptance criteria met | **PASS** | ti-00jr4.2 AC checked verbatim by reviewer: stderr block printed strictly after Textual's own traceback dump, correct wording/column alignment, bug-report line omitted when write failed, gated strictly on truthy `return_code` |
| 3 | Tests pass | **PASS** | 1703 passed, 3 xpassed, 0 failed (full suite, this branch) |
| 4 | No high-severity findings open | **PASS** | One LOW/informational finding (unguarded concurrent global for most-recent bug-report path) — accepted, same pattern as existing `_active_app` |
| 5 | Final branch is clean | **PASS** | `git status` clean; only untracked `.gc/`/`.gitkeep`/`tincan_iris.egg-info` artifacts (pre-existing worktree state, not part of this change) |
| 6 | Branch diverges cleanly from main | **PASS** | Built fresh off `origin/main` (post PR #142 merge); cherry-picked `418f24f` clean; cherry-picked test commit `6fbe0ff` hit one structural conflict in `tests/test_console_app.py` (two independent, non-overlapping test blocks from PR #141 and this feature both appending at the same anchor line — no contested logic); resolved by keeping both blocks, confirmed correct by the full green test run above |
| 7 | Single feature theme | **PASS** | Both commits implement one feature (crash-exit stderr message, ti-00jr4.2); touches `iris/console/app.py` + `iris/console/diagnostics.py` + their tests only |

## Verdict: PASS

## Commits on branch (vs origin/main)

| SHA | Message |
|-----|---------|
| `b321f43` | feat(console): print crash-exit stderr message after traceback (ti-00jr4.2) |
| `d9bc378` | tests(console): crash-exit stderr message decision logic (ti-00jr4.2) |

## Review summary (ti-vg1q9)

**Correctness:** `main()` prints the block after Textual's own `_print_error_renderables()`/terminal restore, verified directly against installed Textual 8.2.7 source, not assumed.
**Signal integrity:** `return_code` traced across every `self.exit()`/`return_code` use site — confirmed a false-positive-free crash signal ([q] quit resolves to Textual's default 0; only Textual's own `_handle_exception` sets 1).
**Findings:** 1 LOW (unguarded concurrent global for the most-recent bug-report path — informational, matches an already-accepted pattern elsewhere in the module).
**Test coverage:** `tests/test_console_app.py` (`_crash_exit_message` text variants, `main()` gating) + `tests/test_diagnostics.py` (public accessor tests) — both present and passing.

## Deploy sequencing note

This bead was held for ~12 hours across many deployer re-checks waiting on PR #142 (`feat/console-diagnostics-ti-oqlyk`) to merge, since `418f24f` stacks directly on that PR's tip. PR #142 merged 2026-07-04T14:37:03Z. This deploy was built by pinning the exact prerequisite SHAs (`418f24f` + `6fbe0ff`) onto a fresh branch off the post-merge `origin/main`, per the bead's own explicit action plan — not by checking out the shared multi-bead branch `feat/console-crash-exit-message-ti-00jr4-2` wholesale, which also carries several other not-yet-gated commits (ti-03yy3, ti-ym0ku, ti-4sy3b, and unrelated daemon/docs work).
