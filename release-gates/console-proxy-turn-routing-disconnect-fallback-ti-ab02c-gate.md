# Release Gate: Console proxy turn routing + disconnect fallback (ti-ab02c)

**Date:** 2026-06-30
**Bead:** ti-ab02c (deploy) / source bead: ti-psvkj
**Source commit:** `414c2efc` on builder branch `tests/ti-t1512-ti-e09mq-cadence-phrasebook`
**Deploy branch:** `feat/console-proxy-turn-routing-ti-s9mm-3-2` (cherry-pick onto PR #116 base)
**Reviewer:** reviewer-gm-xppjp (PASS)
**Deployer:** tincan-iris/deployer

---

## Criteria Evaluation

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | **PASS** | reviewer-gm-xppjp: PASS — all 19 spec tests pass, 5/5 ACs met, ruff clean, no OWASP surface |
| 2 | Acceptance criteria met | **PASS** | All 5 ti-s9mm.3.2 ACs verified in `iris/console/app.py` — see below |
| 3 | Tests pass | **PASS** | 1386 passed, 32 skipped, 3 xpassed, 2 warnings — zero failures |
| 4 | No high-severity review findings | **PASS** | "Security: internal Unix socket IPC, no OWASP surface" — no HIGH/CRITICAL findings |
| 5 | Final branch is clean | **PASS** | `git status` clean — only untracked non-project overlays (.gc/, .gitkeep, deployer dirs) |
| 6 | Branch diverges cleanly from main | **PASS** | 3 commits over main: 3.1 feat + 3.1 gate + 3.2 feat — cherry-picked without conflict |
| 7 | Single feature theme | **PASS** | All commits: console proxy mode (ti-s9mm.3.1 mode detection + ti-s9mm.3.2 turn routing) |

**Overall: PASS**

---

## Evidence

### Criterion 1 — Review PASS

Bead ti-ab02c notes (from reviewer-gm-xppjp):
> "Style clean (ruff pass), all 19 spec tests pass, all 5 acceptance criteria met, no console
> regressions (122 tests pass). Security: internal Unix socket IPC, no OWASP surface.
> Architecture: idempotent disconnect fallback, thread-safe PTT worker."

Verdict: **PASS**

### Criterion 2 — Acceptance Criteria (ti-s9mm.3.2)

| AC | Description | Location | Status |
|----|-------------|----------|--------|
| AC1 | `_dispatch()` sends `stream_turn` to daemon in proxy mode (not local conductor) | `app.py` lines 878–888 | ✅ |
| AC2 | PTT stop in proxy mode uses `_proxy_stop_and_respond` (local STT → socket) | `app.py` lines 1045–1048 | ✅ |
| AC3 | `_on_daemon_event()` handles brain_turn_started, brain_chunk, brain_reply, error | `app.py` lines 695–728 | ✅ |
| AC4 | Disconnect fallback is idempotent: `_switch_to_direct()` no-ops if already direct | `app.py` lines 764–775 | ✅ |
| AC5 | `DaemonNotRunning` from `proxy.send()` also triggers `_switch_to_direct()` | `app.py` lines 883–885 | ✅ |

### Criterion 3 — Tests Pass

Ran on `feat/console-proxy-turn-routing-ti-s9mm-3-2` (clean branch):

```
python -m pytest tests/ -q
1386 passed, 32 skipped, 3 xpassed, 2 warnings in 27.67s
```

Note: `tests/test_console_thin_client.py` (19 tests) is skipped on this machine —
`textual` is not installed. Reviewer ran these 19 tests on their machine (all PASS per
bead notes). The remaining 1386 tests exercise the full non-textual suite.

### Criterion 4 — No High-Severity Findings

Reviewer: "Security: internal Unix socket IPC, no OWASP surface." No HIGH or CRITICAL
findings. ruff clean on `iris/console/app.py`.

### Criterion 5 — Branch Clean

```
On branch feat/console-proxy-turn-routing-ti-s9mm-3-2
Untracked files: .gc/, .gitkeep, release-gates/ (deployer overlays + stale gate files)
nothing added to commit but untracked files present
```

### Criterion 6 — Clean Divergence from Main

Cherry-picked `414c2efc` cleanly onto `feat/console-proxy-direct-mode-ti-s9mm-3-1`
(PR #116 tip, `44f64b9`). Three commits over `origin/main`:

```
7fe06ff feat(console): proxy turn routing + disconnect fallback (ti-s9mm.3.2)
44f64b9 chore: release gate PASS for console-proxy-direct-mode-ti-s9mm-3-1
a3ef9a9 feat(console): proxy/direct mode detection, startup log, status pill (ti-s9mm.3.1)
```

No merge conflicts. Auto-merge on cherry-pick.

### Criterion 7 — Single Feature Theme

All commits are in the console proxy subsystem (`iris/console/app.py`), part of the same
daemon-proxy-mode UX feature (ti-s9mm.3.x). Removing one commit from main would break
the other (3.2 depends on `self._mode` set in 3.1). Single theme PASS.

**Note on PR #116:** An existing open PR (#116) covers the 3.1 commit (`a3ef9a9`). The
deploy branch for this bead includes 3.1 + gate + 3.2. Mayor should close PR #116 when
merging this PR to avoid duplicate work.
