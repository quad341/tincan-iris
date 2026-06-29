# Release Gate: ruff lint gate + violation cleanup (ti-2mmj re-auth)

**Date:** 2026-06-27  
**Branch:** fix/ruff-lint-gate-ti-2mmj  
**Commit:** f0c5ef9  
**Bead:** ti-2mmj  
**Re-authoring note:** Original commit 7a49143 conflicted against origin/main; re-authored against origin/main HEAD (60454d3) after PR #107 merged.

## Gate Evidence

| Check | Result |
|---|---|
| `ruff check .` before fixes | 128 errors found |
| `ruff check . --fix` | 87 auto-fixed |
| Manual fixes | 41 remaining violations fixed |
| `ruff check .` after all fixes | **0 errors — PASS** |
| Gate verification (deliberate unused import) | `ruff check .` fails exit 1 — gate is live |
| `pytest -q` | **1363 passed, 3 xpassed, 2 warnings — PASS** |
| CI workflow | ruff step added before pytest |

## Violations Fixed

- **E741** ambiguous variable name `l` (17 occurrences — lambdas + comprehensions)
- **E702/E701** multiple statements on one line (9 occurrences)
- **F841** assigned-but-unused locals (12 occurrences)
- **F401** unused imports (3 occurrences — via auto-fix + manual)
- **E402** module-level imports not at top of file (2 occurrences)
- Invalid `# noqa` directive in test_pipecat_stt.py (1)
- All remaining 87 auto-fixable violations fixed by `ruff check --fix`

## Files Changed

58 files (72 insertions, 131 deletions)

## Why re-authored vs. cherry-pick

Previous evaluations (deployer × 4) found that cherry-picking 7a49143 onto origin/main conflicted in 8+ paths because test files from ti-eq6d.2/ti-eq6d.3/ti-x5cd did not yet exist on main. Those branches remain pending. This commit is scoped to files on current origin/main only; remaining files (test_pipecat_tts.py, test_call_pipeline.py, test_ride_along_console.py) will be linted clean when their parent branches merge via CI enforcement.
