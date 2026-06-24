# ADR-0006 — Call handling model: an autonomous verb ladder, DND as a one-rung degrade, promote-don't-gate

- **Status:** proposed (2026-06-24)
- **Related:** [ADR-0002](0002-capability-gating-by-speaker-channel.md) (speaker identity = the audio channel — the *who*); [ADR-0004](0004-inbound-events-and-interrupt-handling.md) (the inbound-event source this layer reacts to); [ADR-0005](0005-trust-permission-and-assurance-model.md) (trust/permission/assurance — *what may be done*; this ADR is the policy layer that decides *what Iris does with an inbound call*, above that gate)
- **Authors:** operator (@quad341) + cohelper

## Context

Today, what Iris does with an inbound call lives in the Textual console
(`IrisConsole`): screening, the consent gate, far-party handling, the ride-along.
It only runs while a human is staring at a TUI. The operator wants an
**always-on** posture — rules that decide *what Iris connects, screens, notifies
about, and ignores* with **no TUI running** — plus a small set of **imperative
commands** you can invoke and wait on (`dial`, `hangup`, `status`).

That splits Iris's runtime into two planes:

- **Commands — imperative, you-ask-you-wait.** `dial` / `answer` / `hangup` /
  `status`. Request → direct answer. Thin clients over **tincand's existing
  D-Bus methods** (`Dial`/`Answer`/`Hangup`/`CallState`, `tincand/dbus_service.py`).
- **Rules — declarative, the daemon decides.** An always-on Iris process
  subscribes to tincand's signals (`IncomingCall`, `CallConnected`, the iPhone's
  ANCS message notifications) and applies operator policy autonomously. (This is
  the daemon filed as `ti-s9mm`, "always-on"; the policy it enforces is this ADR.)

Ownership line: **tincan owns transport** (the phone, the audio, the call
primitives); **iris owns policy** (which rule fires, the screening conversation,
the notifications). `iris dial` is a thin client over `tincand.Dial`; an iris
*screen* rule is policy that drives tincand primitives.

This ADR specifies **the handling layer** — what Iris autonomously does with an
inbound call. It deliberately defers *promotion* (how the operator is looped in /
upgrades an outcome across the Linux notification fabric) and the *sources* that
drive DND. Handling is specified first because, by the core invariant, handling
must be complete **without** any human — so it stands alone.

## The core invariant — promote, don't gate

> Every Iris action resolves to a safe outcome **on her own authority** within a
> bounded time. The operator can only ever **upgrade** the outcome (promote);
> their silence or absence can only let it **fall back**. Nothing stalls and
> nothing fails because the human didn't answer. **A rule that needs a human
> reply to complete is invalid by construction.**

Three corollaries shape everything below:

1. **Bounded terminal — no open-ended relay.** Every interaction converges to a
   bounded terminal state. The operator either **engages** (takes the call — their
   voice, a real conversation) or **defers** (lets Iris resolve it). A "directed"
   action is a *one-shot* choice of which terminal Iris should reach — never
   turn-by-turn puppeting of Iris's side of a live conversation. *This is why
   `say`/`ask` are rejected verbs:* they invite an unbounded human-in-the-loop
   relay that is awkward at best and insulting to the caller at worst. The
   directed surface is the one-shot terminal set (`put-through` / `take_message` /
   `wrap-up` / `decline`).

2. **Commitment-aware fallback.** The safe fallback depends on how far Iris has
   committed *with the caller*:
   - **Uncommitted** (Iris never engaged the caller — only signaled the
     operator): operator silence → **do nothing.** The world is unchanged; Iris
     never inserted herself.
   - **Committed** (Iris engaged the caller — answered, started screening):
     operator silence → **close gracefully herself: take a message.** She never
     abandons an engaged caller.

3. **Iris engages the caller in exactly two cases — `screen` and `take_message`.**
   Everywhere else she is a silent gate/announcer over a normal ring; she never
   talks to your caller. (An AI that picks up, is pleasant, then fobs an
   important caller off to a message is *insulting* — so a missed VIP gets plain
   voicemail, never an Iris-mediated message.)

## The handling verbs

Five verbs. Each completes with zero human input (the invariant holds at this
layer alone):

| verb | engages caller? | rings to you? | announces to you? | you don't answer → |
|---|---|---|---|---|
| `ring_with_announcement` (VIP) | no | yes | **yes (voice)** | normal voicemail |
| `ring_through` | no | yes | no | normal voicemail |
| `screen` | **yes** | not until you answer | relays the caller's intro | **`take_message`** |
| `take_message` | **yes** | no | no | terminal |
| `ignore` | no | no | no | reject → voicemail |

- **`ring_with_announcement`** is the single "this caller matters" setting — it
  unifies *VIP*, *favorite*, *announce-me*, and *comes-through-even-in-DND*. Iris
  **does not pick up** (uncommitted); the call rings as normal and Iris announces
  the caller to you by voice. Missed → plain voicemail (never an Iris message —
  invariant #3).
- **`ignore`** = don't bother me + reject to voicemail. Iris cannot silence the
  iPhone itself (it is the Audio Gateway and rings regardless); the most Iris can
  do is reject over HFP. **True/hard blocking belongs at the phone or carrier**,
  where Iris never sees the call.

## The ladder & DND

The verbs form one ordered ladder, most-intrusive → most-protective:

```
ring_with_announcement (VIP)  →  ring_through  →  screen  →  take_message  →  ignore
```

A **Do-Not-Disturb / "I'm busy" condition is a single monotonic degrade: shift
the effective verb one rung down the ladder** — with two hard guards:

- **VIP is immune.** `ring_with_announcement` never degrades; it is the operator's
  protected channel, and the gap *widens* under DND (which is the point).
- **The degrade floor is `take_message`.** It never reaches `ignore`.
  `take_message` and `ignore` are already silent — they don't interrupt you — so
  DND leaves them. In practice DND moves only the top two: `ring_through →
  screen`, `screen → take_message`.

Both ends of the ladder are therefore **pinned against automatic movement**: VIP
can't be auto-silenced (top), and **`ignore` is opt-in only** — no condition,
DND, or default ever degrades a caller into `ignore`; going dark on someone is
always a conscious operator decision (bottom). The autonomous machinery only
moves a caller within the safe middle band `ring_through ↔ screen ↔
take_message`, and **the worst it can ever do on its own is take a message.**

## Resolution

For an inbound call, the effective verb is computed in two steps:

1. **Base verb.**
   - A known contact's explicitly-set verb (per-contact policy), else
   - the default **floor = `screen`** (an unknown or unset caller is screened —
     Iris finds out who/why and, absent promotion, takes a message). [grounding:
     `screen_call.py` already defaults unknown callers to screen.]
2. **Apply active conditions.** If a DND/busy condition is active, degrade the
   base verb one rung (VIP-immune, `take_message`-floor, as above). A specific
   conditional rule (e.g. a per-time-window override) may set the base; the
   one-rung degrade is the general mechanism.

There is no separate "pin" attribute beyond `ring_with_announcement`: "always
reach me, even in DND" *is* the VIP verb.

## Grounding & the migration it implies

The model maps 1:1 onto the existing roster enum (`roster.py:72`,
`handling_rule TEXT NOT NULL DEFAULT 'normal'`), renamed for explicitness
(`normal` was a non-name; the rest gain precise meaning):

| existing roster value | this ADR |
|---|---|
| `normal` | `ring_through` |
| `vip` | `ring_with_announcement` |
| `screen` | `screen` |
| `take_message` | `take_message` |
| `block` | `ignore` |

Other existing pieces this layer reuses: `ScreenCallFlow` (already implements
`screen → take_message` on operator-timeout — the committed-fallback in invariant
#2), `disclosure.py` (pre-rendered courtesy lines), `DesktopNotifySink` +
`proactive_delivery` (announce/notify primitives), the `contacts.py` per-contact
rule editor, and tincand's `Dial`/`Answer`/`Hangup`/`CallState` + `IncomingCall`/
`CallConnected`/ANCS surface.

## Consequences

- Handling is **complete and autonomous**: with zero rules and no human, every
  inbound call resolves safely (floor = `screen → take_message`).
- Policy moves **out of `IrisConsole`** into a daemon; the TUI and the CLI both
  become thin clients/observers of it. (Headless testing/scripting — `ti-noym` —
  falls out: drive the daemon's commands, observe its events.)
- The notification surface stays simple: because promotion is one-shot terminal
  choices, an actionable notification needs only a few buttons (`[take it]` ·
  `[message]` · `[decline]`), not a chat UI.

## Open questions (deliberately deferred)

- **Promotion (the next pass).** *How* the operator is looped in and upgrades an
  outcome, across the full Linux fabric: actionable desktop notifications, D-Bus,
  Discord/ntfy, voice, the external-LLM↔session channel. Includes the one
  handling↔promotion seam noted above: whether a DND-degraded `ring_through` (now
  `screen`) still **announces the screened result to you** so you can grab it, vs.
  silently messaging.
- **DND/busy *sources*.** The condition is one state with many inputs: a
  **schedule** (night mode), the **calendar** (Iris already reads gcal —
  `calendar.py` — so auto-busy during events), a **manual toggle** (`iris busy` /
  a notification action), and **desktop state** (a fullscreen/presentation app
  focused, or mic-active — the same PipeWire signal as `ti-iznt`). What feeds the
  state, and the precedence among sources.
- **Representation & storage.** Per-contact verbs live in the roster today; where
  the *conditional* layer (schedules, time-windows) and the busy-state live, and
  the authoring surface (`iris rule …`? config? the contacts editor?).
- **Caller-side STT robustness.** `screen` and `take_message` engage the caller
  through whisper STT; accent/language coverage there is an accessibility concern
  for non-operator callers (tracked separately).
- **Beyond calls.** Inbound **messages** (SMS/iMessage via ANCS/MAP) are the same
  pattern with a smaller verb set (notify/ignore); designed later.
- **The command CLI surface.** Exact verbs/outputs for the imperative plane
  (`dial`/`answer`/`hangup`/`status`) and the directed terminals
  (`put-through`/`wrap-up`/`decline`).
