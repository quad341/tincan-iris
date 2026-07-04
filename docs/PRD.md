# PRD: Copyable console output & bug-filing path (ti-w3n09)

**Status:** Draft — routed to architecture + design
**Source bead:** ti-w3n09
**Author:** planner
**Date:** 2026-07-03

## Problem statement

The operator can't select/copy text from the iris console (a Textual TUI)
using normal terminal mouse selection, because Textual enables mouse
tracking that intercepts it. Selection is possible via a terminal-specific
modifier (Shift in GNOME Terminal/Konsole, Option/Alt in iTerm2/kitty), but
that workaround isn't discoverable.

This directly blocks the live-debug loop: when the console shows a
traceback, a wrong fact value, or a transcript line worth reporting, the
operator has no reliable way to get that exact text out to file a bug.
Today's partial mitigation — a console log at
`~/.local/state/iris/console.log` — is truncated on every run (including a
crash restart), so by the time the operator goes looking, the evidence is
frequently already gone.

**Who:** the operator, in the moment right after something breaks or looks
wrong during a live or demo call.

**Impact:** actively blocks bug-filing today (per the source bead: "he
can't grab a traceback to send"). Iris is mid-active-development (341
tests, CI-green, already holding real calls) — every crash or bad value
that isn't captured in the moment is unrecoverable evidence, which slows
iteration.

## Goals

- **G1:** Text needed to file a bug (traceback, error, fact/transcript
  value) is retrievable from a file outside the TUI — not dependent on a
  lucky mouse selection or catching it before it scrolls off.
- **G2:** Console output survives a crash. A crash is exactly the moment
  evidence is most needed; today's truncate-on-open log loses prior runs'
  content and never captures Textual's own panic output at all.
- **G3:** In-app copy affordances are discoverable, not just present —
  today's `[y]` binding works but is deliberately hidden from the footer
  and undocumented.
- **G4 (measurable):** from the moment something goes wrong on screen, the
  operator can produce a pasteable bug report in one action, without
  needing to know a terminal-specific selection modifier.

## Non-goals

- A general-purpose logging/observability/metrics platform — scope is
  operator bug-filing only.
- Changing daemon-side logging (`daemon.log` is already append-mode via the
  launcher — out of scope, already works).
- New remote-access/clipboard tooling beyond what Textual's built-in OSC 52
  support already gives for free.
- A wholesale redesign of the console's visual layout or keybinding scheme
  — scope is copy/log/bug-report affordances only.

## User stories

1. As the operator, when the console shows a traceback after a crash, I
   want that traceback already sitting in a file I can open/paste from, so
   I can file a bug without racing the terminal to select it before the
   alt-screen tears down.
2. As the operator, mid-call, when Iris reports a wrong fact value or a bad
   transcript line, I want a single keypress that copies "the last error /
   the last problematic thing" to my system clipboard, so I can paste it
   into a bug report or chat immediately.
3. As the operator, when I want to file a bug, I want one action that
   snapshots what was on screen plus the last error to a file and tells me
   the path, so I don't have to manually reconstruct context from memory.
4. As the operator, I want to discover that these copy/log affordances
   exist (via the footer or a help screen) without reading source code, so
   I stop re-asking "how do I get text out of this thing."
5. As the operator on a plain SSH terminal with no clipboard utility
   installed, I want copy-to-clipboard to still work (or fail loudly, not
   silently), so the fix doesn't depend on `wl-copy`/`xclip`/`xsel` being
   present.

## Functional requirements

Priority: P0 blocks the live-debug loop today; P1 materially improves it;
P2 is discoverability polish.

**FR1 (P0) — Persistent console log survives restarts and crashes.**
- AC: console output is appended (not truncated) across process restarts,
  or each run's log is uniquely named/rotated so no prior run's content is
  destroyed.
- AC: an unhandled exception/crash is captured to the log file — today
  Textual's own panic output reaches the terminal but is never persisted.
- AC: log location stays stable and discoverable (e.g. still under
  `~/.local/state/iris/`, documented).

**FR2 (P0) — A "file a bug" action producing a copyable artifact.**
- AC: one bound action captures recent console state + the last
  error/traceback to a file and surfaces the resulting path to the
  operator (e.g. via a notification/toast), so it's trivially copyable —
  short, single-line — even with no clipboard access at all.
- AC: works even when the triggering event was a crash — not dependent on
  the app still being in a healthy running state.

**FR3 (P1) — In-app copy-to-clipboard affordances extend beyond "copy last
reply."**
- AC: operator can copy the last error/traceback specifically (not only
  the last reply) in one action.
- AC: copy mechanism works in environments without `wl-copy`/`xclip`/`xsel`
  on `PATH` — today's `[y]` silently no-ops if none is present; the bar
  here is "no silent failure," either it works another way or the operator
  is told why not.

**FR4 (P2) — Copy/log/bug-report affordances are discoverable in-app.**
- AC: operator can learn these actions exist without reading source (e.g.
  footer, a help/commands screen, or equivalent — exact mechanism is a
  design decision).
- AC: if a terminal-native-selection-modifier hint (Shift/Option/Alt) is
  kept as a stopgap, it's surfaced in-app too, not just tribal knowledge.

## Non-functional requirements

- **NFR1 (reliability):** log persistence must not depend on clean
  shutdown — must capture output written up to the moment of a crash (the
  console already line-buffers via `_w()`; persistence changes must
  preserve that, not batch/lose the tail).
- **NFR2 (performance):** logging/copy/bug-report actions must add no
  perceptible latency or jank to the live console during an active call —
  this runs alongside a live phone call, not as an offline batch tool.
- **NFR3 (no regressions):** the existing `[y]` copy-last-reply behavior
  and the existing `consent.log` append-only precedent keep working
  exactly as today.
- **NFR4 (privacy):** call transcripts and fact values may contain real
  personal data (ARCHITECTURE.md principle: "real phone numbers, contacts,
  and call content stay local and are never committed or sent to a service
  the user didn't opt into"). Any new log/bug-report file must stay
  local-only — no new network egress — consistent with existing
  `~/.local/state` / `~/.local/share` conventions.

## Technical constraints

No `docs/PROJECT_MANIFEST.md` exists in this rig; the following is derived
from `ARCHITECTURE.md`, `README.md`, and direct inspection of the current
code, for the architect to verify/build on:

- Console app: `IrisConsole(App)` in `iris/console/app.py`. Textual pinned
  as `textual>=8` in `pyproject.toml` (resolved 8.2.7 here) — a floor-only
  constraint, so any design can rely on 8.2.x facilities, including
  `App.copy_to_clipboard` (OSC 52), which is available and currently
  unused.
- Existing precedent to extend, not replace:
  - `[y]` `action_copy_last` (`app.py:1199-1213`) — shells out to
    `wl-copy`/`xclip`/`xsel`.
  - `_open_log()` / `_w()` (`app.py:104-118`, `463-468`) — truncate-per-run
    console log, line-buffered, strips Rich markup.
  - `_log_consent` (`app.py:1065-1075`) — the existing append-only-log
    precedent to model persistent logging on.
- Textual's own crash handling (`App._handle_exception` →
  `panic()`/`_fatal_error()`) already produces a full traceback with
  locals after the terminal is restored — the gap is that it's never
  written to a file, not that the traceback is unavailable.
- No app-level exception hook currently exists in `iris/console/*.py` (only
  scattered local `except Exception`) — architecture must decide where to
  hook in: Textual's own exception-handling mechanism vs. wrapping the
  process entrypoint.
- No vendored/available bug-report library in this repo. The sibling
  `tincan` repo has an analogous, **not vendored**, pattern
  (`tincan_gui/bug_report.py`: `write_report()` →
  `~/.local/share/tincan/bug-reports/bug-<epoch>.json`, schema
  `tincan-bug-report-v1`) that the source bead suggested mirroring —
  architect decides whether to vendor, reimplement, or diverge.
- Privacy/local-first constraints (ARCHITECTURE.md principles on
  disclosure-first and local-only call content) apply to any new
  persisted artifact.

## Dependencies

- None external/new. No new services, APIs, or packages are implied.
- Optional clipboard utilities (`wl-copy`, `xclip`, `xsel`) remain today's
  mechanism for OS-clipboard copy and may stay as a fallback; Textual's
  built-in OSC 52 (`copy_to_clipboard`) is already vendored via the pinned
  `textual` dependency and needs no new package.
- Soft dependency: the sibling `tincan` repo's `bug_report.py` as a
  reference pattern only (not a build dependency — not vendored today).

## Open questions

1. **(architecture)** Log persistence strategy: append-forever to one file
   (simple, unbounded growth) vs. per-session rotation/timestamped files
   (bounded, but the operator has to find "the right one")?
2. **(architecture)** Where to intercept Textual's crash/panic output —
   override/hook the App's own exception handling, or wrap the process
   entrypoint?
3. **(architecture)** Should the "file a bug" action produce iris's own
   artifact format, or literally mirror tincan's `tincan-bug-report-v1`
   schema for consistency across the operator's tools?
4. **(design)** What's the discoverability mechanism for copy/log
   affordances — footer entries (currently deliberately hidden), a
   `[?]`/help screen, or startup hint text?
5. **(design, informed by architecture)** Is the Shift/Alt
   terminal-native-selection hint (direction 4 in the source bead) still
   worth surfacing as a stopgap once FR1–FR3 ship, or is it redundant?
6. **(architecture)** Should copy-to-clipboard prefer Textual's native OSC
   52 path over today's subprocess shell-outs (more portable, works over
   SSH, no dependency on installed clipboard binaries) — and if so, is the
   subprocess path kept as a fallback or removed?
