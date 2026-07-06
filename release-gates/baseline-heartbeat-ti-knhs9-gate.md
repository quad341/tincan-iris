# Release Gate: baseline-heartbeat-ti-knhs9

**Bead:** ti-knhs9 — needs-deploy: baseline heartbeat engine
**Source bead:** ti-ctqc6 (review bead, CLOSED/PASS)
**Feature beads:** ti-pugo3.1 (baseline heartbeat engine, feat), ti-hxqpz (test coverage, needs-tests)
**Branch:** `deploy/baseline-heartbeat-ti-knhs9`
**Gate commit:** (this commit)
**Date:** 2026-07-05

## Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | **PASS** | ti-ctqc6 closed with reviewer PASS verdict. Full notes read directly from the bead (not summarized): reviewer walked the entire diff against every FR/NFR in the architecture doc section-by-section (§4, §5.1-§5.7, §11), confirmed the builder's own flagged judgment calls (UNKNOWN-counts-as-red aggregation, stable check-name identity for check_baseline_capabilities()) against the spec and accepted both. Verdict: "No blockers. Passing to deploy." |
| 2 | Acceptance criteria met | **PASS** | ti-pugo3.1 carries no separate formal acceptance-criteria field; scope is specified via the architecture doc referenced in the bead. Reviewer's spec-compliance walk (see above) confirms the shipped diff matches the doc's specified interval (90.0s per §4/§5.5 — the bead's own description prose saying "60s" is loose paraphrasing of the epic's 60-120s band, not a discrepancy in the code), the aggregation semantics (§5.1), and the daemon wiring (DaemonAPI.is_healthy()/set_heartbeat()/_baseline_snapshot(), construction/start ordering, concurrency + timeout + retry behavior, §5.2-§5.7) exactly. |
| 3 | Tests pass | **PASS** | `pytest -q tests/` (scoped explicitly to this repo's own top-level tests dir — see worktree note below): 1817 passed, 3 xpassed, 1 failed in 116.51s. The 1 failure (`test_daemon_call_card_config.py::test_main_passes_loaded_config_to_call_card_host`, "iris daemon: another instance holds the lock (pid 689129) — exiting") is the same pre-existing environmental daemon-singleton-lock flake documented on prior sibling deploys, reproducing against the identical live process (pid 689129) still holding the lock in this dev environment — unrelated to this branch's files (`iris/daemon/heartbeat.py`, `iris/doctor.py`, `iris/daemon/api.py`, `iris/daemon/__main__.py`, `iris/tincand_status.py`, `iris/audio/endpoint.py`, `iris/up.py`). `ruff check` on all touched/new files: clean ("All checks passed!"). |
| 4 | No high-severity findings open | **PASS** | ti-ctqc6 review found zero blocking findings. Reviewer's independent OWASP/§11-controls walk: no `shell=True`, no new listener/socket, `daemon.sock` permissions untouched, no user-controlled input reaches any new subprocess/D-Bus call, no secrets touched. Two minor, explicitly non-blocking observations on record (not gating): (1) `iris/doctor.py:_tincand_unit_active()` duplicates a systemctl call `check_services()` already makes in the same tick — harmless, ~ms cost every 90s, missed-reuse opportunity only; (2) if `get_tincand_status()` exhausts its 2 retries, the exception propagates out of `check_baseline_capabilities()` before `_check_ambient_aec()` runs that tick, dropping ambient-AEC granularity from the per-check list during exactly the periods an operator would want it most (aggregate still correctly reds out via the synthetic UNKNOWN catch, so nothing is silently hidden) — inherited verbatim from the architect's own §5.3 snippet, flagged as a possible future architect follow-up rather than a builder deviation. |
| 5 | Final branch is clean | **PASS** | `git status --short` clean except pre-existing untracked worktree infra (`.gc/`, `.gitkeep`, and unrelated stray bead directories/gate files left over from other sessions in this shared worktree), none of which are part of this change. |
| 6 | Branch diverges cleanly from main | **PASS** | Merge-base with `origin/main`: `b0b827b52281e5c5bde63224ae38a0fd2cd1a1f9`. `origin/main` has since advanced to `b9e5c4f` (PR #169, unrelated Call Card markup-escaping work merged concurrently by other deploys) — `git merge-tree --write-tree HEAD origin/main` produced a clean merged tree with no conflict markers (exit 0), confirming no file overlap: this branch touches only `iris/daemon/*`, `iris/doctor.py`, `iris/audio/endpoint.py`, `iris/up.py`, `iris/tincand_status.py`, and `tests/*`, disjoint from the concurrently-merged `iris/console/*` changes. |
| 7 | Single feature theme | **PASS** | Four commits, all baseline-heartbeat: one prerequisite refactor (shared D-Bus status helper consolidation, needed by both `doctor.py` and the new heartbeat engine), the feat itself, a self-caught fix (missing `"failing"` key in the status snapshot), and the bead's own follow-up test-coverage commit (ti-hxqpz). No unrelated changes. |

## Verdict: PASS

## Commits on branch (vs origin/main merge-base `b0b827b`)

| SHA | Message |
|-----|---------|
| `eaf5a09` | refactor(iris): consolidate tincand D-Bus status query into shared helper |
| `bf98fbe` | feat(daemon): baseline heartbeat engine — periodic checks, cached BaselineStatus (ti-pugo3.1) |
| `310709c` | fix(daemon): add missing "failing" key to baseline status snapshot |
| `c2074b0` | test(daemon): add coverage for baseline heartbeat engine (ti-hxqpz) |

14 files changed, 1280 insertions(+), 61 deletions(-).

## Review summary (ti-ctqc6)

**Correctness:** heartbeat interval, aggregation semantics (UNKNOWN-counts-as-red), and check-name stability all verified against the architecture doc's §4/§5.1 and matched exactly, including two builder-flagged judgment calls that the reviewer confirmed were already specified in the doc rather than independent deviations.
**Wiring:** `DaemonAPI.is_healthy()`/`set_heartbeat()`/`_baseline_snapshot()` (including the self-caught `"failing"` key), construction/start ordering, `ThreadPoolExecutor` concurrency with 3.0s per-check enrichment timeout and per-future UNKNOWN isolation, and intra-tick D-Bus retry (2x/0.3s) all verified against §5.2-§5.7.
**Security:** full OWASP/§11-controls walk, no findings.
**Coverage:** shipped with zero test coverage by design, with the gap explicitly acknowledged and routed to a dedicated follow-up bead (ti-hxqpz) rather than left silent — that follow-up is now included on this same deploy branch.

## Worktree note

This shared deployer worktree has accumulated ~42 stale nested git worktrees from past deploy sessions, which breaks bare `pytest -q`/`make test` (recurses into every nested worktree's own `tests/` dir, producing duplicate module names and pure collection errors with zero tests actually run). Test results above were produced with `pytest -q tests/`, scoped explicitly to this repo's own top-level tests directory. Flagged separately to the mayor as a housekeeping item; not addressed as part of this deploy.
