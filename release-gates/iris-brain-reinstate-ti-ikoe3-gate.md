# Release Gate: iris-brain daemon reinstated — default install + bring-up ensure (ti-ikoe3)

**Date:** 2026-07-13
**Deploy bead:** ti-ikoe3
**Source beads:** ti-4zjar (review, install-services), ti-z4pnk (review, iris up bring-up), ti-kzkfv + ti-vvc9o (implementation, closed), ti-omwom (architecture, closed)
**Branch:** deploy/iris-brain-reinstate-ti-ikoe3
**Commits evaluated:** 435de9e, aaa73fe (cherry-picked from 4968fa6, 2ef8893 on feat/iris-brain-install-services-ti-kzkfv)

## Criteria

| # | Criterion | Result |
|---|-----------|--------|
| 1 | Review PASS present | ✅ Both commits reviewed + PASSED (ti-4zjar, ti-z4pnk); combined into one deploy bead per this rig's stacked-commits convention since they aren't independently deployable |
| 2 | Acceptance criteria met | ✅ Independently re-read both diffs against ti-omwom's FR-01–FR-05/NFR-01–NFR-03 — all confirmed directly in source, not just bead prose (see Discovery) |
| 3 | Tests pass | ✅ ruff clean; targeted tests/test_install_services.py + tests/test_iris_up.py = 49 passed; full suite 1843 passed / 1 pre-existing failure (ti-8wtzr) / 3 xpassed — exact match to today's verified main baseline, no regression |
| 4 | No open HIGH findings | ✅ None. Two disclosed non-blocking needs-tests gaps (ti-kiv1b, ti-hih1l), both independently confirmed genuine via diff inspection, both already filed and routed to validator per established convention |
| 5 | Final branch clean | ✅ 4 files touched total (_cli.py, install.py, up.py, test_iris_up.py), no stray changes |
| 6 | Branch diverges cleanly from main | ✅ `git merge-base --is-ancestor origin/main <branch>` confirmed — exactly 2 commits ahead, linear, no contamination |
| 7 | Single feature theme | ✅ Both commits implement one architecture (ti-omwom): reinstating iris-brain as a normally-managed, always-on unit |

## Discovery

Independently verified every claim in the bead against source rather than trusting bead prose alone, given the scope of this change:

- **ExecStart fix is real and pre-existing, not new in this bead**: confirmed `iris/services/iris-brain.service.tmpl` targets `python -m iris.daemon` (not the old `iris.voice` REPL) via direct read. `git log --follow` on the template shows the fix landed in **PR #120** (already merged, already live on main) — this bead does not touch the template at all, it only re-adds it to the default-install `UNITS` list. The regression guard added in `_validate_exec_starts()` (install.py) correctly asserts this by rendering the template and checking for `-m iris.daemon` in its `ExecStart=` line.
- **Network-egress posture is pre-existing, not newly granted by this bead.** The template already carries an explicit comment block: "iris-brain intentionally has NO IPAddressDeny — it needs outbound for: optional cloud Tier 2 (Haiku) calls, D-Bus (local but not loopback), calendar and web-search APIs." This scope decision was made and reviewed when the template was authored, not here. **What this bead actually changes** is the default install behavior: previously `_RETIRED_UNITS = ["iris-brain"]` meant the unit was actively stopped/disabled on every install; now `_RETIRED_UNITS = []` and iris-brain is a normal 4th managed unit, installed and started automatically unless the operator passes the new `--no-daemon` flag. That is a genuine first-time default-behavior change (opt-out instead of absent-by-default) even though the network-access scope itself isn't new.
- `install()`'s new `with_daemon: bool = True` param and `--no-daemon` CLI flag confirmed skip-only (does not stop/disable a pre-existing unit) by direct read of both `install.py` and `_cli.py`; matches the bead's own caveat, and the docstring states the manual-disable path (`iris daemon stop && systemctl --user disable iris-brain`) explicitly.
- NFR-02 transparency notice (printed once, only when `iris-brain` is newly installed) confirmed present and worded correctly in `install.py`, listing the same three network-egress reasons as the template comment.
- `iris/up.py`'s new bring-up step confirmed to reuse pre-existing, already-tested helpers (`_unit_known`, `_is_active`, `_start_service` — already exercised by the existing tincand/whisper/kokoro code paths at lines 106–183), and confirmed non-blocking on all three negative branches (not installed / inactive-start-fails) by direct read — matches the FR-04/FR-05 "warn, never fail bring-up" contract.
- Grepped all three touched files for `subprocess`/`shell=`: zero `shell=True` call sites; all list-form argv with constant unit-name strings, no user-controlled input reaches a shell. No new attack surface.
- Console's `DaemonProxy`/direct-mode fallback (`iris/console/app.py`) confirmed untouched by either commit (diff stat). `iris/daemon/` internals untouched. Scope boundary from ti-omwom respected.
- Two coverage gaps (bring_up's new 3-way branch; the regression-guard's negative path) independently confirmed genuine by re-reading the diffs for `test_iris_up.py` and `test_install_services.py` — neither test file gained coverage for the new logic in either commit. Both are already filed (ti-kiv1b, ti-hih1l), routed to validator, and explicitly disclosed as non-blocking by the reviewer (who hand-verified correctness by direct code reading) — same shape as this rig's established needs-tests-follow-up pattern used earlier this session (e.g. ti-pugo3.3.3 for ti-0lw2d).

**Guardrail note carried forward for mayor/operator:** this is the first deploy where `iris install-services` installs and starts an outbound-network-capable daemon (cloud Tier 2/Haiku, calendar, web-search) **by default**, with `--no-daemon` as the opt-out. The network-access scope itself was already decided and is unchanged (live on main since PR #120); what's new is the default-on install/start behavior. Nothing about this is silent — both the code (install-time console notice) and this gate call it out explicitly. Given the nature of this change, a critical notification and mail were sent to mayor before starting this gate evaluation (separate from this merge-request), so the change gets attention rather than blending into a routine batch of PRs.

## Conclusion

**Gate: PASS**

Next action: push branch, open PR against `main`, close bead, mail mayor a merge-request with the guardrail note given first-class prominence (not just noted in passing).
