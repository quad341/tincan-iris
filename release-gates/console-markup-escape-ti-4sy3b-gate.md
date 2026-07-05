# Release Gate: console-markup-escape-ti-4sy3b

**Bead:** ti-4sy3b — needs-deploy: console markup-escaping fix + ARM TRUST gap (from:ti-q1pee)
**Source bead:** ti-q1pee (review bead, CLOSED/PASS)
**Feature bead:** ti-9s84e (implementation — main sweep + ARM TRUST follow-up fix)
**Branch:** `deploy/console-markup-escape-ti-4sy3b`
**Gate commit:** (this commit)
**Date:** 2026-07-05

## Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | **PASS** | ti-q1pee closed with reviewer RE-REVIEW VERDICT: PASS (reviewer-gm-wisp-anw8hc). Two rounds: initial REQUEST-CHANGES caught one blocking gap (`_do_arm_trust`'s `name` local, aliased from `self._call_contact_name` ~500 lines from its origin, missed by the original sweep because it doesn't grep-match "caller_name"); builder fixed it as commit `0840ed3` (escapes at the single assignment point via `rich.markup.escape`); re-review confirmed the fix via the same `Text.from_markup` exploit demo (malicious contact name `"Bob [bold red]FAKE ALERT[/bold red]"`) and declared all blocking findings resolved |
| 2 | Acceptance criteria met | **PASS** | ti-9s84e's scope (escape dynamic content — caller identity, STT transcripts, LLM/brain/mayor reply text, daemon error/exception text — at the three confirmed markup-parsing sinks: `self._w()`/RichLog, `self.notify()`, `Static.update()`) verified against the actual diff for both commits. Reviewer independently enumerated ~90 call sites by hand rather than trusting the commit message's "full sweep" claim, found the one gap noted above, and confirmed the follow-up fix closed it with no new gaps. Internal/deterministic values (engine names, file paths, static command/skill registries, audio device names) correctly left unescaped — out of the bug's risk class |
| 3 | Tests pass | **PASS** | 1751 passed, 3 xpassed, 1 failed (full suite, this branch, independently re-run). The 1 failure (`test_daemon_call_card_config.py::test_main_passes_loaded_config_to_call_card_host`) is the same pre-existing environmental flake documented on the immediately-preceding sibling gates (`jit-error-hint-ti-03yy3-gate.md`, `console-bracket-escape-ti-ym0ku-gate.md`): a genuinely live `iris daemon` process (confirmed via `ps -p 689129` → real `/usr/bin/python3.14 -m iris.daemon`) holds the daemon's OS-level singleton lock this un-isolated test depends on being free. Zero file overlap between this bead's 2 commits (`iris/console/app.py` only) and the failing test's module (`iris/daemon/__main__.py`). Already independently tracked elsewhere in this rig (ti-fcack/ti-qlbi0/ti-2pbao) — not a new finding. Targeted suite (`test_console_app.py` + `test_console_panels_render.py` + `test_ride_along_console.py`): 136 passed, 0 failed |
| 4 | No high-severity findings open | **PASS** | The one MEDIUM/injection-adjacent blocking finding (ARM TRUST contact-name gap) was resolved by `0840ed3` and re-verified PASS. Two INFO-level items (`ActiveCallCard.show_card` sink; already-cleared internal/deterministic sites) were explicitly marked non-blocking/out-of-scope by the reviewer and not re-litigated here |
| 5 | Final branch is clean | **PASS** | `git status --short` clean except pre-existing untracked worktree infra (`.gc/`, `.gitkeep`), not part of this change |
| 6 | Branch diverges cleanly from main | **PASS** | Built off current `origin/main` tip (`65030f1`, post-#162); exactly 2 commits ahead, 0 behind (`git log origin/main..HEAD` / `git log HEAD..origin/main`). Both cherry-picks (`be9b44a`, `0840ed3`) applied with **zero conflicts** — auto-merged cleanly. This is notable: the source bead's own notes recorded that `be9b44a` did NOT cherry-pick cleanly onto `origin/main` in isolation as of 2026-07-04, because its three prerequisite commits (`418f24f`/ti-m99u6, `4c57ab1`/ti-03yy3, `5142c23`/ti-ym0ku) had not yet landed. All three have since merged (PR #151, #159, #161 respectively, all confirmed `state: MERGED` via `gh pr view`), which is why the same cherry-pick now applies clean |
| 7 | Single feature theme | **PASS** | Both commits implement one fix (dynamic-content markup-escaping in the console, ti-9s84e) touching only `iris/console/app.py`. 28 insertions, 27 deletions total. Neither `b40bf14` (daemon posture fix, ti-syhdb, separate file) nor `305bd16` (docs-only comment, ti-cha1h) was cherry-picked — confirmed unnecessary since the diff scope matches the two source commits exactly with no missing-context conflicts |

## Verdict: PASS

## Commits on branch (vs origin/main)

| SHA | Message |
|-----|---------|
| `a7d4924` | fix(console): escape dynamic content interpolated into markup=True strings (ti-9s84e) |
| `ae8e0d4` | fix(console): escape contact name in ARM TRUST messages (ti-9s84e review fix) |

## Review summary (ti-q1pee)

**Correctness:** all three confirmed markup-parsing sinks (`self._w()`/RichLog, `self.notify()`, `Static.update()`) audited by hand across ~90 call sites in `iris/console/app.py`. The one gap found (`_do_arm_trust`'s `name` local) was in the single most security-sensitive screen in the file — confirming trust-arming immediately before granting far-party admin access — and was demonstrated exploitable via `Text.from_markup` before the fix, and neutralized after.
**Findings:** one MEDIUM/injection-adjacent blocking finding, fixed and re-verified PASS. No HIGH findings. Two INFO items correctly scoped out.
**Test coverage:** targeted suite (`test_console_app.py`, `test_console_panels_render.py`, `test_ride_along_console.py`) 118 passed on both review rounds (now 136 passed post-merge of sibling deploys' own test additions); full suite consistent across both rounds, no regressions.

## Deploy sequencing note

This bead was held (claimed, not released) across many deployer sessions since 2026-07-03 pending strict sequential landing behind three sibling needs-deploy beads sharing the same source branch (`feat/console-crash-exit-message-ti-00jr4-2`): ti-m99u6 (ti-00jr4.2, crash-exit message — PR #151), ti-03yy3 (ti-00jr4.3, JIT error hint — PR #159), and ti-ym0ku (ti-40baw, keybinding bracket-escape — PR #161). All three are now independently confirmed `MERGED` via `gh pr view`. This deploy was built by pinning the exact prerequisite SHAs (`be9b44a`, `0840ed3`) onto a fresh branch off the post-merge `origin/main` tip, not by checking out the shared multi-bead branch wholesale — consistent with the deploy pattern already used for all three prerequisite beads. This closes out the full 4-bead sequential chain on this shared branch.
