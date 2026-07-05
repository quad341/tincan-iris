# Release Gate: call-card-render-markup-escape-ti-dfssk

**Bead:** ti-dfssk — needs-deploy: call_card.py render() markup-escaping fix (from:ti-cngr5)
**Source bead:** ti-cngr5 (review bead, CLOSED/PASS)
**Feature bead:** ti-z1utm (builder fix, closed)
**Branch:** `deploy/call-card-render-markup-escape-ti-dfssk`
**Gate commit:** (this commit)
**Date:** 2026-07-05

## Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | **PASS** | ti-cngr5 closed with reviewer PASS verdict: "Reviewed commit 444f886 on feat/callcard-after-data-layer-ti-hb2dx (builder's fix for ti-z1utm)... every dynamic/caller-derived segment... is correctly wrapped in rich.markup.escape()." Independently re-read the same notes directly from the bead (not just the deploy bead's summary of them) — verdict text matches verbatim. |
| 2 | Acceptance criteria met | **PASS** | Scope matches ti-z1utm exactly: escapes dynamic/caller-derived content in `call_card.py`'s three `Widget.render()` sinks not covered by ti-9s84e's earlier (app.py-scoped) audit — `CriticalFactCard`, `FactCard`, `ActionItemCard`, both display and edit-mode branches, same `rich.markup.escape()` pattern as the ti-9s84e precedent. `DisclosureCard.render()`'s `self._script` deliberately left unescaped — reviewer traced the data flow (`event.get("script")` ← `call_card_host.py`'s `_disclosure_script` property ← `cfg.call_card_disclosure_script`) and confirmed it is operator-config-sourced, not caller/STT-derived, matching the established ti-9s84e exemption. Confirmed by reading the actual diff on this branch, not just trusting the description. |
| 3 | Tests pass | **PASS** | `pytest -k call_card`: 42 passed, 1 failed — re-run independently on this branch, matches reviewer's own independently-reproduced count exactly. The 1 failure (`test_daemon_call_card_config.py::test_main_passes_loaded_config_to_call_card_host`) is the same pre-existing environmental daemon-singleton-lock flake documented on the two immediately-preceding sibling deploys (`jit-error-hint-ti-03yy3-gate.md`, `console-bracket-escape-ti-ym0ku-gate.md`): `iris daemon: another instance holds the lock (pid ...) — exiting`. Reviewer independently reproduced the identical failure against the pre-fix parent commit (444f886~1), confirming it predates and is unrelated to this diff. Zero file overlap between this bead's single changed file (`iris/console/call_card.py`) and the failing test's module (`iris/daemon/__main__.py`). `ruff check iris/console/call_card.py`: clean ("All checks passed!"), re-run independently on this branch. |
| 4 | No high-severity findings open | **PASS** | ti-cngr5 review found zero blocking findings. Reviewer ran their own independent exploit/fix demo (crafted `[bold red]INJECTED[/bold red]` payloads in `raw_text`/`normalized_value`/`description`/`owner`/`due_date`, fed rendered output through `Rich.Text.from_markup`): pre-fix, brackets silently swallowed and styling applied (genuinely exploitable); post-fix, literal brackets preserved verbatim across all 3 classes, both branches — exploit fully neutralized. One related but out-of-scope sink (`CallCardPanel.border_title`) already correctly filed separately as ti-ntufu, routed to builder — not part of this bead. |
| 5 | Final branch is clean | **PASS** | `git status --short` clean except pre-existing untracked worktree infra (`.gc/`, `.gitkeep`), not part of this change |
| 6 | Branch diverges cleanly from main | **PASS** | Built directly off current `origin/main` tip (`65030f1852591b66e338aae1972c90e140854ebc`); exactly 1 commit ahead, 0 behind. Cherry-picked commit `444f886` specifically (not branch tip `faaa7ef`, which carries one extra unrelated commit — a release-gate doc for the separate, already-shipped ti-5a8ke deploy, PR #162, merged as this same `65030f1` base) — zero conflicts, confirmed directly in this branch build, matching the reviewer's own pre-verification in a disposable worktree. |
| 7 | Single feature theme | **PASS** | One commit, one file: `iris/console/call_card.py`, 15 insertions(+), 14 deletions(-). Single concern (markup-escaping the three render() sinks) |

## Verdict: PASS

## Commits on branch (vs origin/main)

| SHA | Message |
|-----|---------|
| `0219eab` | fix(console): escape dynamic content in call_card.py render() markup sinks (ti-z1utm) |

(Cherry-picked from `444f886` on `builder/feat/callcard-after-data-layer-ti-hb2dx`, which has no tracking remote on `origin`.)

## Review summary (ti-cngr5)

**Correctness:** all dynamic/caller-derived segments in `CriticalFactCard`, `FactCard`, `ActionItemCard` — `raw_text`, `normalized_value`, edit buffers, `owner`/`description`/`due_date` and their edit-mode counterparts — wrapped in `rich.markup.escape()`, in both display and edit-mode branches.
**Deliberate exemption:** `DisclosureCard.render()`'s `self._script` is operator-config-sourced (traced to `cfg.call_card_disclosure_script`), not caller/STT-derived — correctly left unescaped, consistent with established precedent.
**Exploit verification:** independent crafted-payload demo confirmed the vulnerability was genuinely exploitable pre-fix and fully neutralized post-fix, across all 3 classes and both render branches.
**Coverage:** no new dedicated regression tests added for the `escape()` calls; existing 42-test suite passes unchanged. Judged non-blocking, consistent with the same codebase's established precedent for this exact fix class (ti-9s84e/ti-q1pee).

## Deploy sequencing note

Source commit `444f886` lives on `feat/callcard-after-data-layer-ti-hb2dx`, local to the builder's worktree with no `origin` tracking branch — fetched directly from the `builder` remote (`git fetch builder feat/callcard-after-data-layer-ti-hb2dx`). The branch tip (`faaa7ef`) is one commit ahead of the reviewed/deployed commit; that extra commit is an unrelated release-gate doc for a different, already-separately-shipped deploy (ti-5a8ke, PR #162) and was correctly excluded by cherry-picking `444f886` alone rather than taking the branch wholesale.
