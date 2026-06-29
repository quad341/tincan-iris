# Release Gate: es re-ask phrasebook (ti-rcn9.2)

**Bead:** ti-yb9rc  
**Source review bead:** ti-wddl (closed, PASS)  
**Branch:** fix/test-fixes-ti-gxpt1.3-et9i  
**Reviewed commit:** 2b7416d (feat(brain): add es re-ask patterns to phrasebook, ti-rcn9.2)  
**Gate run:** 2026-06-29  
**Deployer:** tincan-iris/deployer

## Gate Checklist

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | ✅ PASS | reviewer-gm-3estv PASS on 2026-06-29 (ti-wddl) |
| 2 | Acceptance criteria met | ✅ PASS | See details below |
| 3 | Tests pass | ✅ PASS | 19/19 phrasebook tests; 1234+ total pass |
| 4 | No high-severity findings | ✅ PASS | Reviewer: all OWASP checks CLEAR; ruff clean |
| 5 | Final branch is clean | ✅ PASS | Only untracked gc artifacts |
| 6 | Diverges cleanly from main | ❌ **FAIL** | 33 conflict markers in 18 files |
| 7 | Single feature theme (commit scope) | ✅ PASS | 2b7416d touches only `iris/re_ask_phrasebook.py` |

**Overall: FAIL** — Criterion 6 blocks deployment.

---

## Criterion 2 — Acceptance Criteria

ti-rcn9.2 scope (commit 2b7416d — `iris/re_ask_phrasebook.py`):

- [x] Spanish phrases added to `_PATTERNS['es']`: ¿Qué?, Perdón, ¿Puede repetir eso?, Disculpe, No escuché, Eh (+ variants)
- [x] `supported_languages()` returns `frozenset({'en', 'es'})` — immutable API
- [x] pod[eé]s covers Rioplatense 'podés' variant — regional coverage
- [x] `re.IGNORECASE` + Unicode accented chars: safe (Python Unicode case folding correct for ó/é/ú/í)
- [x] English fallback preserved — no regression
- [x] Config.language_set filter deferred to ti-140k (explanatory comment in place)
- [x] 19 phrasebook unit tests pass (en + es patterns, long-utterance guard, supported_languages)

Source: ti-wddl review notes (reviewer-gm-3estv, 2026-06-29).

## Criterion 3 — Test Run

```
python -m pytest tests/test_re_ask_phrasebook.py -v --tb=short
19 passed in 0.06s
```

Full suite per ti-rcn9.1 gate (re-ask-detector-ti-rcn9.1-gate.md):
```
1234 passed, 23 skipped, 3 xpassed, 0 failed
```

## Criterion 4 — Security / Findings

From ti-wddl reviewer:
- A03 Injection: CLEAR — string reaches re.Pattern.match() only; no shell/SQL/eval path
- A02 Sensitive data: CLEAR — no credentials or PII
- ReDoS: CLEAR — pattern anchored; no nested quantifiers; safe for short utterances
- ruff check . → 0 errors (confirmed by reviewer)

No HIGH or CRITICAL findings. LOW finding noted: `ruff format` would reformat 2 files
(missing blank line after module docstring), but CI only enforces `ruff check`.

## Criterion 5 — Branch Clean

Builder worktree status: only untracked `.gc/`, `.gitkeep`, `tincan_iris.egg-info/`
(gc artifacts, not project source). No uncommitted tracked-file changes.

## Criterion 6 — Diverges Cleanly from Main (FAIL)

**PR #113** (feat(brain): Reply.re_ask + Tier-0 re-ask detection, opened 2026-06-29)
shows `mergeable: CONFLICTING` / `mergeStateStatus: DIRTY`.

Local `git merge-tree` confirms: **33 conflict markers across 18 files**.

Conflicting paths (branch vs origin/main):
- `.github/workflows/ci.yml`
- `iris/_kokoro_server.py`
- `iris/brain.py`
- `iris/console/app.py`
- `iris/console/contacts.py`
- `iris/console/list_view.py`
- `iris/roster.py`
- `iris/up.py`
- `iris/voice/__init__.py`
- `tests/test_iris_up.py`
- `tests/test_list_store.py`
- `tests/test_pipecat_stt.py`
- `tests/test_pipecat_tts.py`
- `tests/test_roster.py`
- `tests/test_roster_migration.py`
- `tests/test_stt.py`
- `tests/test_tier0.py`
- `tests/test_tts.py`

Note: commit 2b7416d itself touches only `iris/re_ask_phrasebook.py`, which is
**not** in the conflict list. Conflicts originate from other accumulated commits on
`fix/test-fixes-ti-gxpt1.3-et9i` (ti-rcn9.1, ti-rcn9.3, voice catalogue,
ProfileResolver, roster migration, console, etc.) that conflict with recent main
merges (PRs #106, #108, #109, #111, #112 and subsequent).

**Resolution required:** builder must rebase `fix/test-fixes-ti-gxpt1.3-et9i`
onto `origin/main`, resolve conflicts, and re-trigger deploy gate.

## Criterion 7 — Single Feature Theme

Commit 2b7416d touches only `iris/re_ask_phrasebook.py`: Spanish patterns + helper.
Single subsystem (brain/phrasebook). PASS for this commit.

Branch as a whole spans multiple features — see ti-rcn9.1 gate (criterion 7 note)
and PR #113 body for context on merge-scope delegation to mayor/mpr.
