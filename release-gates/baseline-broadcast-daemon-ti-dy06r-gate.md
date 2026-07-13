# Release Gate: Daemon broadcast of baseline health transitions to console (ti-dy06r / ti-pugo3.3.1)

**Date:** 2026-07-13
**Deploy bead:** ti-dy06r
**Source bead:** ti-csge4 (review)
**Branch:** `deploy/baseline-broadcast-daemon-ti-dy06r` (stacked on `deploy/degradation-notify-sink-none-guard-ti-26ad0`, carrying commit `fd9968d` cherry-picked from `feat/baseline-broadcast-ti-pugo3-3-1`)
**Commit evaluated:** `cf99960`

## Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | PASS | ti-csge4 (reviewer tincan-iris/reviewer) closed PASS |
| 2 | Acceptance criteria met | PASS | `DaemonAPI._on_baseline_transition` added (mirrors the existing `_on_posture_changed` pattern), broadcasts a `baseline` event shaped like `_baseline_snapshot()`'s output via a new shared `_status_payload()` helper; composed alongside (not replacing) `degradation_notify.on_baseline_transition` so desktop notifications from ti-26ad0 keep firing unchanged |
| 3 | Tests pass | PASS | `pytest -q tests/`: 1870 passed, 1 pre-existing unrelated failure, 3 xpassed — identical count to ti-26ad0's own gate, since this commit adds no new tests (coverage explicitly deferred to a follow-up bead, see Discovery) |
| 4 | No high-severity findings | PASS | No open high-severity findings; ruff clean; broadcast payload is the same shape already exposed via the existing status command over a local socket (mode 0600, unchanged) — no new external surface |
| 5 | Final branch is clean | PASS | Working tree clean at `cf99960`; no uncommitted content |
| 6 | Branch diverges cleanly from main | PASS | Cherry-pick applied with zero conflicts on top of the ti-26ad0 stacked base |
| 7 | Single feature theme | PASS | One cohesive theme: daemon-side broadcast of baseline transitions to the console (`api.py` + `__main__.py` wiring only) |

## Discovery

This bead's branch (`feat/baseline-broadcast-ti-pugo3-3-1`) was built on top of the same pre-guard-fix commit (`345ea7a`) as ti-26ad0, and its `__main__.py` diff composes a closure that fires *both* `degradation_notify.on_baseline_transition` *and* this bead's new console broadcast — meaning it has a genuine content dependency on ti-26ad0's wiring being present, not just a shared ancestor. Per the sequencing note flagged in ti-26ad0's own gate, this was stacked directly on top of `deploy/degradation-notify-sink-none-guard-ti-26ad0` (rather than cut independently from `origin/main`) so the cherry-pick has the closure's other half to compose with. `fd9968d` applied with zero conflicts.

Diff scope: `iris/daemon/api.py` (+18/-2) and `iris/daemon/__main__.py` (+11/-2, extending the same closure ti-26ad0 introduced) — matches the bead description exactly (disjoint from ti-26ad0's own `degradation_notify.py`-only diff, confirming the "sibling, not superset" relationship the reviewer described).

Full suite: `pytest -q tests/` (top-level `tests/` explicitly) → **1870 passed, 1 failed, 3 xpassed** — identical to ti-26ad0's own count, since this commit adds no test files of its own. Test coverage for this feature (the dual-composition regression guard) is explicitly deferred to ti-pugo3.3.3 per the bead's own description, which the fresh `bd show` for `ti-0lw2d`'s notes confirm has since landed as 37 new tests (`tests/test_health_panel.py` + `tests/test_baseline_broadcast_composition.py`) — not part of this specific commit's gate, but will surface further down this stack. The one failure, `tests/test_daemon_call_card_config.py::test_main_passes_loaded_config_to_call_card_host`, is the same pre-existing environmental daemon-PID-lock issue (tracked as ti-8wtzr), confirmed unrelated. `ruff check iris/ tests/ scripts/` clean.

The bead's own non-blocking informational note (the composed closure has no per-listener exception isolation, unlike `PostureManager._broadcast`'s precedent) is carried forward as-is — currently unreachable in production, a bead-sanctioned trade-off, not a gating concern.

**Deploy-sequencing note carried forward:** `ti-0lw2d` (Console baseline health pill + Health panel) reads the `baseline` broadcast event this bead introduces, so it stacks on top of this branch next.

## Conclusion

Gate **PASS**. This PR should be opened against the ti-26ad0 PR's branch (stacked), carrying `fd9968d` only, and merged after ti-26ad0 lands.
