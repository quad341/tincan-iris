# Baseline health: what green means

Iris's baseline health monitor answers one question, continuously and without
being asked: **is the phone-bridge actually going to work right now?**

## Why this exists

Owner concern (2026-07-05): *"I have not known AEC has been wrong for the past
couple calls… making sure there is a good baseline really needs to become the
standard, not what we debug every day or so."* An 18-hour phone-bridge outage
had been invisible until a human happened to notice echo on a call. `iris
doctor` already existed and would have caught it — but only if someone
remembered to run it. That's the actual finding this feature answers: health
has to be **continuous and pushed**, not a CLI you have to think to invoke.

Everything below follows from that one bar. When deciding whether something
belongs in baseline health (a new check, a required/optional split, a
notification), ask whether it's the kind of thing that could go silently
wrong for hours without anyone noticing — if yes, it belongs here.

## The three layers

1. **Daemon heartbeat** (`iris/daemon/heartbeat.py`) — a background thread
   inside `iris.daemon` runs a fixed set of cheap checks on a periodic timer
   and caches the aggregated result. This is deliberately daemon-side, not
   console-side: the console is a per-call TUI that isn't always open, so it
   can't be the thing that notices a problem at 3am. The daemon is the
   always-on process; it has to be the guardian.
2. **Degradation notifications** (`iris/daemon/degradation_notify.py`) — the
   daemon pushes a desktop notification when the cached result crosses an
   edge (see Notification semantics below). This is the direct fix for the
   "invisible until noticed" finding: the operator gets told, rather than
   having to ask.
3. **Surfaces** — the daemon's `status` command includes the latest cached
   result (`iris/daemon/api.py`), the daemon broadcasts every transition to
   connected consoles as a `baseline` event, and the console
   (`iris/console/app.py`, `iris/console/health_screen.py`) shows a status-strip
   pill plus an on-demand detail panel (`[H]`). So opening the console for a
   call always answers "what should I expect right now," even between
   notifications.

Each layer only does its own job: the heartbeat computes and caches and has no
opinion on whether a change is worth telling anyone about; the notifier
decides notify-worthiness and has no opinion on how checks are computed; the
console only ever renders what the daemon already decided. If you're looking
for where some behavior lives, it's almost certainly in exactly one of these
three places, not spread across all of them.

## What each check means

Checks are cheap, reused probes from `iris/doctor.py` — the heartbeat calls
into `doctor.py` rather than re-deriving check logic, so `iris doctor` and the
background heartbeat can never quietly disagree about what "working" means.
The current catalog, grouped by what they're actually asking:

- **`daemon-socket`** — is the daemon's own control socket even accepting
  connections. The most basic "is anything alive" signal; everything else is
  moot if this is down.
- **`tincand-connected`, `call-setup-ready`** — is the phone-bridge daemon
  (`tincand`) reachable over D-Bus and reporting itself ready to set up a
  call. These are the checks born directly from the founding incident: they
  can go bad with no error visible anywhere in a normal session, which is
  exactly what made the original outage invisible.
- **`ambient-aec-default`** — are the AEC-processed audio nodes still the
  system default sink/source. This is *the* check for the specific failure
  the owner described: something else (a reconnected device, a WirePlumber
  reassertion) silently becomes the default route, echo cancellation quietly
  stops applying, and nothing errors — you just start hearing echo.
- **`messages-capability`, `call-audio-aec`** — narrower tincand capability
  flags for specific features (SMS handling, in-call AEC signaling). Lower
  stakes than the two above, so these are informational rather than
  required (see next section) — a miss degrades a feature, it doesn't mean
  the bridge is broken.
- **service checks** (`iris-whisper`, `iris-kokoro`, and others via
  `EXPECTED_SERVICES` in `doctor.py`) — are the systemd units iris actually
  depends on active. The heartbeat only asks about the subset it cares about
  (see `_HEARTBEAT_SERVICE_NAMES` in `heartbeat.py`); notably it does not
  speak for `iris-llama`, which is operator-managed and shared across tools
  outside iris's control.
- **`call-card-enrichment`** — are Call Card's L3 enrichment dependencies
  importable by the daemon's own interpreter (not the console's — the daemon
  is what actually runs enrichment, so that's the interpreter that matters).
  Optional: a miss means enrichment gets silently skipped on every call,
  which is worth surfacing but isn't a broken bridge.

This list itself is exactly the kind of thing that drifts — the source of
truth for the current, exact catalog and which checks are required is
`iris/doctor.py` (individual checks) and `iris/daemon/heartbeat.py`'s
`_collect_checks()` (which subset the heartbeat runs each tick).

## Green, yellow, red

Only **required** checks affect the aggregate color (`_aggregate()` in
`heartbeat.py`). Optional checks still show up in the detail panel and can
still fire their own doctor `fix` hint, but they never change the pill —
required is the "would a human want to be interrupted for this" bar, not a
severity label.

- **Red** — at least one required check is down, absent, or in an unknown
  state (the check itself failed to run cleanly). Treat unknown the same as
  down: a check that can't report is not evidence of health.
- **Yellow** — no required check is that bad, but at least one is degraded
  (working, but not as intended).
- **Green** — every required check reports OK. This is the only state that
  means "don't think about this."

A check's required/optional status is a deliberate editorial choice, not a
mechanical property of the check itself (see "how to add a new check" below)
— so the same probe could reasonably move between required and optional as
the product's stakes change, without any change to how it's computed.

## Notification semantics

Notifications are **edge-triggered**, not level-triggered — the steady state
is silence, matching the "never repeat-nag" requirement this was built
against. The edge is tracked by what the notifier itself last told the
operator (a module-level "last announced level" in `degradation_notify.py`),
not by the heartbeat's own previous-tick value. That distinction is what makes
a daemon restart fall out naturally instead of needing special-case handling:
state doesn't survive a restart, so a fresh process assumes green and simply
re-announces on its next tick if the system is, in fact, still broken. A
still-broken system is never silently suppressed forever — at worst it's
rediscovered one tick late.

- **Green → non-green**: one notification, naming the failing required
  check(s) and each one's doctor `fix` hint.
- **Non-green → green**: one quiet recovery confirmation. No detail needed —
  the point is just "you can stop thinking about this now."
- **Sustained red**: re-reminds on a fixed interval (see
  `_RED_REMIND_INTERVAL_S` in `degradation_notify.py`) rather than never
  repeating, so a persistent problem doesn't fall out of mind during a long
  outage. Sustained yellow does not re-remind — it only notifies once on the
  initial edge into yellow, on the theory that a degraded-but-working state
  is lower stakes than a broken one.
- Delivery is a desktop notification (urgency raised for red); the same
  transition is also what drives the console broadcast and panel, so the
  desktop notification and the console's pill are always telling the same
  story, just through different channels.

## Console surfacing

The status-strip pill only appears when connected to the daemon (nothing to
show in direct/no-daemon mode) and mirrors `iris doctor`'s own glyph
vocabulary on purpose — operators who already read `iris doctor` output don't
have to learn a second vocabulary. Color is never the only signal (a glyph
carries the state too), matching the same accessibility reasoning used
elsewhere in the console.

`[H]` opens the full detail panel: every check with its status, whether it's
required, and its detail text; an explicit fix list for anything required and
currently broken; and an "as of HH:MM:SS (Ns ago)" freshness line, so a stale
cached read is never mistaken for a live one. The panel is intentionally dumb
— it only renders whatever the daemon last computed on its own schedule;
opening it never triggers a fresh check.

Because check names/details/fixes originate from the daemon and flow into the
console's markup-rendering widgets, they're escaped the same way Call Card's
own render() output is (`escape_for_content()`) — this is the same content
shape (free-text riding into Textual markup) that already produced a real
injection class of bug elsewhere in this console, so it gets the same
treatment here rather than assuming baseline-check text is somehow safer.

## How to add a new check

1. Add or extend a check function in `iris/doctor.py` (prefer extending an
   existing one over writing a new probe from scratch) returning an
   `AssetCheckResult` — status, required, detail, and a fix hint if the fix
   is known and actionable.
2. Wire it into `heartbeat.py`'s `_collect_checks()`. Keep it cheap — this
   runs on every tick — and make sure a failure inside the check degrades to
   an `UNKNOWN` result rather than raising; one check's exception must never
   take down the whole tick.
3. Decide required vs. optional deliberately, against the bar at the top of
   this doc: required means "bad enough that a human should be interrupted
   about it specifically." Default new checks to optional; only promote to
   required if the failure mode is the kind that could go silently wrong for
   hours the way the founding incident did.
4. Nothing else needs to change. The notifier, the console pill, and the
   detail panel all key off `status`/`required` generically — a new check
   just shows up, and can turn the pill non-green (if required) without any
   code change in `degradation_notify.py`, `api.py`, or the console.
5. Test coverage is a separate, validator-owned bead per this rig's usual
   builder/validator split — file it rather than writing tests inline.

## Source of truth

- `iris/doctor.py` — individual checks
- `iris/daemon/heartbeat.py` — scheduling, aggregation, the required→color rule
- `iris/daemon/degradation_notify.py` — notification policy
- `iris/daemon/api.py` — `status` snapshot + console broadcast
- `iris/console/app.py`, `iris/console/health_screen.py` — pill + detail panel
