# Release Gate: Escape Textual-tokenizer-shaped bracket content in app.py notify()/Static.update() sinks (ti-m7x5v)

**Date:** 2026-07-13
**Deploy bead:** ti-m7x5v
**Source beads:** ti-ikvfu/ti-dqxc1 (app.py escape fix), ti-l9arm (regression coverage)
**Branch:** `deploy/app-markup-escape-content-sink-ti-m7x5v` (cut from `origin/main` at `3071105`, carrying commits `4587e04` and `8b04e41` cherry-picked from their original review branches)
**Commit evaluated:** `ce94139`

## Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | PASS | ti-ikvfu (reviewer tincan-iris/reviewer) closed with independent verification against installed textual 8.2.8; all 27 app.py call sites confirmed swapped uniformly, import hygiene verified |
| 2 | Acceptance criteria met | PASS | All app.py `notify()`/`Static.update()` sinks (→ `Content.from_markup()`) now escape bracket-shaped content (`[$50]`/`[50%]`) via `escape_for_content()`, closing the same tokenizer-deletion gap already fixed for `call_card.py` in ti-kpidj/ti-c7d8a. `self._w()`/`log.write()` sinks (→ Rich's `Text.from_markup()`, different parser, not vulnerable) swapped too for import-hygiene consistency only, confirmed safe |
| 3 | Tests pass | PASS | `pytest -q tests/`: 1852 passed, 1 pre-existing unrelated failure, 3 xpassed (see Discovery) |
| 4 | No high-severity findings | PASS | No open high-severity findings on the source bead; ruff clean on all changed files |
| 5 | Final branch is clean | PASS | Working tree clean at `ce94139`; no uncommitted content |
| 6 | Branch diverges cleanly from main | PASS | Cut directly from current `origin/main` tip (`3071105`); cherry-picks applied with zero conflicts |
| 7 | Single feature theme | PASS | One cohesive theme: app.py's `escape_for_content()` call-site swap plus its own adversarial regression tests. Not independently deployable as two PRs (tests target the exact sinks the fix changes) |

## Discovery

Source branch `fix/app-markup-escape-content-sink-ti-dqxc1` (tip `4587e04`) was stacked on `588b910` (ti-c7d8a), which landed on `origin/main` via squash/merge-commit PR #169 as `b9e5c4f`. Verified `b9e5c4f` **is** an ancestor of current `origin/main` (`git merge-base --is-ancestor b9e5c4f origin/main`), confirming ti-c7d8a's content is genuinely on main — the individual pre-merge SHAs (`588b910`/`9331849`) are not ancestors by their original hashes (expected under squash/merge-commit semantics), so a plain rebase was not applicable. Cut a fresh branch from `origin/main` and cherry-picked only the true incremental delta:

```
git checkout -b deploy/app-markup-escape-content-sink-ti-m7x5v origin/main   # at 3071105
git cherry-pick 4587e04 8b04e41
```

Confirmed `588b910` itself is redundant against this fresh branch (test cherry-pick produces an add/add conflict on `iris/console/_markup.py`, which already exists on main via PR #169) — correctly excluded. Both real cherry-picks applied cleanly: `4587e04` touches only `iris/console/app.py`; `8b04e41` touches only `tests/test_app_markup_escape.py` (new file), no overlap.

`8b04e41` (ti-l9arm, validator) was included alongside the fix following the same fix+test bundling precedent set by PR #169/ti-46cnx, since it is regression coverage for `4587e04` specifically (9 new adversarial tests, each independently verified during authoring to fail against a simulated pre-fix revert via monkeypatched `escape_for_content`).

Full suite: `pytest -q tests/` (top-level `tests/` explicitly, to avoid collection errors from the many sibling `ti-*-needs-deploy-*` nested worktree directories present in this shared deployer worktree) → **1852 passed, 1 failed, 3 xpassed**. The one failure, `tests/test_daemon_call_card_config.py::test_main_passes_loaded_config_to_call_card_host`, is a pre-existing environmental issue unrelated to this change: `iris daemon: another instance holds the lock (pid 2353) — exiting`, confirmed present identically on a pristine `origin/main` checkout in an isolated scratch worktree before these commits are applied. `ruff check iris/ tests/ scripts/` clean on all changed files.

## Conclusion

Gate **PASS**. Opening PR against `main` carrying `4587e04` + `8b04e41`.
