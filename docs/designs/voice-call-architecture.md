# Voice-call architecture (mp6v.1)

> **Status:** Design. The Pipecat adoption (OQ-1) is **validated by an integration spike**
> (2026-06-25) — see [`pipecat-bridge.md`](pipecat-bridge.md) for the spike results and the
> implementation brief. The streaming half is shipped (#99). Adopt Pipecat for the spine;
> the brain keeps the gate.
>
> **Scope:** Assisted-mode voice secretary over Bluetooth HFP. The human is on the
> call and iris **discloses** that she is listening; fully-autonomous calling is out
> of scope. First target: screening / taking messages, then appointment scheduling.
> Maps to the `mp6v` epic (a tincan bead — this doc is the agent-side architecture;
> the audio/transport half is tincand's, noted below).

This doc is mostly tincan-iris (the agent). It cites the audio bridge (tincand /
tincan) where the boundary matters, and the work already shipped.

---

## 1. The two halves and the boundary

```
            BT-HFP (SCO, ~8 kHz telephone audio)
   far party  ⇄  ┌─────────────────────────────────────┐
                 │  tincand  — owns the AUDIO            │
                 │   • SCO downlink tap (far → here)     │
                 │   • uplink mixer (mic + agent → far)  │   ← new primitive, §6
                 │   • always-on raw recorder            │
                 └───────────────── PCM frames ──────────┘
                                     ⇅  (audio I/O contract)
                 ┌─────────────────────────────────────┐
                 │  iris  — the VOICE AGENT (a client)  │
                 │   real-time pipeline (Pipecat, §3)    │
                 │     VAD → STT → ⟨brain⟩ → TTS         │
                 │   brain owns routing + the gate (§4)  │
                 │   profiles/tuning (§5)                │
                 └─────────────────────────────────────┘
```

- **tincand owns audio.** It taps the SCO downlink, mixes the uplink, and keeps a raw
  recorder running. It exposes PCM frames; it does **not** know about STT/LLM/TTS.
- **iris is a client** of that audio. It runs the real-time STT→brain→TTS pipeline and
  speaks back onto the uplink.
- The split keeps media (tincand) and cognition (iris) independently testable, and lets
  the agent run against a *fake* audio endpoint with no Bluetooth (see §7).

**Already shipped toward this:**
- SCO call audio + ride-along — iris adopts the live SCO endpoint on `CallConnected`
  (`ti-veyx`, #95); the `AudioEndpoint` protocol (`iris/audio/endpoint.py`) is the swap point.
- Consent / disclosure gate — iris announces herself before listening to the far party
  (`ti-rqhn`, #96).
- ADR-0006 call-handling daemon — `PostureManager` / `PolicyResolver` / `DaemonAPI` /
  `DaemonProxy` (#98). The daemon socket is the natural control seam.
- Streaming-skill bridge (#99) — see §4.

---

## 2. Latency is the master constraint

Target **EERL < 800 ms** — *far-party stops speaking → first audio of iris's reply on the
uplink* (EERL = end-to-end response latency; budget + harness live in mp6v.2).

Everything below is shaped by that budget. Measured LLM-side numbers (warm local Qwen,
2026-06-25) anchor the design:

| stage | measured | note |
|---|---|---|
| grammar dispatch (routing) | ~190 ms | serial cost of the ADR-0005-safe two-call structure (§4) |
| chat TTFT (first token) | ~17 ms | warm, cached prompt |
| chat first **sentence** (→ first TTS chunk) | ~156 ms | the streaming lever |

Projected chat EERL, two-call + streaming: **~685 ms** (STT/TTS as budgets) — under 800.
The non-streaming baseline is ~826 ms, *over* — so **streaming is what buys the budget**, and
it is iris-native (a ~20-line `stream:True` + sentence chunking), not something Pipecat had
to provide.

---

## 3. The real-time pipeline — Pipecat (OQ-1)

**Decision (leading candidate): adopt Pipecat for the real-time spine; the brain keeps the
gate.** LiveKit's differentiators (WebRTC SFU, SIP telephony, multi-participant scale) are
exactly what we *don't* need — tincand owns the BT-SCO transport and feeds PCM. Pipecat is a
transport-agnostic pipeline of frame processors, which is the part we want.

What iris has vs. what Pipecat adds:

| capability | iris today | who provides | needed? |
|---|---|---|---|
| streaming TTS + LLM→TTS pipelining | ❌ batch | **iris-native** (#99 + per-sentence synth) | yes |
| true mid-stream cancel (LLM + TTS) | ❌ coarse | Pipecat | yes |
| full-duplex barge-in *detection* (hear over self) | ❌ half-duplex | Pipecat (AEC+VAD) | yes — phone calls |
| concurrent detectors / tuners (§5) | ❌ single-thread | Pipecat (processor graph) | yes — the meta-feature |
| semantic turn detection | ⚠️ 800 ms VAD | Pipecat/LiveKit | nice |
| WebRTC/SIP transport, multi-party | n/a | LiveKit | **no — tincand owns SCO** |

The case for adopt rests on the bottom-need rows (mid-stream cancel, full-duplex barge-in,
concurrent detectors), **not** streaming (which we proved is iris-native). It is **not yet
validated by a Pipecat prototype** — that is the next spike.

---

## 4. The brain bridge — the load-bearing piece

iris's brain is **not** a plain LLM; it is a tiered router with a permission gate
(`iris/brain.py`, `iris/lanes.py`). Any pipeline must preserve it:

- **Tiers:** Tier-0 rules (deterministic, <1 ms) → Tier-1 local Qwen (warm) → Tier-2 Haiku
  (explicit "ask Haiku", cloud, no tools).
- **Two-call Tier-1 (keep it).** A *grammar-constrained dispatch* call decides the route:
  it forces `{"skill": "<name>"|"none", "args": {...}}`, and the grammar is **speaker-scoped**
  so the far party cannot even *name* an operator-only skill. Then either:
  - skill proposed → **propose → authorize → execute** (the daemon gate, ADR-0005); or
  - `"none"` → a chat completion (streamed).
- **Why not collapse to one streaming call with inline tool-calls:** the grammar dispatch is
  what makes "the model is never the trust boundary" *literally* true. A combined stream
  interleaves prose and tool-calls and re-establishing that guarantee mid-stream is exactly
  the subtle thing that goes wrong. The two-call structure costs ~190 ms serial — and §2 shows
  that fits. **Keep the clean structure; it is also the fast-enough one.**

**Bridge = wrap `Brain` as a Pipecat LLM service.** The wrapper runs the tiered router and the
gate *inside* it; Pipecat transports audio and never becomes the trust boundary. For the chat
path it streams tokens → sentence chunks → TTS; for skills it runs the authorized skill and
streams (or completes) its output.

**Shipped (#99): the streaming-skill bridge.** `StreamingSkill` opt-in protocol
(`run_stream`), `Brain.respond_stream()` / `_stream_proposal()` with the **same authorize gate
as `respond()`**, and `AgendaSkill` as the first streaming skill. Tested invariant: **authorize
fires exactly once, before the first chunk; a denied skill never runs.** This is the proof that
output can stream while the gate stays exactly in place.

**Open on the bridge:** filler-masking → streaming (first tokens are the latency hide; keep a
"working on it" only for slow *tool* calls); dispatch accuracy (`ti-dp7p`, in flight — chitchat
currently misroutes to `echo`/`time`, which gates the chat-streaming win).

---

## 5. On-the-fly profiles & tuning (the multilingual meta-feature)

Multilingual is the first instance of a general pattern: **adapt a cosmetic runtime setting,
on the fly, from a bounded pre-loaded set.** It generalizes ADR-0006's `PostureManager` (a
single hand-toggled dimension) to many detector-driven dimensions.

```
Profile     a bundle of settings for one dimension
              language = { whisper hint, TTS voice, response-language prompt }
              cadence  = { TTS speed }
Detector    a heuristic on the current turn that PROPOSES a profile
Transition  applies the chosen profile, then LOCKS it for the call
```

**v1 dimensions: { language, cadence }.**

- **Config (operator level):** the *loaded & possible* set — an ordered list of 2–5 languages,
  a cadence range. Bounded, so models/voices stay warm.
- **Annotations (contact level):** per-contact picks, stored as **prefs on the roster contact**
  (reuse — `brain` already loads `prefs.hint(call_context)` each call). e.g. *grandma →
  `{lang: es, cadence: slow}`*.
- **Resolution (per call, per dimension), then lock:**
  ```
  operator override (key; language only in v1)  >  contact annotation (by caller-ID)
     >  detector (utterance 1)  >  default
  ```
  Known callers need **no detection** — grandma is Spanish + slow from the first word.
  Detection is reserved for unknown / screened callers.
- **Detectors v1 (single-utterance, implicit):**
  - **language** — Whisper detection, *constrained to the loaded set*, operator ordering as
    prior. Lock for the call (no mid-call swap).
  - **cadence** — re-ask trigger (*"¿cómo?" / "sorry, again?"*) → step TTS speed down a notch.

**The invariant that makes caller-keyed profiles safe.** Profiles key on **unauthenticated**
signal (caller ID is spoofable; detection is inference). Therefore:

> **Profiles are cosmetic — language, voice, cadence, persona-*style*. They carry zero
> capability. Trust stays in the ADR-0005 gate, keyed on the operator's grant *this call*,
> never on who the caller appears to be.**

A caller-ID match to "grandma" earns a slower Spanish greeting and **nothing else**; far-trust
still starts closed and the operator still has to grant. Spoofing the number wins only the
wrong accent. (This mirrors iris's existing default-closed `_resolve_is_operator`.)

**Future dimensions (same shape):** register/formality (match usted vs tú), verbosity mirroring,
affect (calm down for an urgent caller — the "uncanny" tier; wants a subtlety dial). Each is a
*pure function of the current turn*, which is both simpler and the natural boundary that keeps
"adaptive" from becoming "surveillant." **Do not build the general tuning framework until 2–3
instances exist** — ship language+cadence, structured as Profile/Detector/Transition, and let
the abstraction earn itself.

**Why this is the strongest Pipecat argument.** N independent detectors watching the same
utterance *concurrently* is native to a processor graph and awkward in iris's single-threaded
conductor.

---

## 6. Uplink synthesis — the one new primitive

Today `tincand` wires SCO bidirectionally via `pw-link` (mic → `bluez_output` already works —
the far party hears the operator). mp6v.5 needs iris's TTS **mixed onto that uplink** so the
far party hears *iris*. This is a **PipeWire mixing** problem, not a new transport: insert a
null-sink/loopback so `mic + agent_tts → bluez_output`. The uplink transport is proven; the
mixer + the "who is on the uplink when" policy (barge-in: agent yields to the human) is the new
work. The **disclosure announcement** at call start reuses the consent gate (#96). Telephone
fidelity is low, so streaming TTS optimizes for *time-to-first-audio*, not quality.

---

## 7. Testing without real calls

Real calls bother people; they are a *final* check, not the dev loop. (Full plan: mp6v.2.)
Built on the existing `AudioEndpoint` seam:

- **Synthetic far-party fixtures** — caller turns generated with a *different* TTS voice, then
  telephone-degraded (16k→8k, codec/line noise).
- **`LoopbackAudioEndpoint`** — `capture()` returns the next fixture, `playback()` writes the
  uplink to a file. Drops into the slot the BT-SCO endpoint uses. No Bluetooth.
- **Synthetic caller** — automated multi-turn driver; injects *barge-in* by starting the next
  turn while iris is still speaking.
- **Text-level dual-path** — for the gate: feed transcripts to both `respond` and
  `respond_stream` and diff lane/skill/**authz**/reply. Runs in CI, no audio.
- **EERL clock** — we own the fixture, so we know when far-party audio ends; timestamp the
  first uplink sample.

---

## 8. Security invariants (non-negotiable)

1. **The model is never the trust boundary** (ADR-0005). Grammar-scoped dispatch +
   propose→authorize→execute. A coaxed model cannot get past a *proposal*.
2. **Streaming changes output shape, never the gate.** Authorize once, before the first chunk
   (proven, #99).
3. **Tuning changes style, never permissions.** Profiles are cosmetic; capability stays gated
   on the operator's grant, not on caller-ID or detection.
4. **Disclosure.** Assisted-mode: iris announces she is listening (#96), before any far-party
   audio is processed.

---

## Open questions / next

- ~~**Pipecat integration spike.**~~ **Done (2026-06-25) — OQ-1 validated.** A `BrainLLMService`
  wrapping `Brain.respond_stream` was driven through a real Pipecat pipeline: it streamed, an
  `InterruptionFrame` cancelled mid-stream (barge-in), and the gate authorized once / denied the
  far party. See [`pipecat-bridge.md`](pipecat-bridge.md) for results + the implementation brief.
  Remaining spike: the *concurrent-detectors* pattern (language ∥ cadence) for the §5 meta-feature.
- **Dispatch accuracy** — `ti-dp7p` (in flight): chitchat misroutes to `echo`/`time`; gates the
  chat-streaming win.
- **Uplink mixer feasibility** on the live SCO stack (mp6v.3/.5).
- **Per-sentence streaming TTS** — kokoro synth per sentence vs. true sub-sentence streaming.
- **Contacts management with iris** — annotations are the surface; identity, caller-ID handling,
  roster grooming, "what do I know about this person" is a deeper thread (parked).

## Out of scope

Live translation; mid-call language swap; fully-autonomous calling; profiles that carry
capability.
