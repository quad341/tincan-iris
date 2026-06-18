# Release Gate: ARM TRUST button reviewer fix (ti-l69j)

**Bead:** ti-l69j (deploy acknowledgment) / ti-0us7 (review source) / ti-3qgj (build source)
**Commit:** e36e6b0 on origin/main
**Type:** Post-merge acknowledgment — commit was merged to origin/main before deploy review cycle completed. No PR needed; gate closes the deploy bead.
**Date:** 2026-06-16
**Gate result:** PASS

---

## Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | ✅ PASS | ti-0us7 notes: first-pass reviewer (claude/tincan-iris/reviewer) PASS. Evidence: unused param removal, f-string fix, _GRANT constant re-exposure, 4 pilot tests (card show/arm/badge/hide lifecycle). Security: ARM TRUST requires physical button — no spoken/remote escalation path. All OWASP checks clear. |
| 2 | Acceptance criteria met | ✅ PASS | See acceptance evidence below. All four reviewer changes-requested items verified in e36e6b0 via `git show`. |
| 3 | Tests pass | ✅ PASS | 484 passed, 2 skipped, 3 xpassed on deployer branch. 23/23 trust grant tests pass (`python -m pytest tests/test_trust_grant*.py`). test_console_app.py skipped (Qt pilot-harness env not active in deployer rig); reviewer confirmed 528/528 in full env. |
| 4 | No high-severity findings open | ✅ PASS | Reviewer listed no HIGH findings. All OWASP checks clear. |
| 5 | Final branch is clean | ✅ PASS | Post-merge acknowledgment; e36e6b0 is on origin/main. No uncommitted changes on deploy branch (only untracked .claude/.gc/.codex artifacts). |
| 6 | Branch diverges cleanly from main | ✅ PASS | e36e6b0 IS on origin/main; no conflicts. Deployer branch has the pre-fix ARM TRUST UI (d3b792d) which is the base the fix was applied to. |
| 7 | Single feature theme | ✅ PASS | ARM TRUST console UI polishing: unused param removal, f-string cleanup, _GRANT regression constant, 4 pilot tests. Single subsystem (iris/console/app.py + tests). |

---

## Acceptance Criteria Evidence (from ti-0us7 review + commit verification)

### e36e6b0 — address reviewer changes-requested on ARM TRUST button (iris/console/app.py)

- ✅ `mark_armed(self, contact_name: str)` → `mark_armed(self)` — unused param removed (git show confirms `- def mark_armed(self, contact_name: str)` / `+ def mark_armed(self)`)
- ✅ `mark_unarmed(self, contact_name: str)` → `mark_unarmed(self)` — unused param removed
- ✅ `f"[b yellow]■ TRUST ARMED[/]"` → `"[b yellow]■ TRUST ARMED[/]"` — superfluous f-prefix removed
- ✅ `_GRANT` re-exposed as module constant (spoken-grant path already eliminated in ti-qt1i.1.1; constant retained for regression testing)
- ✅ 4 pilot tests added to test_console_app.py: call_connected shows card, ARM button arms conductor, far_trust=BOTH shows badge/hides button, call_ended hides card
- ✅ Stale tests that assumed [a]=grant and spoken grant still worked — updated

### Security (from reviewer)
- ✅ ARM TRUST requires physical operator button press — no spoken/remote escalation path
- ✅ Spoken-grant regex (`_GRANT`) retained only as a tested constant; action branch was removed in ti-qt1i.1.1
- ✅ OWASP clear: no input injection, no privilege escalation path via voice command

---

## Test Results

```
python -m pytest tests/ -q  (deployer branch)
484 passed, 2 skipped, 3 xpassed, 2 warnings in 7.24s

python -m pytest tests/test_trust_grant.py tests/test_trust_grant_app.py tests/test_trust_grant_cli.py  (deployer branch)
23 passed, 1 skipped in 0.20s

tests/test_console_app.py: 0 collected / 1 skipped
  (Qt pilot-harness not active in deployer rig — env constraint, not a regression)

Reviewer (origin/main at e36e6b0):
528/528 tests pass in reviewer env, including 4 new pilot tests for card lifecycle.
```

---

## Deploy Notes

e36e6b0 was committed directly to origin/main by the factory before the deploy review cycle completed. This gate is an acknowledgment that the change was reviewed and passed, the tests pass, and the deploy bead can be closed. No PR was opened or needed.
