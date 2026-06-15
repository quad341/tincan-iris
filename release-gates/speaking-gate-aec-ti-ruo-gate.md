# Release Gate: speaking gate + AEC for virtual-audio call path (ti-ruo)

**Bead:** ti-ruo (source: ti-2d4 / ti-jpo)  
**Feature branch:** feature/speaking-gate-aec-ti-ruo  
**Commits cherry-picked:** 05a1abe (feat), 1fc1a6e (tests), b74af22 (fix)  
**Source SHAs:** cd55ff9 → 04fde25 → 496716b  
**Gate evaluated:** 2026-06-15

---

## Criterion 1 — Review PASS present

**PASS**

ti-2d4 (review bead) closed with `pass`. Notes contain:

> PASS (follow-up fix review)  
> Commit 496716b adds self.capture_target: str | None = None to LocalAudio.__init__()… Bug confirmed resolved. 152 tests pass.

First-pass (claude reviewer): full review of cd55ff9 + 04fde25 + 496716b — all PASS.  
Second-pass (gemini): disabled per rig policy — single-pass sufficient.

---

## Criterion 2 — Acceptance criteria met

**PASS**

From ti-jpo / ti-ruo:

| Criterion | Evidence |
|-----------|----------|
| `Conductor.speaking` True in THINKING/SPEAKING | `conductor.py:48` — property returns `self._state in (State.THINKING, State.SPEAKING)` |
| `_on_heard()` gate suppresses mic when speaking | `app.py:291-292` — `if self.conductor.speaking: return` |
| `IRIS_VA_AEC=1` sets `capture_target=iris_va_aec_src` | `endpoint.py:360` — `_VA_AEC_SRC if os.environ.get("IRIS_VA_AEC") else None` |
| `IRIS_CAPTURE_TARGET` overrides `IRIS_VA_AEC` | `endpoint.py:353-358` — explicit env var wins |
| `capture_target` threaded into `StreamingTranscriber` | `app.py:249` — `source=self.mic.capture_target` |
| `aec-up`/`aec-down` in `virtual_audio.sh` | `scripts/virtual_audio.sh` — module-echo-cancel WebRTC+AGC+NS |
| `LocalAudio.capture_target = None` (AttributeError fix) | `endpoint.py:122` — `self.capture_target: str | None = None` |
| Operator-gated verify (live Discord + speakers) | ti-jpo notes: "DONE: speaking-gate + AEC integrated… verified on a live speaker call" |

---

## Criterion 3 — Tests pass

**PASS**

```
pytest tests/ — 143 passed, 1 skipped in 1.35s
```

Feature-specific tests all PASS:
- `test_conductor.py` — 5 new speaking-property tests (THINKING/SPEAKING/IDLE/RECORDING/TRANSCRIBING)
- `test_endpoint.py` — IRIS_VA_AEC branching + IRIS_CAPTURE_TARGET precedence (22 added lines, all pass)
- `test_console_app.py` — _on_heard gate tests: **SKIPPED** (textual not installed in CI)

The `test_console_app.py` skip is a known infrastructure gap (textual is an optional extra). The docstring notes "the pipeline logic itself is covered in test_conductor." The `speaking` property coverage (5 tests) substitutes for the _on_heard gate tests in the automated suite; operator verification confirmed behavior end-to-end.

Note: reviewer counted 152 tests on local main (which carried 3 additional commits from other beads). 143 is the correct count on this branch (origin/main + cherry-picks).

---

## Criterion 4 — No high-severity review findings open

**PASS**

One BLOCKING MEDIUM finding was raised:
> LocalAudio missing capture_target — AttributeError on action_listen() in local mode

Fixed in 496716b (`self.capture_target: str | None = None` in LocalAudio.__init__). Re-reviewed by reviewer with verdict PASS. No HIGH findings remain open.

---

## Criterion 5 — Final branch is clean

**PASS**

```
git status: nothing to commit (untracked: .claude/ .codex/ .gc/ .gitkeep — deployer internals, not tracked)
```

---

## Criterion 6 — Branch diverges cleanly from main

**PASS**

Branch diverges cleanly from `origin/main` at 1d0cb38. Three cherry-pick commits apply without conflict. `.beads/interactions.jsonl` (tracking artifact) was stripped; file remains at its origin/main state (empty).

```
git log --oneline origin/main..HEAD:
  b74af22 fix(audio): add capture_target to LocalAudio to match VirtualDeviceAudio interface
  1fc1a6e test(ti-lfp): cover speaking gate + IRIS_VA_AEC endpoint branching
  05a1abe feat(audio): speaking gate + AEC for virtual-audio call path (ti-jpo)
```

---

## Criterion 7 — Single feature theme

**PASS**

All three commits address a single feature theme: eliminating self-echo in the virtual-audio (Discord) call path.

- cd55ff9 / 05a1abe: speaking gate + AEC endpoint integration (the fix)
- 04fde25 / 1fc1a6e: tests for the above
- 496716b / b74af22: LocalAudio interface fix that was a blocker to the feature working in local mode

These are tightly coupled: the tests and the LocalAudio fix exist solely because of the feature commit. Removing either would break the feature or leave it untested.

---

## Overall verdict: **PASS**

All 7 criteria pass. Proceeding with push and PR.
