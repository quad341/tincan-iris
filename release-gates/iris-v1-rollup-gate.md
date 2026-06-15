# Release Gate: Iris v1 Rollup (ti-lmw.2)

**Branch:** `rollup/iris-v1-20260615`  
**Approach:** 20 commits cherry-picked from `origin/iris/tincan-sco` onto current main  
**Base:** `origin/main` @ `5424a46` (post PRs #25–#29)  
**HEAD:** `28d636d` (feat(console): wire ProactiveDelivery into IrisConsole)  
**Gate evaluated:** 2026-06-15  
**Plan context:** ti-lmw.2 two-phase deployment plan; Phase 1 (PRs #25–28 + #29) already merged

## Result: PASS

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | **PASS** | ti-hm4 PASS (ProactiveDelivery engine); ti-cul resolved + ti-hm4 verified (ProactiveStore); ti-h69 PASS (IrisConsole wiring). All other features are PM-authored with closed test-suite acceptance beads (see §Review Coverage). |
| 2 | Acceptance criteria met | **PASS** | All ti-ccc sub-beads for included features are closed. P2 advisory (TTS log line missing) is documented and deferred — fix commit 28737b7 is orphaned and NOT in this PR. |
| 3 | Tests pass | **PASS** | 334 passed, 1 skipped, 3 xpassed |
| 4 | No high-severity findings open | **PASS** | P0 blocker in ti-cul (enqueue() API mismatch) was resolved in commit aad6f9c and verified PASS in ti-hm4 review. Remaining findings are P2/P3 advisories. |
| 5 | Final branch is clean | **PASS** | Cherry-picked 20 commits; no conflicts; diff is pure additions (4504 ins, 15 del within code files; zero deletion of docs/gate files). |
| 6 | Branch diverges cleanly from main | **PASS** | 20 cherry-picks onto origin/main with 0 conflicts. Diff: 20 files, +4504/−15. |
| 7 | Single feature theme | **EXCEPTION — PM-approved** | Multi-feature rollup per ti-lmw.2 plan. PM sanctioned bundling all remaining iris/tincan-sco features as a single Phase 2 PR after foundation PRs #25–29 merged. |

## Cherry-Picked Commits (original SHA → rollup SHA)

| Original | Rollup | Feature | Bead |
|----------|--------|---------|------|
| 0a487d8 | a22c4d5 | feat(data): CallList/ListItem/LookupResult data layer + SQLite schema | ti-ccc.16.1 |
| 8be29ac | 84f0afc | test: TDD suites for context/web-search/calendar/list-skill | — |
| d8ab0eb | 1857043 | feat(context): ConversationContext — window + gist tiers | ti-ccc.11.1.1 |
| a2ad52e | 811945b | feat(list_skill): ListSkill + lookup_status on ListItem | ti-ccc.16.2 |
| 1a84972 | 75def64 | feat(web_search): core fetch engine + SSRF guard | ti-ccc.15.1.1 |
| 58dd141 | 8cb35d5 | feat(web_search): DATA block Q&A isolation layer | ti-ccc.15.1.2 |
| bf6d45c | f3108bf | feat(web_search): PM-approved UX wording + no-URL prompt | ti-ccc.15.1.3 |
| 26f758c | cc9730a | feat(context): TranscriptContext — third tier on-demand lookup | ti-ccc.11.1.2 |
| 4683220 | 6b448d8 | feat(calendar): CalendarClient + three skills + OAuth token management | ti-ccc.14.1.1/14.1.3/14.1.4 |
| f9289f1 | 6b4c5ae | feat(list): async lookup integration + list panel | ti-ccc.16.3/16.4 |
| 6b12fb1 | 0db288c | feat(console): PostCallListView + list_store.set_lookup_status | ti-ccc.16.5 |
| 0177abd | c4c56a0 | feat(audio): AEC support in TincanSCOAudio + scripts/aec_audio.sh | ti-ccc.9 |
| 4add757 | e833fea | feat(context,config): gist playback + proactive config skeleton | ti-ccc.11.1.3/ti-ccc.17.1 |
| 2a9a9a6 | dd7631b | feat(audio): AGC + noise suppression on AEC module | ti-ccc.10 |
| 782109f | 60c4a9b | feat(audio): device selection via IRIS_PLAYBACK_DEVICE + IRIS_CAPTURE_DEVICE | ti-3eh |
| 381f21b | a52028f | test(brain): DEMO-mode Tier2 and skill-dispatch blocking | ti-93w |
| 4476e74 | 6c0d251 | feat(proactive): ProactiveStore + ProactiveItem SQLite CRUD | ti-ccc.17.2.2 |
| c4bd1d1 | f38d108 | test(proactive): pre-author store + delivery test suites | ti-ccc.17.2.4 |
| aad6f9c | 181a82c | feat(proactive): ProactiveDelivery engine + SilenceTracker + ContextInferenceTrigger | ti-ccc.17.2.3 |
| 0945641 | 28d636d | feat(console): wire ProactiveDelivery into IrisConsole | ti-ccc.17.2.5 |

**Skipped (already in main via PRs #26–29):** 1b151fa (trust tighten), 4b8b234 (trust default far_trust=DEMO)

## Review Coverage

| Feature group | Review bead | Verdict |
|--------------|-------------|---------|
| ProactiveDelivery engine (aad6f9c) | ti-hm4 | PASS — "334 tests pass, safety invariant verified" |
| ProactiveStore CRUD (4476e74) | ti-cul → ti-hm4 | P0 BLOCKER resolved in aad6f9c; PASS verified in ti-hm4 |
| IrisConsole wiring (0945641) | ti-h69 | PASS — "334 tests pass, all safety invariants verified" |
| Context system (ti-ccc.11) | ti-ccc.11.1.4 closed | PM-authored; test-suite acceptance bead closed |
| Calendar (ti-ccc.14) | ti-ccc.14.1.4 + ti-ccc.14.1.5 closed | PM-authored; UX integration + test-suite acceptance beads closed |
| web_search (ti-ccc.15) | ti-ccc.15.1.4 closed | PM-authored; test-suite acceptance bead closed |
| AEC/AGC/device-selection (ti-ccc.9/10, ti-3eh) | — | PM-authored; no separate reviewer bead |
| Data layer/list/post-call (ti-ccc.16) | — | PM-authored; no separate reviewer bead |
| Proactive config skeleton (ti-ccc.17.1) | — | PM-authored; covered by ProactiveDelivery review context |
| DEMO-mode brain tests (ti-93w) | — | PM-authored test additions |

## Test Run

```
$ python -m pytest tests/ -x -q --tb=short
334 passed, 1 skipped, 3 xpassed in 3.98s
```

All tests run from the deployer worktree (`rollup/iris-v1-20260615` at HEAD `28d636d`).

## Known Gaps / Advisories

### P2 ADVISORY — TTS log line missing (carry-forward from ti-h69)
- **Finding:** ProactiveDelivery.tick() does not emit `('proactive_tts', message)` after TTS fires; IrisConsole._drain() has no handler for this event; no transcript log line is written for proactive deliveries.
- **AC unmet:** "Transcript log shows 🔔 prefix line for each TTS delivery"
- **Fix commit:** 28737b7 (`fix(proactive): emit proactive_tts event after tts_fn() fires, ti-wi6`) — this commit is **ORPHANED** (not on any remote branch) and is NOT included in this PR.
- **Status:** Deferred. Filed as ti-4wr / ti-wi6 / ti-110. Operator acknowledged P2 advisory in ti-h69 close reason ("deploy bead ti-2gj created, follow-up ti-wi6 filed").

### Multi-feature rollup exception (criterion #7)
- 20 commits spanning 10+ feature areas bundled per PM two-phase deployment plan.
- Phase 1 (PRs #25–#29) established the spine: trust model, dispatch, notes, call-control, transcript, prefs, STT/speaker/skill-param, docs.
- This Phase 2 PR covers everything that was building on that spine on iris/tincan-sco.

### Features with no external reviewer bead
- AEC/AGC/device-selection, CallList data layer, async lookup/list panel, PostCallListView, gist playback/proactive config, DEMO-mode brain tests.
- All are PM-authored; all test suites pass; PM explicitly sanctioned this rollup (ti-lmw.2 bead, source:actual-pm label).

## Satisfies

- ti-lmw (needs-deploy: ProactiveDelivery engine + ProactiveStore fixes)
- ti-2gj (needs-deploy: ProactiveDelivery IrisConsole wiring)
- ti-110 (needs-deploy: proactive TTS log fix — **ADVISORY: fix commit 28737b7 is orphaned; this PR does NOT include the TTS log fix**)
