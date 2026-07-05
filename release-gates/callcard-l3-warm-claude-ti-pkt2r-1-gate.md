# Release Gate: callcard-l3-warm-claude-ti-pkt2r-1

**Bead:** ti-uo3l7
**Source bead:** ti-pkt2r.1 (closed) + ti-pkt2r.1.1 (closed, test companion)
**Review bead:** ti-vvkxi (closed, `Review verdict: PASS`)
**Feature branch:** deploy/callcard-l3-warm-claude-ti-pkt2r-1
**Base:** origin/main @ b0b827b52281e5c5bde63224ae38a0fd2cd1a1f9
**Gate commit:** f96b4c8e202c1192b4393f33351b558d19733c03
**Date:** 2026-07-05

---

## Branch construction note (read before the criteria table)

The deploy bead named two commits to land: `76237d0` (impl, ti-pkt2r.1) and
`06a4625` (tests, ti-pkt2r.1.1). Their actual git ancestry on
`feat/callcard-after-data-layer-ti-hb2dx` is:

```
origin/main-ancestor 8796d99 (#164, already on origin/main)
  └─ e72052b  "Call Card AFTER post-call recap generator (ti-6a1y3)"   <- different bead, NOT part of this deploy
       └─ 76237d0  "route Call Card L3 through warm ClaudeTuiSession (ti-pkt2r.1)"  <- wanted
            └─ 06a4625 (on a sibling tests/ branch, based on 76237d0)              <- wanted
```

`e72052b` belongs to bead ti-6a1y3, which is sitting in a separate, paused
deploy queue (ti-zd5os per ti-uo3l7's description) and has not been through
its own deploy gate. `76237d0`'s own diff modifies files `e72052b`
introduced (`recap.py`, `_llm_common.py`), so a plain `git cherry-pick
76237d0` onto `origin/main` conflicts (those files don't exist on main yet).

Per ti-uo3l7 / ti-vvkxi, `76237d0` is a "fresh implementation" of these
files, i.e. its own tree state is the complete intended result — nothing
from `e72052b` needs to survive independently. So instead of cherry-picking
`e72052b` too (which would land an unreviewed, out-of-scope bead on main),
this branch reconstructs `76237d0`'s exact tree state for exactly the file
set its own commit touches (`git checkout 76237d0 -- <10 files>`), verified
byte-identical (`git diff 76237d0 -- <10 files>` → empty), then commits that
as a single commit reusing 76237d0's original author/message
(`git commit -c 76237d0`). `06a4625` (test-only, purely additive, 4 new
files) then cherry-picks cleanly on top with zero conflicts.

Net effect: the final tree is identical to what reviewer ti-vvkxi actually
reviewed at `76237d0`/`06a4625`, landed as 2 commits on `origin/main`,
without pulling in ti-6a1y3's separate, not-yet-gated work.

---

## Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | **PASS** | ti-vvkxi closed `Review verdict: PASS` (tincan-iris/reviewer, 2026-07-05); zero HIGH/blocking findings |
| 2 | Acceptance criteria met | **PASS** | See AC table below |
| 3 | Tests pass | **PASS** | `make verify` (ruff + pytest) on assembled branch: ruff clean; pytest 1794 passed, 1 skipped, 3 xpassed, 1 failed (pre-existing, see below) |
| 4 | No high-severity review findings open | **PASS** | ti-vvkxi verdict PASS; all 4 findings explicitly logged as Low/informational/process-note, none blocking |
| 5 | Final branch is clean | **PASS** | `git status` clean (only pre-existing worktree scaffolding `.gc/`, `.gitkeep`, and this venv's `tincan_iris.egg-info/` untracked, none part of source) |
| 6 | Branch diverges cleanly from main | **PASS** | `git merge-tree` against origin/main: no conflicts; cherry-pick of 06a4625 applied clean |
| 7 | Single feature theme | **PASS** | ti-pkt2r.1 (impl) + ti-pkt2r.1.1 (its direct unit-test companion) — same subsystem (`iris/capture/` L3 post-call pipeline), same bead family, tests exist only to cover this impl |

---

## Acceptance Criteria (ti-pkt2r.1 + ti-pkt2r.1.1)

| AC | Description | Verdict |
|----|-------------|---------|
| AC1 | Both commits land on main via the normal deploy/PR path | ✅ Being satisfied by this PR |
| AC2 | CI green | ✅ PASS — see test run below |
| AC3 | No anthropic/instructor dependency reintroduced | ✅ PASS — confirmed by two independent methods below |

**Zero-anthropic-key bar** (the explicit owner directive on ti-pkt2r), reconfirmed independently on this assembled branch, not just trusted from prior bead notes:

- Static: `grep -rn "anthropic\|instructor" iris/capture/` → zero matches; `grep -rn "anthropic_api_key\|ANTHROPIC_API_KEY\|IRIS_ANTHROPIC_API_KEY" iris/` → zero matches.
- Dependency-level: fresh venv, `pip install -e '.[console,call-card]'` from this branch's own `pyproject.toml` (call-card extra is now `pydantic>=2`, was `instructor[anthropic]>=1.0`) → `pip freeze | grep -i "anthropic\|instructor"` → empty.

---

## Test Run

```
make install  # pip install -e '.[console,call-card]' pytest ruff
ruff check .                       → All checks passed!
pytest -q                          → 1794 passed, 1 skipped, 3 xpassed, 1 failed in 79.74s
```

The 1 failure (`tests/test_daemon_call_card_config.py::test_main_passes_loaded_config_to_call_card_host`) is pre-existing and environment-specific: a real `python3.14 -m iris.daemon` process (pid 689129) is running on this shared dev box and holds the daemon's exclusivity flock, which this test doesn't mock around. Independently reproduced the identical failure on a plain, unmodified `origin/main` checkout in an isolated worktree (`git worktree add ... origin/main --detach`) — same test, same error, same pid — confirming it is not a regression introduced by this branch. This matches what both the builder (ti-pkt2r.1) and reviewer (ti-vvkxi) already documented independently.

---

## Verdict: **PASS**
