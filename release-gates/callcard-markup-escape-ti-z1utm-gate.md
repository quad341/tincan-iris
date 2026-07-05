# Release Gate: escape rich.markup in call_card.py render() sinks (ti-z1utm)

**Date:** 2026-07-05
**Deploy bead:** ti-utkci
**Source bead:** ti-z1utm (fix) / ti-c2dbo (review)
**Branch:** `fix/callcard-markup-escape-ti-z1utm` (cut fresh from `origin/main`)
**Commit evaluated:** `5754568` (cherry-pick of `faaa7ef`, byte-identical patch-id to `444f886` on `feat/callcard-after-data-layer-ti-hb2dx`)

## Deploy sequencing note

`faaa7ef`'s parent on its source branch (`6cc36e3`, ti-6a1y3 "post-call recap
generator") is not yet merged to `origin/main` (its own needs-deploy bead
ti-zd5os is `deferred`). Independently confirmed `6cc36e3` touches zero lines
of `iris/console/call_card.py`, so this fix was cherry-picked directly onto a
fresh branch off `origin/main` (tip `65030f1`) rather than deploying the full
source branch — avoids bundling deferred, unrelated work. Cherry-pick applied
with **zero conflicts**.

## Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | PASS | ti-c2dbo closed with REVIEW VERDICT: PASS (2026-07-05, tincan-iris/reviewer) |
| 2 | Acceptance criteria met | PASS | Independently re-read the cherry-picked diff: all 3 `Widget.render()` sinks (`CriticalFactCard`, `FactCard`, `ActionItemCard`, display + edit-mode branches) wrap dynamic/STT-derived fields in `rich.markup.escape`. `DisclosureCard.render()`'s operator-configured script correctly left unescaped (different trust boundary). `CallCardPanel.border_title` correctly out of scope (different sink class, tracked separately as ti-ntufu). |
| 3 | Tests pass | PASS | Re-ran the call_card test surface independently on this branch: `tests/test_call_card_pure.py`, `test_call_card_panel.py`, `test_call_card_host.py`, `test_call_card_finalize_writeback.py`, `test_daemon_call_card_config.py`, `test_daemon_core_import_no_callcard.py` → **37 passed, 1 failed**. The failure (`test_main_passes_loaded_config_to_call_card_host`) reproduces the same pre-existing/environmental signature already tracked across ti-ym0ku/ti-fcack/ti-qlbi0/ti-2pbao — a real `iris.daemon` process (pid 689129) holding a singleton lock on this shared machine. Diff touches only `iris/console/call_card.py` rendering; no plausible relation to daemon lock acquisition. |
| 4 | No high-severity review findings open | PASS | Reviewer found zero HIGH findings. One non-blocking coverage gap (no committed regression test for the `escape()` behavior) tracked via companion bead ti-u4ngs (routed to validator, non-blocking per rig convention). |
| 5 | Final branch is clean | PASS | `git status` on `fix/callcard-markup-escape-ti-z1utm` shows no uncommitted/staged changes to tracked files (worktree contains pre-existing untracked leftover bead-worktree directories from prior sessions, unrelated to and not part of this branch's commits). |
| 6 | Branch diverges cleanly from main | PASS | Branch cut directly from `origin/main` tip (`65030f1`); cherry-pick of `faaa7ef` applied with zero conflicts. `git diff` confirms the single-commit diff is exactly the 1-file, +15/-14 escape-only change. |
| 7 | Single feature theme | PASS | Single file (`iris/console/call_card.py`), single concern (markup-injection hardening for STT-derived text), same pattern already shipped for `app.py` in ti-9s84e. |

## Conclusion

Gate **PASS**. Proceeding to push `fix/callcard-markup-escape-ti-z1utm` and open a PR against `main`.
