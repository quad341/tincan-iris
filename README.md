<div align="center">

<img src="assets/iris-logo.png" width="150" alt="Iris logo"/>

# Iris

**A voice agent you can phone.** Iris is a Claude-powered conversational AI that rides [tincan](https://github.com/quad341/tincan)'s Bluetooth phone bridge to hold real, spoken conversations over a live phone call.

</div>

---

## What is this?

[**tincan**](https://github.com/quad341/tincan) turns a Linux box + a Bluetooth adapter into a bridge to your phone — call control, messaging (MAP), notifications (ANCS), and **two-way HFP call audio**, all over D-Bus + MCP.

**`tincan-iris` is the brain on top of that bridge.** It taps the live call audio, transcribes the far party in real time, thinks with a low-latency Claude model (Haiku), and speaks back onto the call with synthesized voice — so the person on the other end is simply *talking to Iris*.

> **Iris** — named for the Greek messenger goddess who carried word between worlds. She introduces herself by name, and she always discloses that she's an AI.

## How it works

```
        Far party (phone)
              │  cellular
              ▼
   ┌───────────┐   HFP/SCO audio (PipeWire)   ┌─────────────────────────────┐
   │   tincan  │◀────────────────────────────▶│         tincan-iris         │
   │  (daemon) │   D-Bus im.tincan.Calls + MCP │  STT → Claude (Haiku) → TTS  │
   └───────────┘   (call control)             └─────────────────────────────┘
```

- **tincan** *(dependency)* — the stable phone/Bluetooth bridge. Exposes `im.tincan.Calls` over D-Bus, an MCP server for call/message control, and the SCO call audio as PipeWire nodes (`bluez_input` = the far-end voice, `bluez_output` = the uplink).
- **tincan-iris** *(this repo)* — the conversational loop:
  1. **Listen** — capture `bluez_input`, stream it to speech-to-text.
  2. **Think** — feed the running transcript to Claude (Haiku, chosen for low latency).
  3. **Speak** — synthesize the reply and play it into `bluez_output`.
  4. **Act** — answer, hang up, send a text, etc. via tincan's MCP / D-Bus.

The audio foundation this builds on was validated end-to-end on 2026-06-11 (RTL8761B HFP/SCO — two-way call audio confirmed).

## Status

🌱 **Early.** The phone-audio foundation works; Iris herself is being built. First milestone: a short, **disclosed** phone conversation with a real caller.

## Principles

- **Disclosure first.** Iris always tells the other party she's an AI — warmly, and up front.
- **An entity, not a kiosk.** She has a name and a voice, and is treated with care in how she speaks and how we build her.

## Roadmap

- [ ] Live streaming transcription of the far party
- [ ] Claude (Haiku) conversation loop with turn-taking / barge-in
- [ ] Voice synthesis onto the uplink + spoken AI disclosure
- [ ] Call control via tincan MCP (answer / hang up / transfer / text)
- [ ] **Demo:** Iris holds a short conversation with a caller

## Built on tincan

This project depends on **[tincan](https://github.com/quad341/tincan)** — see its docs for phone-bridge setup (Bluetooth adapter, HFP/SCO, oFono, SELinux, MCP).

## License

MIT — see [LICENSE](LICENSE).
