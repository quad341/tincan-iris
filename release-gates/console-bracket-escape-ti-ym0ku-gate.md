# Release Gate: console-bracket-escape-ti-ym0ku

**Bead:** ti-ym0ku — needs-deploy: console keybinding-hint bracket escape fix (from:ti-de3zw)
**Source bead:** ti-de3zw (review bead, CLOSED/PASS)
**Feature beads:** ti-40baw (implementation), ti-eu6d7 (tests)
**Branch:** `deploy/console-bracket-escape-ti-ym0ku`
**Gate commit:** (this commit)
**Date:** 2026-07-05

## Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | **PASS** | ti-de3zw closed with reviewer PASS verdict (reviewer-gm-wisp-anw8hc, 2026-07-04): "verified independently (isolated venv, disposable worktree, ancestry check on companion tests branch). All 5 sites correctly fixed, full suite clean, coverage complete via ti-eu6d7." |
| 2 | Acceptance criteria met | **PASS** | All AC items from ti-de3zw checked against the actual diff: all 5 sites (app.py:350,616,987,1163,1164) use the `rf"...\[x]..."` backslash-escape pattern consistent with ti-00jr4.3 precedent; app.py:350 (trickiest — key fully inside the tag, no separate text node) confirmed correct for both digit keys (current production values) and hypothetical lowercase-letter keys; companion tests branch verified as a clean single-commit ancestor; fresh grep sweep for other unescaped sites confirmed clean; out-of-scope dynamic-content sites (app.py:990 etc., filed as ti-9s84e) correctly excluded from this fix |
| 3 | Tests pass | **PASS** | 1751 passed, 3 xpassed, 1 failed (full suite, this branch, re-run independently). The 1 failure (`test_daemon_call_card_config.py::test_main_passes_loaded_config_to_call_card_host`) is the same pre-existing environmental flake documented in the immediately-preceding sibling gate (`jit-error-hint-ti-03yy3-gate.md`): a genuinely live `iris daemon` process (confirmed via `ps -p 689129` → real `/usr/bin/python3.14 -m iris.daemon`, PPID 2008) holds the daemon's OS-level singleton lock this un-isolated test depends on being free. Re-ran the single test in isolation — identical failure, identical PID, confirming an externally-running process rather than a leaked/flaky test artifact. Zero file overlap between this bead's 2 commits (`iris/console/app.py`, `tests/test_console_app.py`, `tests/test_incoming_call_panel.py`) and the failing test's module (`iris/daemon/__main__.py`, `tests/test_daemon_call_card_config.py`). This exact failure class (daemon exclusivity/lock) is already independently tracked by in-flight beads ti-fcack/ti-qlbi0/ti-2pbao elsewhere in this rig — not a new finding |
| 4 | No high-severity findings open | **PASS** | ti-de3zw review found zero blocking findings. One informational/LOW finding (dynamic-content-into-markup pattern recurring at other call sites) filed separately as ti-9s84e (P3, builder backlog) — explicitly out of scope for this fix, not blocking |
| 5 | Final branch is clean | **PASS** | `git status --short` clean except pre-existing untracked worktree infra (`.gc/`, `.gitkeep`), not part of this change |
| 6 | Branch diverges cleanly from main | **PASS** | Built off current `origin/main` tip (`1b176e5`); exactly 2 commits ahead, 0 behind (`git log origin/main..HEAD` / `git log HEAD..origin/main`). One cherry-pick conflict occurred during assembly (append/append collision in `tests/test_console_app.py`), resolved via mechanical concatenation after confirming via all 3 git conflict stages that the merge-base content between markers was empty — i.e. a genuine non-overlapping addition, not a real content dispute |
| 7 | Single feature theme | **PASS** | Both commits implement one feature (keybinding-hint bracket-escape fix, ti-40baw) plus its own dedicated regression coverage (ti-eu6d7); touches `iris/console/app.py` + `tests/test_console_app.py` + `tests/test_incoming_call_panel.py` only. 110 insertions, 5 deletions total |

## Verdict: PASS

## Commits on branch (vs origin/main)

| SHA | Message |
|-----|---------|
| `44771bc` | fix(console): escape literal [x] keybinding hints dropped by Rich markup (ti-40baw) |
| `a6ad5d1` | tests(console): regression coverage for [x] keybinding-hint escaping (ti-eu6d7) |

## Review summary (ti-de3zw)

**Correctness:** all 5 broken sites (app.py:350,616,987,1163,1164) fixed with the established `rf"...\[x]..."` escape pattern (same technique as ti-00jr4.3 precedent). app.py:350 (IncomingCallPanel choice buttons) was the trickiest site — the key sat entirely inside the markup tag with no separate text node — confirmed correct for both digit keys (current production values) and hypothetical lowercase-letter keys.
**Markup safety:** verified via `Content.from_markup(...).plain` that each fixed string now renders with literal brackets/key intact, rather than being silently swallowed by Rich/Textual's markup parser.
**Findings:** 1 LOW/informational (dynamic-content-into-markup pattern recurs at a few more call sites beyond the one originally flagged in ti-00jr4.3's review — app.py:571,666,678,685,990 — filed as follow-up ti-9s84e, P3, out of scope for this fix).
**Test coverage:** 4 new regression tests on `tests/console-bracket-escape-ti-eu6d7@1336aba`, covering all 5 sites, asserting against rendered/plain form (not raw string) so a regression to an unescaped bracket actually fails the test.

## Deploy sequencing note

This bead was held (claimed, not released) across multiple deployer sessions since 2026-07-03 pending strict sequential landing behind two sibling needs-deploy beads sharing the same source branch (`feat/console-crash-exit-message-ti-00jr4-2`): ti-m99u6 (ti-00jr4.2, crash-exit message) and ti-03yy3 (ti-00jr4.3, JIT error hint), whose own bead text explicitly required this bead's commit (`5142c23`) to be excluded from its deploy and to land as its own separately-reviewed/gated bead. A prior deployer session added `bd dep add ti-ym0ku ti-03yy3` to enforce this ordering in `bd ready` queries. Both prerequisites are now independently confirmed merged into `origin/main` (PR #151 for ti-m99u6, PR #159 for ti-03yy3). This deploy was built by pinning the exact prerequisite SHAs — `5142c23` (the ti-40baw fix) and `1336aba` (the ti-eu6d7 companion tests) — onto a fresh branch off the post-merge `origin/main` (`1b176e5`), not by checking out the shared multi-bead branch wholesale. One cherry-pick conflict occurred in `tests/test_console_app.py` (an append/append collision between PR #159's already-merged JIT-error-hint tests and this bead's own new tests at the same tail-of-file insertion point) and was resolved via mechanical concatenation after confirming via `git ls-files -u`/`git show :N:` that the merge-base content between conflict markers was empty — i.e. both sides purely appended non-overlapping content with no genuine dispute. Once this bead closes, ti-4sy3b (console markup-escaping fix + ARM TRUST gap, same shared branch) becomes unblocked.
