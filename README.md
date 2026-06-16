<div align="center">

<img src="assets/iris-logo.png" width="150" alt="Iris logo"/>

# Iris

**Your AI co-pilot on the call — with you, not instead of you.** Iris is a Claude-powered voice agent that rides [tincan](https://github.com/quad341/tincan)'s Bluetooth phone bridge, listens to a live call alongside you, and speaks up when you ask her to — always disclosing she's an AI.

</div>

<div align="center">

<img src="assets/iris-hero.png" width="320" alt="Iris, Bearer of the Can"/>

<sub><i>“Iris, Bearer of the Can” — generated locally on an AMD iGPU, network-isolated, in 44 seconds.</i></sub>

</div>

---

## What is this?

[**tincan**](https://github.com/quad341/tincan) turns a Linux box + a Bluetooth adapter into a bridge to your phone — call control, messaging (MAP), notifications (ANCS), and **two-way HFP call audio**, all over D-Bus + MCP.

**`tincan-iris` is the brain on top of that bridge** — and in v1 she's a **supervised co-pilot**, not an autonomous answerphone. You're always on the call. Iris listens to both sides and acts only when she's **addressed** (“*Iris, …*”). She thinks **locally first** — a tiered brain (deterministic rules → a warm local model → a cloud model only on explicit escalation) — and speaks back onto the line with a synthesized voice. The other party hears a real conversation with *you*, plus Iris when you bring her in.

> **Iris** — named for the Greek messenger goddess who carried word between worlds. She introduces herself by name, and she always discloses that she's an AI.

## How it works

```
        Far party (phone)
              │  cellular
              ▼
   ┌───────────┐   HFP/SCO audio (PipeWire)   ┌────────────────────────────────────┐
   │   tincan  │◀────────────────────────────▶│             tincan-iris            │
   │  (daemon) │  D-Bus im.tincan.Calls + MCP  │  STT → tiered brain → TTS          │
   └───────────┘  (call control)              │  rules · local Qwen · Haiku (esc.) │
        ▲                                      │  + operator console & trust gate   │
        │ mic                                  └────────────────────────────────────┘
   operator (you) — hears both sides, addresses Iris by name
```

- **tincan** *(dependency)* — the stable phone/Bluetooth bridge. Exposes `im.tincan.Calls` over D-Bus, an MCP server for call/message control, and the SCO call audio as PipeWire nodes (`bluez_input` = far-end voice, `bluez_output` = the uplink).
- **tincan-iris** *(this repo)* — the conversational loop, supervised by you at a console:
  1. **Listen** — capture both channels (you on the mic, the far party on `bluez_input`), stream each to speech-to-text, tagged by speaker.
  2. **Think** — route each turn: rules and known skills take the fast path; the **local model** reasons; a **cloud model (Haiku)** only on an explicit “*ask Haiku…*” — and never in demo mode. (See [ADR-0001](docs/adr/0001-no-mcp-direct-api-via-qwen.md).)
  3. **Speak** — synthesize the reply (Kokoro) and play it into `bluez_output`.
  4. **Act** — answer, hang up, send a text, take a note, check the calendar — via tincan's D-Bus / MCP, gated by who's allowed (below).

## Who can do what — trust by channel

Iris knows *who's speaking from the audio channel*, not voice ID: you're on the mic, the far party is on `bluez_input`. (See [ADR-0002](docs/adr/0002-capability-gating-by-speaker-channel.md).)

| Mode | Who | What she'll do |
|---|---|---|
| **Demo** *(default — any caller)* | everyone | introduce herself · the time · answer from model knowledge. **No tools, no personal data.** Telemarketer-safe. |
| **Full** | you, always; the far party only when **you** grant it (per-call, non-sticky, auto-off on hangup) | the real skills — calendar, notes, lookups, messaging |

The grant is **operator-only and spoof-proof** — honored only on the mic channel, so a caller can't talk their way into your data. For the far party the rule is **requests push *in*, data never pulls *out*.**

## Status

**v1 is built and running** — and has already held real, **disclosed** phone calls.

**Shipped:** streaming STT (Whisper) + Kokoro TTS · the tiered local-first brain (rules → local Qwen → Haiku on escalation) · skill/LLM dispatch · call control + spoken AI disclosure · calendar (OAuth) · web search · notes & scratchpad · conversation context (rolling window + compressed gist) · the **operator console** (Textual) · the DEMO/FULL **trust model** · SCO call-audio tap with echo-cancellation. *(341 tests, CI-green.)*

**In progress / next:** echo-cancelled **Discord / virtual-audio** calling (beyond SCO) · **proactive** delivery (built, shipped *disabled* — pending the “don't talk over either party” design) · the memory layer's semantic-recall design ([issue #8](https://github.com/quad341/tincan-iris/issues/8)).

## Principles

- **You stay in the mix.** Iris is a co-pilot, not a replacement — you're on every call, you address her by name, and far-party access is yours to grant. Autonomy is opt-in, and later.
- **Disclosure first.** Iris always tells the other party she's an AI — warmly, and up front.
- **Local-first.** The default engines are free and local, and inference runs network-isolated. A hosted API is *an* answer, not the only one.
- **Route, don't always reason.** Known actions take a fast, deterministic path; the cloud model is the fallback, not the front door.
- **An entity, not a kiosk.** She has a name and a voice, and is treated with care in how she speaks and how we build her.

## Built on tincan

This project depends on **[tincan](https://github.com/quad341/tincan)** — see its docs for phone-bridge setup (Bluetooth adapter, HFP/SCO, oFono, SELinux, MCP).

## More

- **[Architecture](ARCHITECTURE.md)** — the loop, the dispatch layer (skills vs. LLM), the trust/capability model, pluggable providers, the tincan contract
- **[Security](SECURITY.md)** — network-isolated model inference + call-data privacy
- **[Roadmap](https://github.com/quad341/tincan-iris/issues?q=is%3Aissue+label%3Aroadmap)** — where we're headed (intent, not promises)

## License

MIT — see [LICENSE](LICENSE).
