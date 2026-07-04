# Release Gate: help-screen-ti-00jr4-1

**Bead:** ti-jcetz — needs-deploy: [?] help screen, always-visible binding + startup hint (from:ti-04dqq)
**Feature Branch:** deploy/ti-jcetz (cherry-pick of commit 2776212, originally on gc-builder-dd400ec40fa5)
**Reviewed Commit:** 2776212 (byte-identical duplicate also present as d1397d9 on gc-validator-abfaf8e96d0d; both share parent a6192f1). Neither persistent branch tip was pushed as-is, since a6192f1 is not an ancestor of origin/main (main advanced past it) — the commit was cherry-picked directly onto a fresh branch off origin/main instead, per the reviewer's explicit note in the bead.
**Deploy Commit:** 689102f (cherry-pick of 2776212 onto origin/main@088b7da)
**Gate Date:** 2026-07-03

## Gate Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | **PASS** | ti-04dqq: Review verdict PASS — tincan-iris/reviewer; full AC-by-AC verification, no blocking findings |
| 2 | Acceptance criteria met | **PASS** | All 6 ACs from ti-00jr4.1 verified against the diff by the reviewer (see table below) |
| 3 | Tests pass | **PASS** | 1616 passed, 3 xpassed, 2 warnings, 0 failures (71.02s) — full suite run by deployer on deploy/ti-jcetz |
| 4 | No high-severity findings open | **PASS** | Reviewer found zero blocking findings. Only accepted/tracked items: footer 80-col truncation (pre-existing, tracked separately as ti-ffch2, already closed/decomposed) and quit-gate test coverage (tracked ti-00jr4.4, already closed on its own sibling branch) |
| 5 | Final branch is clean | **PASS** | `git status` clean on deploy/ti-jcetz after cherry-pick |
| 6 | Branch diverges cleanly from main | **PASS** | Cherry-pick of 2776212 onto origin/main (088b7da) auto-merged with zero conflicts |
| 7 | Single feature theme | **PASS** | One cohesive change: console discoverability — [?] binding, HelpScreen, startup hint, and the quit-gate dispatch fix it required. Touches only iris/console/app.py and the new iris/console/help_screen.py |

**Overall: PASS**

## Acceptance Criteria Verification

| Criterion | Result | Evidence |
|---|---|---|
| New `?` binding (question_mark), show=True, wired to action_help pushing HelpScreen | **PASS** | `Binding("question_mark", "help", "help")` first in BINDINGS; show defaults True (textual 8.2.7 signature confirmed); action_help() pushes HelpScreen(logpath) |
| HelpScreen modeled on ContactsScreen push/pop; q/escape (priority=True) dismiss; focus in on open, back to #log on dismiss | **PASS** | on_mount focuses #help-body; on_unmount mirrors action_list_panel's #log focus precedent (#log.can_focus=False, same no-op as existing behavior) |
| Content matches ti-00jr4 design-doc Section 2 verbatim; Shift/Alt tip appears exactly once | **PASS** | Diffed line-for-line against design doc (only the illustrative log path replaced by dynamic `{logpath}`, anticipated by the doc). Grep confirms Shift/Alt tip appears exactly once repo-wide |
| on_mount gets one new `[dim]` startup-hint line adjacent to the session-log line | **PASS** | Line added, same style; verified literal `[?]` does not get misparsed as Rich markup (Rich tag grammar requires `[a-z#/@...]`, `?` doesn't match) |
| Footer grows by exactly one always-visible entry; 80-col overflow handled per fallback policy if needed | **PASS** | Confirmed +1 exactly. 80-col truncation is a pre-existing, already-tracked condition (ti-ffch2, closed) — not a regression introduced here, correctly out of scope |
| No regressions to existing bindings/actions (NFR3) | **PASS** | Full suite green at reviewed commit (1557 passed, 3 xpassed, matching builder's claim) |
| check_action quit-gate fix (q on HelpScreen must not quit the app) | **PASS** | Reviewer wrote an ad hoc Pilot-based script: confirmed q/escape dismiss HelpScreen without quitting; normal quit from main screen still works. Narrow, correctly scoped fix (single `action=="quit"` + isinstance check) |

## Findings (from review ti-04dqq)

No blocking findings.

| Sev | Summary | Disposition |
|---|---|---|
| — | Footer 80-col truncation worsens by one entry | Pre-existing condition (measured before/after by builder), already tracked and closed as ti-ffch2 (decomposed into ti-ffch2.1/.2). Not a regression from this change |
| — | New quit-gate decision logic had no permanent automated test at review time | Sibling bead ti-00jr4.4 already closed its own coverage (14 tests, commit 78de176) on a separate branch/deploy — out of scope for this PR |
| — | Security | No injection/exposure risk — HelpScreen's Static uses `markup=False` defensively for the dynamic `{logpath}` interpolation. No new network/auth/deserialization surface; pure local TUI change |

## Test Run

```
Command: python -m pytest -q   (on deploy/ti-jcetz, cherry-pick of 2776212 onto origin/main@088b7da)
Result:  1616 passed, 3 xpassed, 2 warnings in 71.02s
```

Warnings are pre-existing Python 3.14 / GLib deprecations, unrelated to this change.
