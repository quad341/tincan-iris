# Release Gate: Degradation notifications + None-sink guard fix (ti-26ad0 / ti-pugo3.2)

**Date:** 2026-07-13
**Deploy bead:** ti-26ad0
**Source beads:** ti-h2y2j (base feature review), ti-kbbhr (follow-up fix review)
**Branch:** `deploy/degradation-notify-sink-none-guard-ti-26ad0` (cut from `origin/main` at `3071105`, carrying commits `345ea7a`, `41b22a9`, `3c8297a` cherry-picked from `fix/degradation-notify-sink-none-guard-ti-ngtmb`)
**Commit evaluated:** `8b9456f`

## Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | PASS | ti-h2y2j (base feature) and ti-kbbhr (follow-up None-sink guard) both closed PASS by reviewer tincan-iris/reviewer |
| 2 | Acceptance criteria met | PASS | Edge-triggered desktop notification on baseline green→non-green transitions naming the failed check(s) + doctor fix line; single quiet confirmation on recovery; red persists re-remind at most once/24h; `_notify_degraded`/`_notify_recovered` now guard against an unconfigured (`None`) sink |
| 3 | Tests pass | PASS | `pytest -q tests/`: 1870 passed, 1 pre-existing unrelated failure, 3 xpassed (see Discovery for reconciliation against the bead's original 1778-passed evidence) |
| 4 | No high-severity findings | PASS | No open high-severity findings; ruff clean on all touched files; `DesktopNotifySink.notify` uses list-form `subprocess.run`, no `shell=True`, no injection risk |
| 5 | Final branch is clean | PASS | Working tree clean at `8b9456f`; no uncommitted content |
| 6 | Branch diverges cleanly from main | PASS | Cut directly from current `origin/main` tip (`3071105`); cherry-picks applied with zero conflicts |
| 7 | Single feature theme | PASS | One cohesive theme: degradation notifications + the None-sink guard fix that hardens them, plus their own regression tests. The guard fix is not independently deployable from the feature it guards |

## Discovery

`3c8297a` (on `fix/degradation-notify-sink-none-guard-ti-ngtmb`) supersedes the originally-targeted `345ea7a` (on `feat/degradation-notify-ti-pugo3-2`) per the reviewer's own retargeting note — the fix branch is a strict superset containing the base feature commit, the validator's test commit, and the new guard fix. Cherry-picked all three in sequence (`345ea7a` → `41b22a9` → `3c8297a`) onto a fresh branch cut from current `origin/main`, rather than rebasing the original branch, since `fix/degradation-notify-sink-none-guard-ti-ngtmb`'s early history duplicates content already merged to `origin/main` via PR #171 (confirmed via matching `git patch-id` on both sides in the bead's own evidence). All three cherry-picks applied with zero conflicts.

Diff scope: `iris/daemon/__main__.py` (+9/-6, wiring), `iris/daemon/degradation_notify.py` (new, 86 lines), `iris/daemon/heartbeat.py` (+6/-... minor), `tests/test_degradation_notify.py` (new, 295 lines, 27 tests) — matches the bead description exactly. The guard fix itself is exactly two 2-line `if _notify_sink is None: return` additions at the top of `_notify_degraded`/`_notify_recovered`, nothing else.

Full suite: `pytest -q tests/` (top-level `tests/` explicitly, avoiding sibling `ti-*-needs-deploy-*` nested worktree directories) → **1870 passed, 1 failed, 3 xpassed**. This does not match the bead's own original evidence (1778 passed) at face value, so reconciled explicitly: independently verified plain `origin/main` today (via a disposable detached worktree at the same `3071105` tip) runs **1843 passed, 1 failed, 3 xpassed** on its own — main has organically grown by ~65 tests via unrelated PRs merged over the past week since ti-h2y2j/ti-kbbhr's evidence was written (2026-07-05/06). Adding this branch's 27 new tests (`tests/test_degradation_notify.py`, all from `41b22a9`) to that baseline gives exactly 1843 + 27 = 1870, matching this run precisely. Not a regression — fully explained by main's growth plus this branch's own additive test commit. The one failure, `tests/test_daemon_call_card_config.py::test_main_passes_loaded_config_to_call_card_host`, is the same pre-existing environmental daemon-PID-lock issue (tracked as ti-8wtzr) confirmed identical on plain `origin/main` and unrelated in every prior gate this session. `ruff check iris/ tests/ scripts/` clean.

Concurrency safety (module-level globals in `on_baseline_transition`) and the guard-placement design question raised by the builder were both verified directly against source per the bead's own evidence and are not re-litigated here — no further findings.

**Deploy-sequencing note carried forward:** `ti-dy06r` (Daemon broadcast of baseline health transitions) is a sibling deploy bead based on the same pre-guard-fix commit (`345ea7a`) but touching disjoint files (`api.py` + `__main__.py` vs. this bead's `degradation_notify.py` only). `ti-dy06r`'s `__main__.py` diff composes a closure alongside this branch's `degradation_notify.on_baseline_transition` wiring, so it has a real content dependency on this branch's tip, not just a shared ancestor — it will be stacked on top of this deploy branch rather than cut independently from `main`.

## Conclusion

Gate **PASS**. Opening PR against `main` carrying `345ea7a` + `41b22a9` + `3c8297a`.
