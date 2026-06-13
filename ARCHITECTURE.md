# Iris — Architecture

Iris is a voice agent you can phone: a Claude-powered conversational AI that rides
[tincan](https://github.com/quad341/tincan)'s Bluetooth phone bridge to hold spoken
phone conversations. This document is how we see the secretary working.

> **Status: design + early build.** The phone-audio foundation is validated on real
> hardware (2026-06-11); the agent itself is being built. Anything marked _(planned)_
> is intent, not yet implemented.

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
the expensive model for reasoning that actually needs it. _(planned — formalize the skill/router
contract early; see beads.)_

## 5. Provider slots

Each slot has a local-first default and swaps via config:

| Slot | Default (local / free) | Swap-in (hosted / paid) |
|---|---|---|
| **STT** | whisper.cpp | OpenAI Whisper · Deepgram |
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

- **Formalize the skill/router contract** (intent registry + handler interface) — the fast path
- Turn-taking & barge-in — the latency budget for natural back-and-forth
- Streaming STT + incremental LLM for low latency
- OAuth/token management for skills (calendar, etc.)
- The audio tap: direct PipeWire (now) → daemon-exposed (later)
- Multi-call / hold (tincan Phase 2)
- **The demo:** Iris holds a short, *disclosed* phone conversation with a real caller

## Credits

- **Artwork** generated locally with [stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp)
  (ggml + Vulkan) running **Stable Diffusion XL** on an **AMD Strix Halo** iGPU
  (Radeon 8060S / Mesa RADV). The mascot logo is hand-drawn vector via **pycairo**.
- Built on **[tincan](https://github.com/quad341/tincan)**.
