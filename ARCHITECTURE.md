# Iris — Architecture

Iris is a voice agent you can phone: a Claude-powered conversational AI that rides
[tincan](https://github.com/quad341/tincan)'s Bluetooth phone bridge to hold spoken
phone conversations. This document is how we see the secretary working.

> **Status: v1 built and running.** The conversation loop, dispatch, the trust/capability
> model, the operator console, the skills (calendar / web / notes), the SCO call-audio
> tap, and the Call Card live-call capture layer (ADR-0006) have shipped — CI-gated by a
> heavy test suite — and Iris has held real, disclosed calls. This document describes the
> design; a few items remain marked _(planned)_ where noted (e.g. daemon-exposed audio,
> the semantic-memory layer).

## Product thesis & scope

Iris is **an always-around, local-first communications secretary** — she owns the operator's
**contacts, communication, and scheduling**: calls, messages, the people they talk to, the
commitments they make. She is deliberately **not a general assistant**. The differentiation —
and the reason to build her at all — is depth in the comms domain, where the incumbents are
shallow, cloud-bound, and don't act inside live conversations. Iris does: she joins the call,
speaks, takes the note, and gates what she'll do by *who's asking* (ADR-0002).

**Scope discipline:** every feature must deepen comms / scheduling / contacts. Resist
general-chatbot sprawl — the focus *is* the moat. The organizing entity is **Iris's own
contact roster** (her list, not a mirror of the phone's), around which calls, messaging,
memory, and scheduling cohere (see [ADR-0004](docs/adr/0004-inbound-events-and-interrupt-handling.md) §4,
and the trust/permission model in [ADR-0005](docs/adr/0005-trust-permission-and-assurance-model.md)). *(Direction set with the operator 2026-06-16.)*

## 1. Design principles

1. **Deployable platform, not a hardcoded app.** Every external capability — speech-to-text,
   text-to-speech, the LLM brain, memory — is a **swappable provider** behind a stable
   interface, selected by config.
2. **Local-first defaults.** Out of the box Iris runs on free/local engines. If you'd rather
   pay for a hosted API (OpenAI, ElevenLabs, …), drop it in. *An answer, not the only answer.*
3. **Route, don't always reason.** Known actions take a fast, deterministic path (intent →
   tool); the frontier LLM is the **fallback** for the hard, open-ended stuff — not the front door.
4. **Disclosure first.** Iris always tells the other party — warmly, up front — that she's an AI.
5. **An entity, not a kiosk.** She has a name and a voice and is built with care.
6. **Privacy.** Real phone numbers, contacts, and call content stay local and are never
   committed or sent to a service the user didn't opt into.

## 2. The two layers

**tincan** *(separate project, dependency)* — the phone/Bluetooth bridge. A Linux daemon
(`tincand`) that connects to an iPhone over Bluetooth and exposes:
- **D-Bus**: `im.tincan.Daemon` (status/capabilities), `im.tincan.Messages`
  (SMS/iMessage/contacts), and `im.tincan.Calls` (call control).
- An **MCP server** (`python -m tincand.mcp`) — tools for status, conversations, messages,
  contacts, notifications.
- Call audio over **HFP/SCO** via oFono + BlueZ + PipeWire.

**tincan-iris** *(this project)* — the brain. It drives tincan for call control and message
I/O, taps the call audio, and runs the conversation loop.

## 3. The conversation loop

```
 Far party ──cellular──▶ iPhone ──HFP/SCO──▶ PipeWire (bluez_input)
                                                     │  far-end audio
                                                     ▼
                                        ┌──────────────────────────┐
                                        │   STT    (speech → text)  │
                                        │      │                    │
                                        │   Memory + context        │
                                        │      │                    │
                                        │   Dispatch ──┬── Skill     │  ← §4
                                        │      │       └── LLM brain │
                                        │      ▼                    │
                                        │   TTS    (text → speech)  │
                                        └──────────────────────────┘
                                                     │  Iris's voice
                                                     ▼
 Far party ◀─cellular── iPhone ◀─HFP/SCO── PipeWire (bluez_output)

 Call control (answer / hang up / DTMF) ── tincan im.tincan.Calls (D-Bus) / MCP
```

## 4. Dispatch — fast path vs. smart path

Not every utterance needs a frontier model. Iris routes each turn:

- **Known actions → skills (fast path).** A registered set of well-known intents —
  *schedule an appointment, send a text, read me my messages, take a message, what's on my
  calendar* — handled deterministically via **self-authored direct-API integrations**
  (e.g. Google Calendar REST), orchestrated by the warm local model. **No MCP servers at
  runtime, and the cloud model never touches tools** — see
  [ADR-0001](docs/adr/0001-no-mcp-direct-api-via-qwen.md). Snappy, cheap, reliable, predictable.
- **Everything else → the LLM (smart path).** Open-ended conversation and ambiguous/novel
  requests fall back to the generic LLM brain (local Qwen or Claude Haiku).

```
 STT text ─▶ Router ──┬── known intent ──▶ Skill (MCP tool / OAuth API) ──▶ result
                      └── otherwise ──────▶ LLM brain (Qwen / Haiku) ──────▶ reply
```

A lightweight **router / intent-classifier** (rules or a small local model — itself pluggable)
decides the path. **Skills are plugins:** a new one registers an *intent* + its *handler*
(an MCP tool call and/or an OAuth-scoped API). This keeps the common cases instant and reserves
the expensive model for reasoning that actually needs it. _(Shipped: the tiered router
(`Tier0Rules → Tier1Qwen → Tier2RawHaiku`) and the skill registry — see `iris/brain.py`,
`iris/lanes.py`, `iris/skills.py`.)_

## 4b. Capabilities, trust & context — the v1 model

> Decided 2026-06-15; the safety model is **[ADR-0002](docs/adr/0002-capability-gating-by-speaker-channel.md)**.

**Who is speaking is known from the audio channel, not voice recognition.** The
operator is on the local mic; the far party arrives on `bluez_input`. Each
transcript is tagged with its source and that tag rides through the pipeline — so
Iris can attribute every command and gate by *who asked*.

**Two capability modes, chosen per call:**

| Mode | Who gets it | What she can do |
|---|---|---|
| **Demo** *(default — any caller)* | everyone, always | introduce herself · the time · answer from model knowledge. **No tools, no personal data either way.** Telemarketer-safe. |
| **Full** | the operator always; the far party only when the operator flips a **per-call, non-sticky** trust flag (re-armed every call, auto-off on hangup) | the real skills — calendar, notes, lookups, messaging |

The trust flag is **operator-only and spoof-proof**: honored only when granted on
the *mic* channel. For the far party the rule is **requests push *in*, data never
pulls *out*** — they can create a follow-up *for the operator*, never extract the
operator's data. Iris also **acts without disclosing** (answers "that works" to a
free/busy check, never the underlying appointment). Web fetch is **full-mode,
operator-initiated only** (a fetched page is untrusted, prompt-injection input).

**Dispatch, concretely.** In demo mode the router never reaches a skill — Tier 0
(introduce/time) + the LLM knowledge lane only. In full mode the warm local model
**orchestrates the skills**: it picks `{skill, args}` or decides "just talk."

**First full-mode skill: explicit notes & follow-ups** — *"Iris, note that…"* /
*"follow up on…"*. Deterministic, reliable, and it proves the action loop. The
**conversation summary is the same artifact as the context "gist" below**, so we
take notes now and the summary emerges for free.

**Context — always listen, act only when addressed.** Ambient *listening* is
cheap (local STT → a buffer); ambient *acting* is rare and addressed-only. When
addressed, she resolves references from three layers:

1. **Rolling window** — the last few minutes verbatim (a cyclic buffer); resolves *"search for that."*
2. **Running gist** — periodically the local model compresses older turns into a tiny summary that persists across a long call.
3. **On-demand** — for specifics that aged out: retrieve from the local transcript, or simply *ask* ("which trip do you mean?").

This keeps her out of "kiosk mode" (you needn't restate everything) without ever
holding an hour of transcript in the model. **Nothing proactive/unprompted in
v1** — she speaks only when addressed; proactive behavior is a later design.

**Personality has to *do* something.** A beat must either be intrinsically
relational (the AI disclosure, a warm greeting, a signature sign-off — those
build the entity, that is their point) or drive a real action. So "how'd I do?"
becomes *"I caught two follow-ups — want me to handle either?"*, and feedback
("you were too formal with Mom") **writes to a preferences store** that actually
changes the next call. Tone of every action + a feedback channel — not a
decorative layer.

## 5. Provider slots

Each slot has a local-first default and swaps via config:

| Slot | Default (local / free) | Swap-in (hosted / paid) |
|---|---|---|
| **STT** | **Whisper** (`faster-whisper`, `small.en`) | OpenAI Whisper · Deepgram |
| **TTS** | **Kokoro** (`kokoro-82M`) | ElevenLabs · OpenAI · Cartesia |
| **Brain (LLM fallback)** | local (e.g. Qwen via llama.cpp) | **Claude Haiku** _(recommended)_ · OpenAI |
| **Router** | rules / small local classifier | small LLM |
| **Memory** | SQLite + sqlite-vec | Mem0 · Letta · hosted vector DB |
| **Embeddings** | local model | OpenAI · others |

Each is an abstract `Provider` interface; a config file selects and parameterizes the
backend. New providers (and new skills) implement the interface — no core changes.

## 6. tincan integration contract

What tincan-iris relies on (grounded in tincan's interface surface):

- **Status & capabilities** — `im.tincan.Daemon.GetStatus()` → check `connected` and the
  capability flags *before* assuming a feature exists.
- **Call control** — `im.tincan.Calls`: `Dial / Answer / Hangup / SendDtmf`; signals
  `IncomingCall / CallConnected / CallEnded / AudioError / AudioRestored`. (Phase 1 scope =
  single call, dial/answer/hangup/DTMF; multi-call/hold is Phase 2+.)
- **Messaging** *(optional — for an SMS-aware secretary, and a ready-made skill)* —
  `im.tincan.Messages`: list conversations, read/send, contacts. Also exposed as MCP tools.
- **Notifications** *(optional)* — `im.tincan.Daemon.AppNotificationReceived` (ANCS mirror).

### The audio tap (the important gap)

**tincand does not yet expose a call-audio API.** When a call goes active, WirePlumber/oFono
auto-create PipeWire SCO nodes; Iris taps them **directly via PipeWire**:
- **Far-end → Iris:** capture `bluez_input.<bt_mac>.*` → STT.
- **Iris → uplink:** play TTS into `bluez_output.<bt_mac>.*`.
- Set HFP `CallVolume` (oFono) and link the nodes to/from Iris's audio (e.g. `pw-link`).

This path was validated end-to-end on hardware (2026-06-11). Moving the routing **into the
daemon** (a future `im.tincan.Audio` interface, or daemon-managed routing) is tracked on the
tincan side, so Iris won't have to know the Bluetooth MAC or do its own PipeWire wiring. _(planned)_

## 7. Memory

> **Status (v1):** the structured store and an in-call context layer have shipped — a local
> **SQLite** transcript + notes/lists store (`iris/transcript.py`, `iris/list_store.py`) and a
> two-tier in-call **context** (`iris/context.py`: rolling window + a Qwen-compressed gist).
> The **semantic-recall / vector** layer below is an **open design question** — whether it
> replaces, complements, or layers onto the context tiers is for the architect to decide
> ([issue #8](https://github.com/quad341/tincan-iris/issues/8)).

A secretary has to remember people and past calls — plain markdown / task-trackers are the
wrong shape. Two local layers:
1. **Structured store (SQLite):** call log, transcripts, contacts, durable facts
   ("appointment Tuesday"). (tincan already uses SQLite, so it's in-house.)
2. **Semantic recall (vector index):** `sqlite-vec` (vectors *inside* the same SQLite file —
   zero extra infra) or LanceDB, for "what did we talk about last time."

Optionally, a purpose-built **agent-memory layer** (Mem0 or Letta/MemGPT) that
auto-extracts / summarizes / forgets across conversations. All behind the pluggable
**Memory** provider.

## 8. Hardware foundation

Call audio rides HFP/SCO over a Bluetooth adapter. Validated 2026-06-11:
- ✅ **RTL8761B (ASUS USB-BT500)** USB dongle — two-way SCO audio works. Requires a SELinux
  policy for the SCO fd, and **USB autosuspend disabled** (else the dongle suspends mid-call
  and garbles audio).
- ❌ Built-in **MediaTek MT7925** — call *control* works, but SCO *audio* fails at the
  firmware level.

(See tincan's COMPATIBILITY notes for the full adapter matrix.)

## 9. Roadmap / open questions

**Shipped since this doc's first draft:**
- ✅ The skill/router contract (intent registry + tiered handler) — the fast path
- ✅ Turn-taking & barge-in (interrupt / stop mid-reply)
- ✅ Streaming STT for low latency
- ✅ OAuth/token management for the calendar skill
- ✅ **The demo** — Iris has held short, *disclosed* phone conversations with real callers

**Still open:**
- Echo-cancelled **Discord / virtual-audio** calling (beyond SCO) — endpoint + speaking gate
- **Proactive** speech: built but shipped *disabled* — needs the "never talk over either party / genuine-pause" design before it's enabled
- **Semantic memory** — the vector-recall layer (§7) is an open design question ([#8](https://github.com/quad341/tincan-iris/issues/8))
- The audio tap: direct PipeWire (now) → daemon-exposed `im.tincan.Audio` (later, tincan side)
- Multi-call / hold (tincan Phase 2)

## Credits

- **Artwork** generated locally with [stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp)
  (ggml + Vulkan) running **Stable Diffusion XL** on an **AMD Strix Halo** iGPU
  (Radeon 8060S / Mesa RADV). The mascot logo is hand-drawn vector via **pycairo**.
- Built on **[tincan](https://github.com/quad341/tincan)**.
