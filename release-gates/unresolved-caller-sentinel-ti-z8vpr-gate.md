# Release Gate: unresolved-caller writeback via SENTINEL_CONTACT_ID substitution

Bead: ti-z8vpr (from ti-c37a9 review, ti-llzx9 architecture spec, ti-hb2dx data layer)
Branch: `deploy/unresolved-caller-sentinel-ti-z8vpr`
Base: `origin/main` @ `b0b827b`

## Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | PASS | ti-c37a9 (CLOSED): "Review verdict: PASS" — line-by-line diff verification against ti-llzx9, OWASP walk clean, independent test re-run in a disposable worktree. No blocking findings. |
| 2 | Acceptance criteria met | PASS | Diff (4 files, 26 insertions, 21 deletions) verified directly against architect spec ti-llzx9 §3.1–§4: SENTINEL_CONTACT_ID substitution in `engine.py::on_call_connected` and `call_card_host.py::finalize_writeback`; `_pending_caller_number` lifecycle added to `HandlingEngine` (set/cleared alongside `_pending_contact`); `caller_number` surfaced via `store.py::get_call_card` and persisted through `after_store.py`'s idempotent `PRAGMA table_info`/`ALTER TABLE` migration + `insert_call_log`. Exact match, no deviations. Zero changes to `iris/roster.py` (confirmed via diff). |
| 3 | Tests pass | PASS | Independently re-run in this worktree (confirmed `iris` resolves here, not a stale editable install). Targeted suite (`test_after_store`, `test_capture_store`, `test_call_card_host`, `test_daemon_tcc_mes`, `test_daemon_api_cc`): 66/66 passed. Broader suite (`daemon or capture or engine or roster`): 292 passed, 1 failed — `test_daemon_call_card_config.py::test_main_passes_loaded_config_to_call_card_host`, failure cause "another instance holds the lock (pid 689129)". Same PID independently cited by both the builder's and reviewer's own test runs — confirmed pre-existing environmental flake (shared-machine daemon singleton lock), not a regression. `ruff check` on all 4 changed files: all checks passed. |
| 4 | No high-severity review findings open | PASS | Reviewer (ti-c37a9): "No blocking findings." Two informational-only observations (silent sentinel-attribution log removal; shared-bucket `contact_fact` collision) are both explicitly spec-directed and pre-accepted by the architect's own Risks table (ti-llzx9 §7), not open findings. |
| 5 | Final branch is clean | PASS | Working tree clean after this gate commit. |
| 6 | Branch diverges cleanly from main | PASS | `git merge-base HEAD origin/main` == current `origin/main` tip == current `HEAD`; branch cut fresh from `origin/main` with only this bead's diff applied on top. |
| 7 | Single feature theme | PASS | Single fix to the Call Card AFTER writeback pipeline (4 files, all in the capture/daemon writeback path). No unrelated feature bundled. |

## Notes

New decision-branch logic (`on_call_connected` substitution, `finalize_writeback` substitution, `caller_number` plumbing) has no dedicated test coverage yet by design — coverage is tracked separately in needs-tests bead ti-v8474 (unclaimed, 6-item plan), already accepted as sufficient by the reviewer.
