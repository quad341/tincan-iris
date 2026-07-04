# Release Gate: Console diagnostics — log persistence, crash hooks, bug-filing, error copy (ti-oqlyk)

**Date:** 2026-07-04
**Bead:** ti-j05da (deploy) / source bead: ti-oqlyk / review: ti-1a4xy (PASS)
**Source commit:** `639df2054dc61e3fda33b46d92f86ee331387c6b` (feat/console-diagnostics-ti-oqlyk)
**Test commit (cherry-picked, NOT branch-merged):** `a948c438d9238f9130bd47e65efdba802c393bcd` (tests/test_console_app.py, tests/test_diagnostics.py only)
**Deploy branch:** `feat/console-diagnostics-ti-oqlyk` (639df20 + cherry-picked 83f1d6b)
**Reviewer:** tincan-iris/reviewer (ti-1a4xy) — PASS
**Deployer:** tincan-iris/deployer

**Context:** Implements FR1-FR3 of the console-diagnostics PRD (ti-w3n09) per the ti-qz990
architecture / ti-oqlyk implementation design: persistent (append+rotate) console log,
3-layer crash-diagnostics hook, manual "file a bug" action, and an additive OSC52+subprocess
clipboard copy.

**Note on test provenance:** The committed regression suite for this diff lives on branch
`tests/console-diagnostics-ti-94lrs`, but that branch's tip carries merge commit `4b9e08c`
pulling in unrelated, not-yet-merged commits (`6c3fde9`, `546212f`) from a different bead
chain (ti-ir12t/ti-s6kz3), from a shared/reused validator worktree. Per the reviewer's
explicit instruction (ti-1a4xy, Finding 5) and the source bead's own Action note, only the
isolated test commit `a948c43` was cherry-picked onto `639df20` — the contaminated branch
was never merged or pulled.

---

## Criteria Evaluation

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | **PASS** | ti-1a4xy: "REVIEW VERDICT (reviewer, 2026-07-04): PASS" — independently verified in a disposable worktree, every row of ti-qz990's FR/NFR traceability table checked against the actual code |
| 2 | Acceptance criteria met | **PASS** | FR1 (persistent + rotating log), FR2 (file-a-bug, manual + automatic), FR3 (additive clipboard copy, no silent failure) all confirmed against `iris/console/diagnostics.py` + `iris/console/app.py` directly by this deployer, matching reviewer's traceability check |
| 3 | Tests pass | **PASS** | Independently re-run in an isolated venv (not just re-quoting reported numbers): `1642 passed, 1 skipped, 3 xpassed` — the 1 skip is an unrelated pre-existing environmental gap. `ruff check .`: all checks passed |
| 4 | No high-severity review findings open | **PASS** | 4 findings recorded in ti-1a4xy, all explicitly LOW severity / non-blocking |
| 5 | Final branch is clean | **PASS** | `git status` clean after cherry-pick — only pre-existing, unrelated untracked artifacts, nothing staged/uncommitted from this diff |
| 6 | Branch diverges cleanly from main | **PASS** | `639df20` is a single clean commit on top of `origin/main` (`088b7da`); cherry-picking `a948c43` onto it applied with **zero conflicts** |
| 7 | Single feature theme | **PASS** | One feature commit touching exactly `iris/console/app.py` + `iris/console/diagnostics.py` (console diagnostics), one test commit touching exactly the two corresponding test files — one cohesive subsystem |

**Overall: PASS**

---

## Evidence

### Criterion 1 — Review PASS

Bead ti-1a4xy notes (reviewer, 2026-07-04):
> "REVIEW VERDICT (reviewer, 2026-07-04): PASS ... Independently verified in a disposable
> worktree (not just re-reading builder/validator claims): ruff clean on both files, and
> cherry-picking the validator's test commit a948c43 cleanly onto 639df20 alone gives full
> suite 1643 passed / 3 xpassed / 0 failed."

Verdict: **PASS**

### Criterion 2 — Acceptance Criteria (FR1-FR3 of ti-w3n09, per ti-qz990 architecture)

| FR | Description | Location | Status |
|----|-------------|----------|--------|
| FR1 | Persistent (append, not overwrite) console log, single-generation size-triggered rotation | `app.py::_open_log()` — `"w"` → `"a"`, `os.path.getsize` check + `os.replace` to `.1` | ✅ |
| FR2 | File-a-bug action, manual + automatic on crash | `diagnostics.py::write_bug_report()` — invoked by `[b] action_file_bug` and from every exception-hook path via `persist_crash` | ✅ |
| FR3 | Copy affordances, no silent clipboard failure | `_copy_text_to_clipboard()` — OSC 52 unconditional + wl-copy/xclip/xsel additive; "Copied (best-effort)." wording is a deliberate consequence of no delivery ack, not a regression | ✅ |
| NFR1-3 | Exception-safety, no hot-path cost, no behavior change to existing `[y]`/`_log_consent` | Confirmed by direct code read: every diagnostics.py function wrapped in a documented never-raise contract; rotation check is a single `stat()` at process start only | ✅ |

### Criterion 3 — Tests (independently re-run, not just re-quoted)

Isolated venv (not the shared global environment):
```
$ python -c "import iris; print(iris.__file__)"
.../deployer/ti-j05da-.../iris/__init__.py   # confirms no shadowing by another install

$ ruff check .
All checks passed!

$ pytest -q
1642 passed, 1 skipped, 3 xpassed in 83.56s
```
The 1 skip (`tests/test_tincan_messages.py:221: could not import 'dbus'`) is an
environment gap unrelated to this diff. Matches the reviewer's reported counts modulo
that pre-existing, unrelated skip.

### Criterion 4 — No high-severity findings

All 4 findings in ti-1a4xy are explicitly tagged LOW severity by the reviewer:
unguarded stderr fallback print, create-then-chmod perm window (improvement over prior
no-chmod behavior), unrestricted bug-reports directory listing (no real privilege
boundary in the single-user threat model), and an unlikely fd leak on chmod failure.
None block deploy per the reviewer's own verdict.

### Criteria 5-7 — Branch hygiene

- `git checkout feat/console-diagnostics-ti-oqlyk` → `639df20`, one commit ahead of
  `origin/main` (`088b7da`).
- `git cherry-pick a948c438d9238f9130bd47e65efdba802c393bcd` → applied clean, 0
  conflicts, exactly `tests/test_console_app.py` + `tests/test_diagnostics.py` (478
  insertions, 0 deletions) — the contaminated `tests/console-diagnostics-ti-94lrs`
  branch tip was never merged or pulled, per the reviewer's explicit instruction.
- Resulting branch: `639df20` + `83f1d6b`, 2 commits ahead of `origin/main`, working
  tree clean.

---

**Gate evaluated by:** tincan-iris/deployer
**Result:** PASS — proceeding to PR.
