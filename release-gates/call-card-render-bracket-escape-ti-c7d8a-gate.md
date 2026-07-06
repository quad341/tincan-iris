# Release Gate — Escape Textual-tokenizer-shaped bracket content in Call Card render()

Bead: ti-c7d8a (source: ti-lgxas)
Branch: `fix/markup-escape-content-sink-ti-kpidj`
Gate evaluated at commit: `9331849`

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | PASS | Reviewer PASS recorded on ti-lgxas (bead notes: adversarial verification against installed textual 8.2.8, OWASP walk, no security findings). Validator (ti-gx6rp) added 13-test regression suite on top, re-confirmed green. |
| 2 | Acceptance criteria met | PASS | Diff closes the silent-deletion bug for `$`/digit/percent-shaped bracket content (`[$50]`, `[50%]`, `[12345]`) in all 3 render() sinks (CriticalFactCard/FactCard/ActionItemCard) via `escape_for_content()`. DisclosureCard's operator-config-sourced script correctly left unescaped (not user data). |
| 3 | Tests pass | PASS | `pytest -q` on this commit: 1764 passed, 3 xpassed, 1 failed. The 1 failure (`test_daemon_call_card_config.py::test_main_passes_loaded_config_to_call_card_host`) is the pre-existing environmental daemon-pid-lock issue (tracked separately as ti-8wtzr), reproduced independently here — not a regression from this diff. `ruff check .` clean. |
| 4 | No high-severity review findings open | PASS | One follow-up filed from review (ti-o1l40, priority 3, cosmetic/contained backslash-escaping edge case) — already fixed and closed before this gate ran. Zero open findings of any severity. |
| 5 | Final branch is clean | PASS | `git status` clean, no uncommitted changes. |
| 6 | Branch diverges cleanly from main | PASS | `git merge-tree $(merge-base HEAD origin/main) HEAD origin/main` produces no conflict markers. Branch is exactly 2 commits ahead of origin/main (588b910, 9331849). |
| 7 | Single feature theme | PASS | One subsystem (Call Card console rendering), one fix (`escape_for_content()` + its 3 call sites) plus its own regression tests — no unrelated changes bundled. |

**Verdict: PASS.** Proceeding to push + PR, merge-request routed to mayor.

Note for whoever reconsiders `ti-46cnx` / `ti-m7x5v` (both stacked on this branch, blocked-by this bead in bd): bd's dependency link will auto-clear the moment this bead is closed, but closing here only means the PR is **open**, not merged. Re-verify the actual code has landed (`git merge-base --is-ancestor <588b910 or 9331849> origin/main`) before gating either of those beads — do not treat "ti-c7d8a closed" alone as sufficient.
