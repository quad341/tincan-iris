# Release Gate: Document Call-Capture Single-Owner Invariant

**Bead:** ti-ig121 (needs-deploy)
**Source review bead:** ti-cha1h
**Branch:** `deploy/capture-invariant-doc-comment-ti-ig121`
**Commit:** `96e38e2` (cherry-picked from `305bd16` on `feat/console-crash-exit-message-ti-00jr4-2`)
**Gate evaluated:** 2026-07-03

---

## Criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Review PASS present | **PASS** | ti-cha1h notes: reviewer PASS, independently confirmed the documented invariant is accurate against the dispatch body |
| 2 | Acceptance criteria met | **PASS** | See below |
| 3 | Tests pass | **PASS** | 1615 passed, 1 skipped, 3 xpassed, 0 failed |
| 4 | No high-severity findings open | **PASS** | None recorded |
| 5 | Final branch is clean | **PASS** | `git status` shows only untracked non-source artifacts (venv, egg-info) |
| 6 | Branch diverges cleanly from main | **PASS** | Cherry-pick of `305bd16` onto `origin/main` (088b7da) applied via clean auto-merge, no conflicts |
| 7 | Single feature theme | **PASS** | 1 commit, 1 file, docstring-only expansion, zero behavior change (diff verified below) |

**Overall gate: PASS**

---

## Acceptance Criteria (ti-1fpil doc comment)

- [x] `_on_daemon_event` docstring documents the single-owner invariant: no `call_connected` case exists in this dispatch body, so proxy-mode calls never trigger the console's own ride-along capture
- [x] Zero behavior change — confirmed via diff, only docstring lines added

---

## Diff (full, docstring-only)

```diff
@@ -698,7 +698,16 @@ class IrisConsole(App):
                 self.query_one(IncomingCallPanel).update_countdown(remaining)

     def _on_daemon_event(self, ev: dict) -> None:
-        """Handle a JSON event received from DaemonProxy."""
+        """Handle a JSON event received from DaemonProxy.
+
+        SINGLE-OWNER INVARIANT: deliberately has no "call_connected" case, so
+        proxy mode never starts the console's own ride-along capture
+        (_attach_call_audio()/_begin_ride_along(), direct-mode-only — see the
+        streaming-loop handler above). Proxy mode's daemon already owns
+        capture via CallCardHost/HandlingEngine/BrainHost. Adding a
+        "call_connected" case here (e.g. to restore proxy-mode UI feedback)
+        would double audio capture unless it keeps excluding those calls.
+        """
         event_type = ev.get("event", "")
         if event_type == "incoming_call":
```

---

## Test Results

```
.venv/bin/pytest -q (on deploy/capture-invariant-doc-comment-ti-ig121, origin/main + 96e38e2 only)

1615 passed, 1 skipped, 3 xpassed in 83.34s
```

No failures.

---

## Branch Composition

| Commit | Description |
|--------|-------------|
| `96e38e2` | docs(console): document call-capture single-owner invariant (ti-1fpil) |

Cherry-picked `305bd16` only, from the shared `feat/console-crash-exit-message-ti-00jr4-2` branch, excluding its current tip `0840ed3` (belongs to a separate bead, ti-9s84e, deployed independently). Regression test coverage for this same invariant already shipped separately via ti-upbvt (unrelated branch, no dependency either direction) — not duplicated here.
