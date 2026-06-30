# Release Gate: DisclosureCard widget (ti-rnlqo.6.1)

**Bead:** ti-vv7cn (deploy) → ti-cq6p8 (review)
**Commit:** cd820c1 (cherry-pick of 8fb034e) on feat/disclosure-card-ti-rnlqo-6-1
**Branch base:** origin/main (6cf3072)
**Date:** 2026-06-30

## Gate Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | **PASS** | ti-cq6p8 — reviewer-gm-l0iyz: "REVIEW VERDICT: PASS" |
| 2 | Acceptance criteria met | **PASS** | All 8 spec requirements verified (see below) |
| 3 | Tests pass | **PASS** | 1557 passed, 3 xpassed, 0 failures (61s) |
| 4 | No high-severity findings | **PASS** | 2 LOW findings only — neither a blocker |
| 5 | Final branch is clean | **PASS** | `git status` clean (untracked files are not part of commit) |
| 6 | Branch diverges cleanly from main | **PASS** | 1 cherry-picked commit, no conflicts |
| 7 | Single feature theme | **PASS** | 1 commit, 1 new file: `iris/console/call_card.py` |

**Overall: PASS**

---

## Acceptance Criteria Verification

From reviewer ti-cq6p8 spec compliance check — all 8 requirements confirmed against `iris/console/call_card.py` at cd820c1:

| # | Requirement | Status |
|---|-------------|--------|
| 1 | NOT a `_BaseCard` subclass — inherits `Widget` only | ✓ |
| 2 | EXPANDED state: orange border, amber header, yellow script, [D]/[S] buttons | ✓ |
| 3 | Focus trap: Tab/Shift-Tab D↔S, Esc=Skip, Enter=activate, d/s hotkeys | ✓ |
| 4 | Badge: `'✓ AI Disclosed'` (green) or `'⊘ Skipped'` (gray) | ✓ |
| 5 | Disk persistence: `~/.local/share/iris/disclosure-{session_id}.json` | ✓ |
| 6 | Re-init with saved state skips expansion | ✓ |
| 7 | Virtual button proxies (#disclose-btn, #skip-btn) | ✓ |
| 8 | `DisclosureState(str, Enum)`: EXPANDED | DISCLOSED | SKIPPED | ✓ |

## Open Findings (non-blocking)

1. **[LOW] Security** — `_state_path()` embeds `session_id` in filename without sanitization (call_card.py:114). `session_id` is not user-controlled; recommend defensive sanitization as follow-up.
2. **[LOW] Code Quality** — bare `except Exception: pass` in `_return_focus()` swallows unexpected failures. Safe for focus restoration; recommend `log.warning()` as follow-up.

## Test Run

```
1557 passed, 3 xpassed, 2 warnings in 61.38s
```

Ruff: `All checks passed!` on `iris/console/call_card.py`

## Scope

Single new file: `iris/console/call_card.py` (235 lines). No imports from the call-card feature stack; depends only on `textual.widget.Widget`, `json`, `enum`, `pathlib`, `typing`. Cherry-picks cleanly onto `origin/main` without phonenumbers/dateparser dependency (PR #124).
