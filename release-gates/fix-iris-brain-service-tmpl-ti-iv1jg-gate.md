# Release Gate: fix-iris-brain-service-tmpl-ti-iv1jg

**Bead:** ti-iv1jg — Fix iris-brain.service.tmpl ExecStart iris.voice → iris.daemon (ti-s9mm.5.1)
**Source bead:** ti-yim2b (review bead, CLOSED/PASS)
**Commit:** a656739 (cherry-picked as d58dc50 on feat/fix-iris-brain-service-tmpl-ti-iv1jg)
**Branch:** feat/fix-iris-brain-service-tmpl-ti-iv1jg → origin/main
**Date:** 2026-06-30

## Gate Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | ✅ PASS | ti-yim2b notes: `REVIEW VERDICT: PASS` by reviewer-gm-dckpd |
| 2 | Acceptance criteria met | ✅ PASS | See below |
| 3 | Tests pass | ✅ PASS | 26/26 `test_install_services.py` pass (0.13s) |
| 4 | No HIGH-severity findings | ✅ PASS | Reviewer: style clean, security clean, no HIGH findings |
| 5 | Final branch clean | ✅ PASS | `git status` — no uncommitted changes to tracked files |
| 6 | Branch diverges cleanly | ✅ PASS | `git merge-base --is-ancestor origin/main HEAD` — clean linear divergence |
| 7 | Single feature theme | ✅ PASS | One file changed (iris/services/iris-brain.service.tmpl), one subsystem |

**Overall: PASS**

## Acceptance Criteria Verification

**AC1: ExecStart uses `iris.daemon` entrypoint**
```
ExecStart={REPO_PATH}/.venv/bin/python -m iris.daemon
```
Confirmed in `iris/services/iris-brain.service.tmpl:12`.

**AC2: Root cause — `iris.voice` has no `__main__.py`**
Confirmed: `iris/voice/` contains no `__main__.py`; `python -m iris.voice` crashes at startup.

**AC3: `iris.daemon` is the correct entrypoint**
Confirmed: `iris/daemon/__main__.py` exists and is the always-on keep-warm daemon.

## Test Run

```
$ python3 -m pytest tests/test_install_services.py -x -q
..........................
26 passed in 0.13s
```

Tests cover: template substitution, idempotency, systemctl calls, preflight validation.

## Commit

```
d58dc50 fix(services): update iris-brain.service.tmpl ExecStart iris.voice -> iris.daemon (ti-s9mm.5.1)
 iris/services/iris-brain.service.tmpl | 2 +-
 1 file changed, 1 insertion(+), 1 deletion(-)
```

Cherry-picked cleanly from a656739 (original builder commit on feat/brainhost-ti-s9mm.1.1).
