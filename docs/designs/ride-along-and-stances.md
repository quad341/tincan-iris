# Ride-along & stances — iris as a co-pilot on live calls

> **Status:** Design (the golden path). Walked with the operator 2026-06-25; open
> questions noted inline. Reads with [`voice-call-architecture.md`](voice-call-architecture.md)
> (mp6v.1) §5 and ADR-0005 (trust). Bead: ti-x5cd. Presentation/cosmetic tuning is the
> sibling, ti-6371.

The bounded use case (fully-automated screen / take-message) has a depth ceiling. The depth
is iris as a **co-pilot on the operator's *own* calls** — catching actionable moments, helping,
mostly as an ambient visual assistant, becoming a voice only by escalation. This is *not* about
profiling the operator.

---

## 1. Stances — the master switch

iris runs in one of two **stances**. A stance is not a single dial; it's a coordinated setting
of **participation + far-party trust + persona**:

| | **Business** (a tool) | **Collaboration** (a participant) |
|---|---|---|
| participation | silent by default; uplink needs explicit control + task | welcome on the call (standing) |
| far-party trust | caller has no reach to iris | caller may address her ("hey iris, remind Jim…") |
| persona | efficient, quiet | playful, conversational |

Default is **business**; collaboration is opt-in per call. Example collaboration moment — Mom:
*"hey iris, remind Jim to…"* → iris: *"oh I will definitely remind him — how many times?"*

**Entering / leaving collaboration:** the **grant must already be given by keyboard** (the
high-assurance operator channel, ADR-0005) **plus** a spoken **keyword pair** (join / stand
down) toggles it live. The far party can *address* iris in collaboration but **cannot change the
stance** — mode control is operator-authority. No extra disclosure on entry: iris is *always
introduced* at call start (see §5), and that intro is the blanket.

---

## 2. Participation spectrum & channels

| level | what | who hears |
|---|---|---|
| 0 silent capture | listens, notes/actions privately, says nothing | nobody |
| 1 ambient / visual | console cards — captured items, context, suggestions | operator (glance) |
| 2 audio-private | brief earpiece whisper, timed into a call pause (full-duplex VAD) | operator |
| 3 on-call | speaks onto the uplink | the far party too |

**Channel-consistency rule (the spine):** *iris answers on the channel she was invoked on.*
Call her **out loud** ("hey iris, …") → she answers **out loud** (leaving the far party hanging
after they heard you summon her is the jarring thing). Want her **silently** → **type** to her
(the private prompt) → she answers privately. The stance sets *who* may invoke her audibly
(business: operator only; collaboration: the far party too).

The **two-conversations** problem dissolves by keeping private help **visual** (no second voice
in your ear); audio-private is rare/brief/pause-timed; on-call is the one moment there's a single
conversation again (iris has the floor, you listen).

**Floor ≠ stance** (two layers): *anyone* may claim the floor — "iris, stop" / a barge-in makes
her yield **that instant** (just manners; it's the full-duplex barge-in). That is **not** the same
as standing down from collaboration, which only the operator can do.

**Addressing** is always the wake phrase **"hey iris"** — even in collaboration. (A cleverer
post-join addressing model is welcome later but unsolved, especially with open-ended search;
collaboration is the forgiving mode, so some friction is fine.)

---

## 3. The collaboration far-party grant (ADR-0005)

Collaboration *is* an operator-granted assurance bump for the far party — bounded. The principle:

> **The far party may CREATE things addressed to the operator** — reminders, notes, messages —
> **and may QUERY** — generic qwen/haiku questions, web search. **They may never READ the
> operator's data** (calendar, email, contacts, notes, memory) or act *as* the operator.

The ADR-0005 gate never leaves; collaboration just opens it to `{create-to-operator, generic-query,
web-search}` for the far-party principal. Operator-only read/act skills stay denied even in
collaboration. Spoofing the caller-ID wins, at most, this bounded create+query surface.

---

## 4. Assistance — detector → existing skill, mode-dependent action

iris watches the conversation for actionable moments and helps. Each is a detector feeding an
**existing** skill (gated, #99):

- **Capture:** numbers / emails / addresses / codes → `NotesStore` / contact
- **Commitment:** "Tuesday at 3" → offer calendar add (+ conflict-check vs your calendar)
- **Action item:** "send me the form" / "I'll call Friday" → reminder
- **Surface:** caller / topic → roster + 3-layer memory ("dentist, last call May 3, you owe a form")
- **Flag:** proposed time clashes with your calendar; caller contradicts a note
- **End-of-call:** the open-loops summary

**Same signal, mode-dependent transition** — numeric-density → *automated:* "read it back to the
caller"; *ride-along:* "noted 555-0199 for you." And **assurance flips with your presence:**
operator-on-the-call = high assurance → iris is proactive (auto-capture a number you both heard);
the automated path stays conservative.

**Capture verification:** indicate the saved note for an easy glance; **lean toward defaulting to
reading captured specifics back** (numbers/times are the costly-to-get-wrong items, and read-back
is the cheapest verification). The operator is present and fluent, so review/correct is a glance.

---

## 5. Recording, retention, consent

- **Message-taking** records like a **voicemail** (the raw recorder).
- **Retention:** keep the **notes, summaries, and extracted items** (not a long-term raw-audio
  store).
- **Consent:** **iris always introduces herself** at call start (the #96 consent gate, always-on).
  That introduction is the **blanket** — there is no separate privacy policy (this is not a
  company). Disclosure is required exactly when iris is *audible to the far party*; the always-on
  intro covers it, so stance changes need no re-disclosure.

---

## 6. Dimension axes (how this composes with presentation tuning)

Each tunable dimension has three **orthogonal** properties:

| dimension | cosmetic / trust | locked / dynamic | persistable per contact |
|---|---|---|---|
| language | cosmetic | **locked** (mid-call swap is hard; detect up front) | yes |
| cadence | cosmetic | **dynamic** (the trigger is mid-conversation) | yes (seed) |
| verbosity / affect | cosmetic | dynamic | optional |
| **mode (stance)** | **trust** | dynamic | **no — never persisted** (caller-ID spoofing) |

"Persisted" is orthogonal to "dynamic" — cadence both *seeds* from a contact (grandma starts
slow) and *adjusts* live. **mode** is the outlier: trust-bearing, so it is **never** persisted by
caller-ID; a contact may *suggest* collaboration, but the operator grants it per call (keyboard).

**Ownership:** this subsystem (ti-x5cd) **owns `mode`** (it's trust-bearing); the presentation
subsystem (ti-6371) consumes the persona a stance implies.

---

## 7. Operator controls (summary)

- **Keyboard grant + keyword pair** → enter/leave collaboration.
- **Type to iris** → silent invocation (private answer).
- **"hey iris …"** → audible invocation (audible answer).
- **Single quick button press** → approve iris going on-call when she proposes (must be fast, no
  jarring pause).
- **Force-language key** → recover a wrong locked language mid-call (preserve/reset behavior TBD;
  also editable in the contact). Rough support is fine for v1.

---

## Open questions

- **Console card UX** — what the glanceable cards actually show, and the interaction for one-tap
  approve. (Unresolved.)
- **Cleverer post-join addressing** — anything better than "hey iris" once she's collaborating
  (hard with open-ended search; not required).
- **Read-back default** — confirm whether captured specifics are read back to *the caller*, to
  *the operator privately*, or operator-configurable.

## Out of scope

Multi-party / conference calls; true mid-call language swap; profiling the operator; profiles or
modes that carry capability beyond §3.

## Build order (suggested)

Start with **silent-capture → visual note** (levels 0–1 only): catch the number/commitment, drop
it on the console, operator glances. Pure assistance value, *no* participation arbitration, no
on-call disclosure, no two-conversations problem. De-risks the golden path before the on-call
ladder.

## Pointers
`iris/notes.py`, `iris/calendar.py`, `iris/roster.py`, `iris/memory.py` (the skills assistance
feeds); #95 ride-along, #96 consent, #99 streaming gate; ADR-0005 (trust); mp6v.1 §5.
