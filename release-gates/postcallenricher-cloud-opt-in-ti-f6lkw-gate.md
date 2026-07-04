# Release Gate: PostCallEnricher Cloud-Enrichment Opt-In Flag

**Bead:** ti-z9b84 (needs-deploy)
**Source review bead:** ti-f6lkw.3
**Branch:** `fix/postcall-enricher-cloud-opt-in-ti-f6lkw-1`
**Commit (feature):** `b09dc88`
**Commit (tests):** `6c50c70` (cherry-picked from `57774b6` on `gc-validator-82d59f3e5db0`)
**Gate evaluated:** 2026-07-03

---

## Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | **PASS** | ti-f6lkw.3 notes: `REVIEW VERDICT: pass` |
| 2 | Acceptance criteria met | **PASS** | See below; diff re-read directly against ti-f6lkw.1 criteria |
| 3 | Tests pass | **PASS** | 1634 passed, 3 xpassed, 0 failed (independently re-run on the assembled branch) |
| 4 | No high-severity findings open | **PASS** | Reviewer's one finding (cfg=None wiring gap) is informational/non-blocking, filed separately as ti-ajkht — 0 HIGH findings open |
| 5 | Final branch is clean | **PASS** | `git status` shows only pre-existing untracked worktree scaffolding (`.gc/`, `.gitkeep`), no source changes outstanding |
| 6 | Branch diverges cleanly from main | **PASS** | Branch is `origin/main` + 2 commits, fast-forward-able, no conflicts with `origin/main` |
| 7 | Single feature theme | **PASS** | One theme: opt-in config flag gating PostCallEnricher's cloud (Haiku) transcript egress, plus its test coverage |

**Overall gate: PASS**

---

## Branch assembly (read before re-deriving)

`ti-f6lkw.1`'s fix (`b09dc88`) and `ti-f6lkw.2`'s tests (`57774b6`) were built in separate worktrees. `57774b6` lives on `gc-validator-82d59f3e5db0`, a reused validator session branch whose tip also carries an **older, unrelated** commit `71a67b4` ("PostCallEnricher + TranscriptStore validator suite", ti-rnlqo.5.5, dated 2026-06-30, not an ancestor of `b09dc88`, not on `origin/main`). Opening a branch-to-branch PR from `gc-validator-82d59f3e5db0` would have shipped `71a67b4` unreviewed alongside this fix, so per the reviewer's explicit instruction (ti-f6lkw.3 notes), only `57774b6` was cherry-picked onto `fix/postcall-enricher-cloud-opt-in-ti-f6lkw-1`.

That cherry-pick is a **modify/delete conflict**, not a clean apply as anticipated: `tests/test_post_call_enricher.py` doesn't exist at `b09dc88` at all — it was created by the excluded `71a67b4` (8 baseline tests) and then extended by `57774b6` (+10 tests, 18 total, 381 lines). Resolution was mechanical, not a judgment call: git leaves `57774b6`'s full 381-line version in the tree on conflict; that content was verified byte-identical to `git show 57774b6:tests/test_post_call_enricher.py` before staging, so the resolution is "take theirs" with no reconciliation of competing edits (no other commit in this lineage touches the file). Result: `6c50c70`, "1 file changed, 381 insertions(+), create mode 100644" — a clean net-new file.

Separately, this deployer's own worktree branch (`gc-deployer-52a44aeb5e71`) turned out to be a reused session branch carrying unrelated, unpushed prior work (a completed disclosure-card deploy gate commit + a duplicate of the ti-rnlqo.5.5 test commit) — not used for this PR. Building instead directly on the builder's `fix/postcall-enricher-cloud-opt-in-ti-f6lkw-1`, which bases cleanly on current `origin/main` tip (`088b7da`).

---

## Acceptance Criteria (ti-f6lkw.1)

- [x] New Config field, flat on the main Config dataclass (`iris/config.py:62`): `call_card_cloud_enrichment_enabled: bool = False`, matching `haiku_enabled`'s style.
- [x] `PostCallEnricher.run()` checks `_cloud_enrichment_enabled(cfg)` before `_api_key()`/transcript/LLM access; when False, skips via the same no-crash log-and-return pattern already used for missing `api_key`.
- [x] Independent of `haiku_enabled` — separate field, no shared code path; tested explicitly (`test_cloud_enrichment_independent_of_haiku_enabled`).
- [x] Defaults to `False` on fresh installs / demo mode.
- [x] Documented in `docs/SETUP.md` ("Privacy — Call Card cloud enrichment" section).

---

## Test Results

```
python3 -m pytest tests/test_post_call_enricher.py -q   (on fix/postcall-enricher-cloud-opt-in-ti-f6lkw-1, post cherry-pick)
18 passed in 0.10s

python3 -m pytest tests/ -q
1634 passed, 3 xpassed, 2 warnings in 78.33s
```

Matches builder/validator/reviewer's independently-reported numbers exactly (1634/3/0).

---

## Lint

```
ruff check iris/config.py iris/capture/enricher.py    -> clean (matches reviewer's ti-f6lkw.3 finding)
```

Note: `ruff check tests/test_post_call_enricher.py` flags one pre-existing `F401` (unused `import pytest`) inherited from the excluded baseline commit `71a67b4` (ti-rnlqo.5.5) — confirmed present in `71a67b4`'s own version of the file, not introduced by `57774b6`'s new tests and not part of this bead's scope. Non-blocking; left as-is rather than editing code outside ti-f6lkw's scope.

---

## Review Finding

**[INFO, non-blocking] ti-f6lkw.3** — `CallCardHost` is constructed with `cfg=None` in `iris/daemon/__main__.py` (pre-existing since PR #129, not a regression from this change), so this new opt-in flag cannot yet be set to `True` via a real `config.toml` in production — it fails closed (safe) but is currently inert end-to-end. Filed separately as **ti-ajkht**, routed to builder, explicitly noted as not blocking this deploy.

---

## Branch Composition

| Commit | Description |
|--------|-------------|
| `b09dc88` | fix(capture): explicit opt-in flag for PostCallEnricher cloud egress (ti-f6lkw.1) |
| `6c50c70` | tests(capture): PostCallEnricher cloud-enrichment opt-in gating (ti-f6lkw.2) — cherry-picked from `57774b6` |
