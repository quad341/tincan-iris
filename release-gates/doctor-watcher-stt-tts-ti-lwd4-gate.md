# Release Gate: doctor/watcher/stt/tts round-2 corrections (ti-lwd4)

**Bead:** ti-lwd4 — needs-deploy: server providers, doctor, watcher, HomeApp sprint (from:ti-c6ns)
**Branch:** feature/ti-qxel-6qsb-sprint
**Tip commit:** 720766d
**Gate date:** 2026-06-18
**PR:** https://github.com/quad341/tincan-iris/pull/50

---

## Gate Checklist

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | **PASS** | ti-c6ns (round-2 reviewer bead) closed with "PASS (round 2) — all 5 findings resolved. 913 passed." All F-CORRECT-01/02/03, F-STYLE-01, F-SAFE-01 resolved in commit 720766d. |
| 2 | Acceptance criteria met | **PASS** | See finding resolution below. |
| 3 | Tests pass | **PASS** | 874 passed, 4 skipped, 3 xpassed, 2 warnings on `feature/ti-qxel-6qsb-sprint@720766d`. |
| 4 | No high-severity findings open | **PASS** | All findings in round-1 review (ti-4lzj via ti-c6ns) were medium/style severity; all resolved. F-SEC-01 from ti-6v2m (FarEndIdentity, separate bead) was explicitly deferred to ti-nr3m.6 by design decision — not a blocker for this sprint PR. |
| 5 | Final branch is clean | **PASS** | `git status` shows only untracked build artifacts (.beads/identity.toml, docs/plans/, tincan_iris.egg-info/). No uncommitted changes. |
| 6 | Branch diverges cleanly from main | **PASS** | `git merge --no-commit origin/main` → "Already up to date." Feature branch has clean linear divergence from origin/main (20 commits ahead, no conflicts). |
| 7 | Single feature theme | **PASS** | All changes are part of the ti-qxel/ti-6qsb sprint: persistent server providers, doctor health-check CLI, ProactiveWatcher with NUDGE_CACHE, HomeApp Textual dashboard, email/roster features, FarEndIdentity, and STT/TTS server adapters. Sprint work has intra-feature dependencies (FarEndIdentity uses roster contact_id; email skills use roster; doctor uses server-provider config). Shipped as one coherent sprint PR. |

---

## Finding Resolution (round-2 corrections, commit 720766d)

| Finding | Description | Resolution |
|---------|-------------|------------|
| F-CORRECT-01 | `--deep` flag did not show round-trip latency | Fixed: added `Round-trip` column via `time.monotonic` on health-URL check; displays `—` for services without `health_url`. |
| F-CORRECT-02 | `doctor_main` used hardcoded float timeouts | Fixed: reads `DEFAULT.doctor_timeout_s` / `DEFAULT.doctor_deep_timeout_s` from Config. |
| F-CORRECT-03 | `NUDGE_CACHE` NULL != NULL dedup failure | Fixed: `NUDGE_CACHE` gains `title_hidden` + `starts_at` columns; `nudge_key` falls back to `sha256(title+starts_at)[:16]` when `event_id is None`. |
| F-STYLE-01 | Unused `field` import in `doctor.py` | Fixed: removed. |
| F-SAFE-01 | `urlopen()` in `transcribe()` and `synth()` lacked timeout | Fixed: `timeout=30.0` added, matching `available()` discipline. |

---

## Sprint PR Context

This gate covers the final round-2 corrections on top of the sprint branch. The full sprint was previously gated in:
- `release-gates/email-roster-ti-2ykz-ti-4530-ti-5xly-gate.md` (commit fd3c9a7) — covering ti-2ykz/ti-4530/ti-5xly email-roster work
- `release-gates/farend-identity-ti-btj3-gate.md` (commit d257466) — covering ti-btj3 FarEndIdentity (also in PR #52 cherry-pick branch)

All sprint work merges via **PR #50** (`feature/ti-qxel-6qsb-sprint → main`). PR #52 (`release/farend-identity-ti-btj3`) is a subset cherry-pick branch; mayor should close it when merging PR #50.

---

**Overall verdict: PASS**
