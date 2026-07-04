# ADR-0006 — Call handling & promotion/demotion: an autonomous verb ladder, DND degrade, and a single-attention control surface

- **Status:** accepted — shipped (proposed 2026-06-24; implemented across the Call Card work, 2026-06/07)
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

This ADR specifies **the handling layer** (what Iris autonomously does with an
inbound call) *and* the **promotion/demotion layer** (how the operator steers a
live call, plus the busy/DND posture). Handling is specified first because, by the
core invariant, it must be complete **without** any human — so it stands alone;
promotion/demotion is the optional control surface layered on top. Only the
*implementation* (the always-on daemon, `ti-s9mm`) is deferred.

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

### The spine — Iris never infers what she can't know

A rule the invariant keeps generating: **Iris must not act on intent or state she
cannot actually observe.** It recurs everywhere —
- she never **discloses your availability** to a caller (she can't know *why*
  you're unavailable, and guessing leaks it) — every non-available outcome is a
  plain, reason-free `take_message`;
- **DND is reason-opaque** (she won't infer or expose *why* you don't want to
  answer);
- low-confidence STT **falls back to audio**, never a confidently-wrong (and, in
  another language, insulting) transcript;
- a **one-time action never writes standing** — "decline this call" could mean
  "I'm in the bathroom" or "I can't stand them," and she can't tell, so changing a
  contact's `handling_rule` is always a separate, deliberate edit.

When in doubt she does the safe, non-presumptuous thing and leaves the inference
to the human.

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

### The catch-line — where Iris starts catching calls for you

The ladder reads two ways at once: by **intrusiveness** (downward = bothers you
less) and by **Iris-service** (downward = Iris catches more). They are the same
order inverted, which is why the degrade `ring → screen` is good on both axes —
less bother *and* Iris starts catching it. The fallback-on-ignore makes the
service reading concrete and draws a line:

```text
VIP → ring_through   │   screen → take_message → ignore
  ignore → voicemail  │   ignore → take a message
  (Iris uninvolved)   │   (Iris catches it for you)
```

The divider between `ring_through` and `screen` **is** the commitment line
(invariant #2): above it Iris catches nothing (a miss → voicemail); at/below it
she catches your call as a message. That is *why* `ring → screen` is the
meaningful DND degrade — it carries you across the line, turning "missed →
voicemail" into "Iris took a message."

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

## Promotion & demotion — the operator's control surface

Handling resolves every call on its own. **Promotion/demotion is the optional
layer by which the operator steers a live call** — up toward engagement
(*promote*) or down toward protection (*demote*) — always one-shot, always
overridable, never required (the autonomous baseline still resolves if the
operator does nothing). Demotion is also the **sanctioned conscious path to the
bottom**: automatic machinery stops at `take_message`, so a deliberate demote is
the only way a live call reaches `decline`.

### It is a PC concern, not cross-device

The phone is the *controlled device*, not a notification target: if the operator
is going to use the phone, they use the phone. Iris's whole value is a **PC
surface** so they *don't* have to. So promotion is PC-local — there is no
cross-device/mobile fabric (no ntfy). "Cross-platform" means only PC desktops —
Linux (GNOME/KDE/WMs), Mac, WSL — each a client of the daemon, hitting its local
API. (No native Windows.)

### The daemon is the floor; every UI is a client

The **floor is the daemon deciding autonomously** (it works with zero clients).
The CLI, a GUI, native desktop notifications, the TUI — all are **interchangeable,
optional adjustment surfaces** over it. The desktop/TUI is *just one client*;
logic lives in the daemon. There is no universal native renderer for notification
*actions* (it is fragmented across GNOME/KDE/WMs/Mac/web), which is *why* the
daemon owns a neutral choice-set and each client renders it however it can.

### Three posture states (internal — never disclosed to a caller)

- **available** — default; neither below active.
- **busy** — **auto-detected, never set by hand:** a live conversation is in
  progress. Detectors: **SCO active** (on a cell call, from tincand) or **desktop
  mic-active** (on Discord/Zoom — the `ti-iznt` PipeWire signal). Internal
  corollary: Iris's own **single-attention** gate (below) also forces degrade
  while she is mid-engagement.
- **DND** — a **chosen, reason-opaque** "treat me as unavailable" posture, and the
  **catch-all for every non-call reason you're unavailable.** Set by a **manual
  toggle**, a **schedule** (quiet hours), the **calendar** (auto during events),
  or **desktop state** (fullscreen/presentation focus). One state, many sources.
  It tracks *which* source **internally** — for the operator's own view and for
  **auto-expiry** (night ends → off, meeting ends → off) — but **never discloses
  the source** to a caller. DND degrades the ladder one rung (VIP-immune).

busy and DND may both be active; available = neither. Neither is ever narrated to
a caller (the spine): every non-available outcome is a plain `take_message`.

### Single attention, and Iris controls SCO only

**Iris engages exactly one live conversation at a time** (ride-along, screen,
take_message, respond) — practically, not technically. And she can only *act on*
the **SCO** path (via tincand); desktop audio she only *observes*. So for a second
call:

- **SCO-during-SCO** (a call during a call): one SCO link — Iris cannot engage the
  second caller (no audio path), and today is not even notified of the `waiting`
  call (`tincan-6t7ym`). She **stays out**; the carrier handles
  call-waiting/voicemail. A future *swap* (hold #1, take #2) depends on that bead.
- **desktop-during-SCO** (on Discord, a cell call arrives): paths are separate, so
  Iris can take the cell caller's **message in the background, your desktop call
  undisturbed** — the one non-disruptive direction. The only cost is her attention
  (she pauses the ride-along, which your call never needed).

### The action surface (a neutral, state-aware choice-set)

The daemon emits, per decision point, a **neutral choice-set**; any client renders
it and returns the pick over the daemon's **local API** (127.0.0.1 / D-Bus). The
client stays dumb; the daemon decides which actions are valid and resolves the
chosen one, scoped to the call.

- **Per-call (ephemeral — this call only, never touches standing):**
  `promote → put-through` ("take it"), or `swap` (only SCO-on-SCO, via
  `tincan-6t7ym`); `demote → take_message` or `decline`.
- **Global posture:** `DND on/off` (available ⇄ DND), and `DND until <end>`.
  `busy` is auto, not an action.
- **State-aware:** the valid set depends on current posture — e.g. `busy` offers
  `swap` in place of `take it`.
- **Contract:** daemon → `[{action_id, label, kind: promote|demote|toggle}]`;
  client → chosen `action_id` + call ref. (Same shape as the external-LLM↔session
  channel.)

**Standing is separate and deliberate.** A per-call action *never* writes a
contact's `handling_rule`; changing standing is an explicit edit (the contact
editor). A one-time decline carries no information about whether it's a preference
(the spine: never infer what you can't know).

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

- **Implementation — the always-on daemon (`ti-s9mm`).** This ADR is the policy;
  building the headless daemon that enforces it — subscribing to tincand, owning
  the posture state, exposing the local control API + the neutral choice-set, and
  lifting orchestration out of `IrisConsole` — is the work. TUI / CLI / native
  notifications become its clients.
- **The handling↔promotion seam.** Whether a DND-degraded `ring_through` (now
  `screen`) still **announces the screened result to you** so you can grab it, vs.
  silently messaging. (A promotion-surface detail; default to announce.)
- **Representation & storage.** Per-contact verbs live in the roster today; where
  the *conditional* layer (schedules, time-windows) and the **DND posture + its
  source/expiry** live, and the authoring surface (`iris rule …`? config? the
  contacts editor?).
- **Caller-side STT robustness & i18n (roadmap — "enable others," not today).**
  Today STT is faster-whisper `small.en` with `language="en"` pinned — tuned for
  clean American English; weak on heavy accents and unable to do other languages
  at all. `screen`/`take_message` are the caller-facing paths, over narrowband
  telephony SCO (the hardest STT input). Agreed direction:
  - **Audio is the retained source of truth.** `take_message` captures and keeps
    the recording; the transcript is a *derived, regenerable* artifact. This is
    the universal inclusive floor — anyone can leave a message in any
    language/accent, and a better model (or a newly-added language) can
    re-transcribe the backlog later because the audio was kept. (`message_store`
    is transcript-only today — keeping audio is the gap.)
  - **Split STT by latency.** Live paths (operator commands, `screen`,
    ride-along) stay on a fast/small model. `take_message` is asynchronous, so it
    transcribes **offline with a bigger/better multilingual model** — no live
    latency cost. A natural background-queue job for the always-on daemon.
  - **Per-operator language set (1–2).** Transcribe the operator's chosen
    languages well; out-of-set → keep **audio only** (never a false transcript).
    Infra v1 can wire a single language (English), mechanism extensible; consult a
    real multilingual user before building the multi-language UX.
  - **Minimum-confidence transcript gate (dignity, not just accuracy).** Below a
    confidence floor — faster-whisper exposes `avg_logprob` and a language-detection
    probability, but iris surfaces only `no_speech_prob` (used today to *silently
    drop*) — **suppress the transcript and fall back to audio** (async
    `take_message`) or re-ask once, then take-message-with-audio (live `screen`). A
    confidently-wrong transcript of another language isn't just useless, it's
    *insulting*; the audio is the respectful, truthful fallback. Never display a
    sub-threshold transcript, and never degrade to silence.
  - **Language vs locale.** Whisper selects by *language* (`en`) — bare language
    is correct *for Whisper's API* (it doesn't accept locales), so all English
    accents collapse to `en`. Accent/dialect is a *locale* concern (`en_US` vs
    `en_SG`): carry locale (operator's, per-contact) as metadata *above* the
    Whisper param — to drive model/threshold/expectations and the command-surface
    i18n — and never pass a locale into Whisper's `language`.
  - **i18n for the command/response surface** (localizing Iris's own vocabulary
    and replies, plus locale-correct dates/numbers/spelling) is a separate, later
    track.
- **Beyond calls.** Inbound **messages** (SMS/iMessage via ANCS/MAP) are the same
  pattern with a smaller verb set (notify/ignore); designed later.
- **The command CLI surface.** Exact verbs/outputs for the imperative plane
  (`dial`/`answer`/`hangup`/`status`) and the directed terminals
  (`put-through`/`wrap-up`/`decline`).
