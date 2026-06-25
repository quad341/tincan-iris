# Release Gate: ti-2fiv-iris-up (ADR-0006 iris daemon/DND sprint)

**Bead:** ti-dl5x — needs-deploy: ADR-0006 iris daemon/DND sprint (ti-gxpt.1.1-1.3, 2-6)  
**Source bead:** ti-ryji (review bead, CLOSED/PASS)  
**Branch:** `feature/ti-2fiv-iris-up`  
**Gate commit:** `99a6f19`  
**Date:** 2026-06-25  

## Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | **PASS** | ti-ryji closed with reason=pass; notes: "REVIEW COMPLETE — PASS" (gm-wisp-89rho6j) |
| 2 | Acceptance criteria met | **PASS** | FR-01–FR-08, FR-10, FR-12 all verified by reviewer; see ti-ryji notes |
| 3 | Tests pass | **PASS\*** | 1176 passed, 13 skipped, 3 xpassed, 2 failed (pre-existing STT/TTS, ti-et9i) |
| 4 | No high-severity findings open | **PASS** | One LOW finding (HandlingEngine race window); acceptable per ADR-0006 single-attention spec |
| 5 | Final branch is clean | **PASS** | `git status` clean; only untracked `.gc/` artifacts |
| 6 | Branch diverges cleanly from main | **PASS** | No merge conflicts; `git merge-tree` clean against `origin/main` |
| 7 | Single feature theme | **PASS** | All 10 commits implement ADR-0006 iris daemon/DND; single subsystem (`iris/daemon/`, `iris/roster.py`) |

\* Two pre-existing test failures unrelated to this sprint:
- `test_stt.py::test_default_stt_is_faster_whisper` — filed as ti-et9i
- `test_tts.py::test_default_tts_uses_kokoro_when_available` — filed as ti-et9i

## Verdict: PASS

## Commits on branch (vs origin/main)

| SHA | Message |
|-----|---------|
| `99a6f19` | feat(roster): PostureStore + v2 migration tests (ti-gxpt.1.3) |
| `3ace0de` | feat(console): IncomingCallPanel + DaemonProxy integration (ti-gxpt.5) |
| `4952092` | feat(cli): iris daemon/dnd subcommands + daemon process entry point (ti-gxpt.6) |
| `d4970ba` | feat(tui): contacts screen — ADR-0006 enum labels + ignore warning badge (ti-gxpt.1.2) |
| `2343012` | feat(daemon): DaemonAPI + DaemonProxy — Unix socket IPC layer (ti-gxpt.4) |
| `29feb8d` | feat(daemon): PolicyResolver + HandlingEngine skeleton — verb dispatch + AttentionLock (ti-gxpt.3) |
| `78948e6` | feat(daemon): PostureManager + PostureWatcher + IrisConsole DND integration (ti-gxpt.2) |
| `c36e333` | feat(roster): schema migration v2 — handling_rule enum renames + posture/schedules tables (ti-gxpt.1.1) |
| `248200f` | fix(install): retire obsolete units before the preflight gate |
| `4e96653` | feat(up): one-command stack bring-up; drop iris-brain unit (ti-2fiv) |

## Review summary (ti-ryji)

**Security:** Socket mode 0600 ✓, dnd_source not exposed ✓, no injection surface ✓  
**Spec compliance:** All FRs verified; FR-02 bounded terminal partially stubbed (in-scope per ti-gxpt.5 DoD)  
**Findings:** 1 LOW (HandlingEngine race window — acceptable per ADR-0006 single-attention invariant)  
**Test coverage:** test_daemon_api.py, test_daemon_cli.py, test_roster_migration.py, test_incoming_call_panel.py, test_iris_up.py — all present and passing
