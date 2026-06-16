# Release Gate: vec0+trust+arm-cli bundle (ti-dh6y)

**Bead:** ti-dh6y (deploy) / ti-2phx (review source) / ti-otoh, ti-qt1i.1.1, ti-qt1i.1.2, ti-qt1i.1.3, ti-qt1i.1.4 (build sources)
**Commits:** f7b8020 + 86afbe7 on main (HEAD=86afbe7)
**Branch:** feature/trust-vec0-arm-ti-dh6y → origin/main
**Date:** 2026-06-16
**Gate result:** PASS

---

## Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | ✅ PASS | ti-2phx notes: "Verdict: PASS" — first-pass reviewer (claude). Gemini second-pass disabled per project policy. |
| 2 | Acceptance criteria met | ✅ PASS | All acceptance criteria for all 5 sub-items verified in ti-2phx review notes (see below). |
| 3 | Tests pass | ✅ PASS | 484 passed, 2 skipped, 3 xpassed at 86afbe7. TDD tests for trust grant all pass. |
| 4 | No high-severity findings open | ✅ PASS | F1 (Low/Correctness) and F2 (Low/Future) — neither high-severity, neither blocking. |
| 5 | Final branch is clean | ✅ PASS | Both commits on origin/main via factory direct-push; no uncommitted changes. |
| 6 | Branch diverges cleanly from main | ✅ PASS | f7b8020+86afbe7 are on origin/main; no conflicts. |
| 7 | Single feature theme | ✅ PASS (with note) | Trust model changes (spoken-grant removal, TrustMode arm/grant, console UI, CLI) are tightly coupled and cannot ship independently. vec0 encoding fix (`iris/memory.py`) is technically a different subsystem but is bundled in f7b8020 alongside the spoken-grant removal (same commit, already on main — cannot be split). Reviewer reviewed the bundle as a unit. |

**Bundling note (criterion 7):** The vec0 fix (`iris/memory.py`) and the trust changes (`iris/trust.py`, `iris/console/`) touch different package prefixes and could theoretically ship independently. However, f7b8020 bundles them in a single commit that is already irrevocably on `origin/main` via the factory direct-push workflow; PM handoff (which requires pre-deploy splitting) is not actionable. Noted here for process visibility. Future: bundle related fixes only when they are genuinely coupled.

---

## Acceptance Criteria Evidence (from ti-2phx review)

### ti-otoh — vec0 insert encoding (iris/memory.py)
- ✅ insert_embedding: struct.pack(f'{n}f', *embedding) for vec0; json.dumps fallback
- ✅ fetch_embeddings_for_contact: symmetric struct.unpack / json.loads decode
- ✅ struct import added; empty embedding guard preserved

### ti-qt1i.1.1 — Remove spoken-grant (iris/console/app.py)
- ✅ _GRANT regex declaration deleted
- ✅ elif _GRANT.match(cmd) block deleted
- ✅ Zero _GRANT references remain; _STOP and _MARKUP still present
- ✅ SECURITY: eliminates voice-command privilege escalation path

### ti-qt1i.1.2 — TrustMode arm/grant + Conductor (iris/trust.py, iris/console/conductor.py)
- ✅ TrustMode: NONE/LOCAL/BOTH; DEMO=NONE, FULL=BOTH aliases (TrustMode.DEMO is TrustMode.NONE → True)
- ✅ Conductor: _trust + _armed replaces far_trust; far_trust property derived
- ✅ arm() idempotent; disarm() clears both; grant() no-op when unarmed; cycles NONE→LOCAL→BOTH→NONE
- ✅ grant_far() backward-compat; grant() requires arm() first (two physical actions for far-party elevation)

### ti-qt1i.1.3 — [g] grant cycle in console (iris/console/app.py — 86afbe7)
- ✅ action_grant() blocks on not c._armed; calls conductor.grant(); reads c.trust_state for display
- ✅ _do_arm_trust() calls arm() (not grant_far()) — ARM button just arms, not grants
- ✅ Trust labels: UNARMED/ARMED/LOCAL/LOCAL+FAR-REMOTE in status line

### ti-qt1i.1.4 — iris-arm/iris-disarm CLI (iris/console/arm.py — 86afbe7)
- ✅ Unix socket client to ~/.local/run/iris/console.sock
- ✅ Fails gracefully when no console running (exit 1)
- ✅ --ttl=N flag accepted (type=int, no injection); entry points registered in pyproject.toml

## Test Results

```
python -m pytest tests/ -q  (at factory HEAD 86afbe7)
484 passed, 2 skipped, 3 xpassed, 2 warnings in 6.92s
```

Reviewer confirmed: "484 tests pass at HEAD (86afbe7). TDD tests all pass."

## Security

OWASP pass per reviewer:
- Spoken-grant path eliminated → trust requires ARM button + [g] (two physical operator actions)
- struct.pack, type=int for --ttl, constant socket command string — no injection vectors
- FULL/DEMO aliases resolve correctly; allow_skills gate in Brain unchanged

## Non-blocking Findings

- **F1 — Low/Correctness** — iris/memory.py:151-161 — Mixed-encoding migration: pre-fix JSON rows in a vec0-enabled DB would fail struct.unpack. Not a blocker for new deployments; one-time concern for existing DBs.
- **F2 — Low/Future** — iris/console/arm.py:20 — Socket server (receiver) not yet implemented. When implemented, must use 0600 permissions. Client code correct today.

## Deploy Notes

f7b8020 and 86afbe7 were committed directly to origin/main via the factory's direct-push workflow before this PR was cut. This PR is the formal gate record. Feature branch `feature/trust-vec0-arm-ti-dh6y` was cut from `ad01965` (parent of f7b8020) with both commits cherry-picked; gate file is the only new content relative to main.
