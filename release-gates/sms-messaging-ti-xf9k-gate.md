# Release Gate: SMS/messaging lane (ti-xf9k)

**Bead:** ti-pyp1 (deploy) / ti-3ebf (review source) / ti-xf9k (build source)
**Commit:** ad01965c3339ea4c8634296bdd2564acff6af870
**Branch:** feature/sms-messaging-ti-xf9k → origin/main
**Date:** 2026-06-16
**Gate result:** PASS

---

## Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | ✅ PASS | ti-3ebf notes: "Verdict: PASS" — first-pass reviewer (claude). Gemini second-pass disabled per project policy. |
| 2 | Acceptance criteria met | ✅ PASS | All 5 criteria checked in ti-3ebf review notes (see below). |
| 3 | Tests pass | ✅ PASS | 484 passed, 2 skipped, 3 xpassed at factory HEAD (factory is 2 commits above ad01965; all messaging tests confirmed to pass individually). |
| 4 | No high-severity findings open | ✅ PASS | Only F1 (Low/Correctness) and F2 (Low/Test) — neither high-severity, neither blocking. |
| 5 | Final branch is clean | ✅ PASS | ad01965 committed directly to main via factory workflow; no uncommitted changes. |
| 6 | Branch diverges cleanly from main | ✅ PASS | ad01965 is on origin/main; no conflicts. |
| 7 | Single feature theme | ✅ PASS | SMS/messaging lane only: tincan_messages.py (D-Bus client) + messages_skill.py (read/send skills) + their tests. One subsystem. |

---

## Acceptance Criteria Evidence (from ti-3ebf review)

- ✅ MessageReceived + other signals subscribed and emitted as tuples into event queue
- ✅ ReadMessagesSkill: list conversations with unread counts, read thread by conversation_id
- ✅ SendMessageSkill: refuses to send without body; no self-initiation without explicit body
- ✅ FULL-trust gate: allow_skills=not demo_mode in Brain.respond() (brain.py:118, pre-existing, verified)
- ✅ Capability gate: _capable set at start(); _proxy() returns None when incapable; all method wrappers return empty/False; messages_unavailable event emitted
- ✅ No tincan daemon side modified: diff is 4 new files only
- ✅ Name→number resolution: _resolve_number() in messages_skill.py:116-131 uses get_contacts() → GetContacts; no prefs/roster

## Test Results

```
python -m pytest tests/ -q  (at factory HEAD 86afbe7, superset of ad01965)
484 passed, 2 skipped, 3 xpassed, 2 warnings in 7.07s

python -m pytest tests/test_tincan_messages.py tests/test_messages_skill.py -v
40 passed, 2 warnings in 0.06s
```

Reviewer confirmed at ad01965: "461 tracked tests pass. New tests: 40 (23 + 17) — all pass."

## Non-blocking Findings

- **F1 — Low/Correctness** — messages_skill.py:127-130 — partial name match priority (first match wins; exact match not preferred). Non-blocking per reviewer.
- **F2 — Low/Test** — test_tincan_messages.py:215 — daemon thread leaked in one test. Daemon threads die at process exit; no correctness impact. Non-blocking per reviewer.

## Deploy Notes

`ad01965` was committed directly to origin/main via the factory's direct-push workflow rather than via a feature-branch/PR. The formal gate + PR is retroactive. Feature branch `feature/sms-messaging-ti-xf9k` was cut from the commit's parent (`d3b792d`) with the gate file as new content.
