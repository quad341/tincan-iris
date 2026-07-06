# Release Gate: border_title escape fix + backslash-algorithm fix (ti-46cnx)

**Date:** 2026-07-05
**Deploy bead:** ti-46cnx
**Source beads:** ti-ntufu/ti-yv2h2 (border_title fix), ti-o1l40/ti-btc9h (backslash-algorithm fix), ti-1jayi (regression coverage)
**Branch:** `deploy/escape-backslash-fix-ti-46cnx` (cut from `origin/main` at `b9e5c4f`, carrying commits `62e920b`, `2755ce9`, `aef887b` cherry-picked from their original review branches)
**Commit evaluated:** `c4ed825`

## Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | PASS | ti-yv2h2 and ti-btc9h both closed with independent empirical verification against real installed textual 8.2.8 (see those beads' notes) |
| 2 | Acceptance criteria met | PASS | `CallCardPanel.border_title` now escaped via `escape_for_content()`, closing the bracket-shaped-token deletion + fake-markup-injection gap on the production-wired sink; `escape_for_content()` backslash algorithm fixed (add exactly one backslash instead of double-then-add), eliminating stray-backslash-on-round-trip for content with a literal backslash before a bracket |
| 3 | Tests pass | PASS | `pytest -q tests/`: 1767 passed, 1 pre-existing unrelated failure, 3 xpassed (see Discovery) |
| 4 | No high-severity findings | PASS | No open high-severity findings on either source bead; ruff clean on all changed files |
| 5 | Final branch is clean | PASS | Working tree clean at `c4ed825`; no uncommitted content |
| 6 | Branch diverges cleanly from main | PASS | Cut directly from current `origin/main` tip (`b9e5c4f`); cherry-picks applied with zero conflicts |
| 7 | Single feature theme | PASS | One cohesive theme: `CallCardPanel.border_title` escaping + the `escape_for_content()` bug the fix depends on, plus its own regression tests. Not independently deployable as two PRs (2755ce9 fixes a bug in the helper 62e920b calls) |

## Discovery

Source branch `fix/escape-content-backslash-ti-o1l40` (tip `2755ce9`) was a linear stack on top of `588b910` (ti-c7d8a), which landed on `origin/main` via squash-merge PR #169 as `b9e5c4f`. Per squash-merge semantics, `588b910` is not an ancestor of `origin/main` even though its content is present, so a plain rebase was not applicable. Instead cut a fresh branch from `origin/main` and cherry-picked the two new commits plus the companion regression-test commit:

```
git checkout -b deploy/escape-backslash-fix-ti-46cnx origin/main   # at b9e5c4f
git cherry-pick 62e920b 2755ce9 aef887b
```

All three cherry-picks applied cleanly (no conflicts) — `62e920b`/`2755ce9` touch `iris/console/_markup.py` and `iris/console/call_card.py`, `aef887b` touches only `tests/test_call_card_panel.py`, none of which overlap with `b9e5c4f`'s own changes.

`aef887b` (ti-1jayi, validator) was included alongside the two fixes following the same fix+test bundling precedent set by PR #169, since it is regression coverage for `62e920b` specifically (3 new tests, each independently verified to fail against a simulated pre-fix revert).

Full suite: `pytest -q tests/` (top-level `tests/` explicitly, to avoid collection errors from the many sibling `ti-*-needs-deploy-*` nested worktree directories present in this shared deployer worktree) → **1767 passed, 1 failed, 3 xpassed**. The one failure, `tests/test_daemon_call_card_config.py::test_main_passes_loaded_config_to_call_card_host`, is a pre-existing environmental issue unrelated to this change: `iris daemon: another instance holds the lock (pid 689129) — exiting`, confirmed present identically on `origin/main` before these commits are applied. `ruff check` clean on all four changed files (`iris/console/_markup.py`, `iris/console/call_card.py`, `tests/test_call_card_panel.py`, plus the pre-existing `tests/test_call_card_markup_escape.py` re-run for the shared helper).

## Conclusion

Gate **PASS**. Opening PR against `main` carrying `62e920b` + `2755ce9` + `aef887b`.
