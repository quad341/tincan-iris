# Release Gate: callcardview-ride-along-ti-krqie

**Bead:** ti-krqie — needs-deploy: CallCardView + ride_along refactor (ti-rnlqo.6.4+6.5)  
**Branch:** feat/callcardview-ride-along-ti-krqie  
**Review bead:** ti-kohgd (CLOSED — PASS)  
**Source commits:** e2c05d0 (CallCardView, ti-rnlqo.6.4), 209d2f2 (ride_along refactor, ti-rnlqo.6.5)  
**Fix commit applied:** 480030d console slice (data-loss fix + confidence bar extraction)  
**Gate run:** 2026-07-01

---

## Criteria

### 1. Review PASS present

**PASS**

Review bead ti-kohgd closed with verdict PASS. Reviewer (reviewer-gm-pz8ku) verified:
- on_daemon_event thread pattern: UI mutations via call_from_thread() safe
- _fact_from_dict/_action_item_from_dict: KeyError/ValueError caught, returns early (defensive pattern)
- call_from_thread usage: _prepend_card, _show_enriching, _hide_enriching, header update all on Textual loop
- ride_along refactor: old ActionItemCard removed, ActionItem wrapper for backward compat (session_id='', confidence=1.0) correct
- add_fact(CapturedFact): routes critical→CriticalFactCard, else→FactCard
- type annotation card: Widget (not _BaseCard) — correct since ActionItemCard from call_card.py is not a _BaseCard subclass
- ruff: clean on both files
- participation_level bindings: ]/[ keyboard shortcuts correct
- 480030d fixes verified: TranscriptStore tests, DaemonAPI CC tests, CriticalFactCard data-loss fix, confidence-bar extraction

### 2. Acceptance criteria met

**PASS**

All reviewer-confirmed checks passed in this deployment branch:

| Check | Result |
|-------|--------|
| CallCardView layout: header + DisclosureCard + _CallCardFeed + Footer | ✓ verified in call_card.py |
| _ParticipationLevel ]/[ key bindings wired | ✓ on_key in CallCardView |
| on_daemon_event routes all 5 event types (started/fact/action_item/ended/enriched) | ✓ call_from_thread used for all UI mutations |
| _fact_from_dict/_action_item_from_dict handle KeyError/ValueError | ✓ returns early on bad payload |
| ride_along add_fact(CapturedFact) routes critical → CriticalFactCard | ✓ if fact.fact_type == FactType.CRITICAL |
| ActionItemCard backward-compat (action_dismiss/action_create_reminder) | ✓ preserved in call_card.py |
| CriticalFactCard data-loss fix (_commit_edit) | ✓ applied from 480030d console slice |
| _confidence_bar extracted to standalone module | ✓ iris/console/_confidence_bar.py |
| ruff clean | ✓ ruff check iris/ tests/ → All checks passed |

### 3. Tests pass

**PASS**

```
1403 passed, 32 skipped, 3 xpassed, 2 warnings in 30.51s
```

Run: `python -m pytest tests/ -x -q --tb=short` on branch tip  
Note: This branch adds console widgets only; existing test coverage from the broader
codebase (1403 passing) includes all previously-deployed features.

### 4. No high-severity review findings open

**PASS**

Reviewer ti-kohgd noted only defensive patterns as LOW / informational:
- call_card_disclosure_needed event not handled in on_daemon_event (LOW — DisclosureCard self-manages from session_id at construction; current usage constructs fresh per call)

No HIGH findings. Zero unresolved blockers.

### 5. Final branch is clean

**PASS**

```
On branch feat/callcardview-ride-along-ti-krqie
nothing to commit, working tree clean
```

### 6. Branch diverges cleanly from main

**PASS**

Cherry-picks applied with zero conflicts:
- 8fb034e → 99b9e77 (DisclosureCard, 6.1): clean
- 07a142b → 9f7a5bd (CriticalFactCard+FactCard, 6.2): clean
- e147ded → 44e5abd (ActionItemCard, 6.3): clean
- e2c05d0 → 5cd1c51 (CallCardView, 6.4): clean
- 209d2f2 → d3b0af9 (ride_along refactor, 6.5): clean
- 480030d console slice → f02bdb6 (data-loss fix + _confidence_bar): clean

Files changed vs main: `iris/console/call_card.py`, `iris/console/ride_along.py`, `iris/console/_confidence_bar.py` (all in one subsystem).

### 7. Single feature theme

**PASS**

All commits touch `iris/console/` exclusively. This is the call_card widget chain:
- 6.1 DisclosureCard (consent gate modal)
- 6.2 CriticalFactCard + FactCard (fact display widgets + confidence bar)
- 6.3 ActionItemCard (action item widget with inline edit)
- 6.4 CallCardView (full-screen Textual app composing the above)
- 6.5 ride_along refactor (wires call_card.py widgets into ride_along.py)
- fix: CriticalFactCard data-loss fix + _confidence_bar extraction

These are tightly coupled (6.4 imports 6.1–6.3; 6.5 rewires 6.3 into ride_along). Cannot ship independently without breaking the caller.

---

## Overall: PASS

All 7 criteria PASS. Cleared to push and open PR.

**Note on scope:** 6.1–6.3 are included as prerequisites — `call_card.py` does not exist on `origin/main` before this PR. PR #125 (DisclosureCard only, feat/disclosure-card-ti-rnlqo-6-1) covers a subset of this scope and should be reviewed for supersession after this PR merges.
