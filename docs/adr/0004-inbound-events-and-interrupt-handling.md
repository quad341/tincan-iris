# ADR-0004 — Inbound Events & Interrupt Handling

- **Status:** proposed (2026-06-16)
- **Related:** [ADR-0001](0001-no-mcp-direct-api-via-qwen.md) (no MCP, local direct-API), [ADR-0002](0002-capability-gating-by-speaker-channel.md) (capability/trust by channel), ADR-0003 (memory — currently on bead `ti-wc2`), [ARCHITECTURE.md §6](../../ARCHITECTURE.md) (tincan contract)

---

## Context

For the always-around comms-secretary direction, Iris must react to **inbound events pushed from the phone** via tincan: an **incoming call**, a **new text**, a **phone notification**. These are *interrupts*. The **incoming call is hard-real-time** — Iris has to decide and act inside the ring window, and ideally intercept *very* quickly.

This ADR records how inbound events are delivered, kept low-latency, prioritized, and handled — and the default call-handling policy.

## Substrate — already exists

`tincand/dbus_service.py` already emits the D-Bus signals we need:

| Interface | Signal | Payload |
|---|---|---|
| `im.tincan.Calls` | `IncomingCall` | `(caller_name, caller_number)` |
| `im.tincan.Calls` | `CallConnected` / `CallEnded` | — |
| `im.tincan.Calls` | `AudioError` / `AudioRestored` | — |
| `im.tincan.Messages` | `MessageReceived` | `dict` |
| `im.tincan.Daemon` | `AppNotificationReceived` | `dict` |

Iris's `iris/call_control.py` `TincanCallControl` already subscribes to the **Calls** signals on a background GLib main-loop thread, with **opt-in auto-answer (default off)**. It does **not** yet subscribe to Messages or Daemon notifications.

## Decision

### 1. The always-on presence is a *resident warm daemon*

The always-around presence is a single long-lived service that, in steady state, keeps the **entire pipeline hot**:

- the **audio graph up** (virtual devices / SCO endpoints as applicable),
- **STT, TTS, and the LLM sessions resident** (whisper warm, Kokoro warm, llama-server/Qwen warm),
- **Iris's contact roster loaded** in memory (§4),
- and the **D-Bus listener subscribed** to Calls + Messages + Daemon notifications, normalizing each into a typed event on Iris's event queue.

Cold-start costs (model load, device creation, session warm-up) are paid **once at daemon start**, never on the critical path of an event. **The operator accepts the steady-state resource cost** (RAM/VRAM/CPU held continuously) in exchange for zero per-event latency.

This generalizes `TincanCallControl` (today the seed: a Calls-only listener) into the service spine, and **inverts ownership**: today `IrisConsole.__init__` constructs STT/TTS/Brain/endpoint *per launch*, so the ephemeral console owns the heavy resources. Under this ADR a **long-lived service owns the warm pipeline and the console becomes a client/view** that attaches to it.

### 2. Priority / preemption

Inbound events are interrupts with priority:

```
incoming call  (highest, hard-real-time)
  > operator command
    > inbound text / notification  (soft — queue, surface on a natural pause)
```

A higher-priority interrupt preempts low-priority activity (an incoming call preempts a reminder read-out). Iris never talks over either party (see ADR-0002 and the proactive-speech design).

### 3. Call latency path

With the warm daemon (§1), the critical path at call time is only the irreducible work:

```
IncomingCall (D-Bus push, ~ms)
  → policy decision (~ms — in-memory roster lookup)
    → [if answering] Answer()
      → SCO audio-up   ← the one inherent cost (BlueZ/oFono call setup;
                          tincan signals readiness via call_setup_ready / CallConnected)
        → play pre-rendered disclosure WAV   (instant — already in memory)
```

No model load, device spin-up, or TTS synthesis is on this path. The **AI disclosure is a pre-rendered cached WAV** played the instant audio is ready — TTS/LLM stay off the critical path. The remaining latency is SCO setup; the design goal is the greeting audible well within the ring window.

### 4. Call-handling policy: per-caller rules on **Iris's own roster** (DECISION)

Iris maintains **her own contact list** — *not* merely a read of the phone's address book. Each entry carries a **handling rule**, so routing is per-caller and richer than known/unknown (rules below are illustrative, not locked):

| Handling | Behavior on `IncomingCall` |
|---|---|
| **ring-through** | announce ("Mom is calling") and let it ring to the operator; Iris does not auto-answer |
| **VIP / interrupt** | ring-through, and preempt whatever Iris/operator is doing |
| **screen** | auto-answer in DEMO, disclose she's an AI, ask who's calling, relay to the operator |
| **take-message** | auto-answer in DEMO, disclose, take a message, don't interrupt the operator |
| **block** | decline / don't ring |

On `IncomingCall`, look up `caller_number` in **Iris's roster** and apply that entry's rule. **Not on the roster (truly unknown) → screen in DEMO** (telemarketer-safe; ADR-0002).

Iris can **import (download) the phone's contacts** to seed the roster and keep it easy to manage, but **Iris's list is authoritative** — the operator curates it through her, and it can deliberately diverge from the phone (screen a number that's in the address book; VIP someone who isn't).

Crucially, an entry is **more than a routing rule** — it carries a **per-contact relationship profile** that changes *how Iris behaves* with and about that caller (examples illustrative):

- **tone** — warm and casual with a best friend; crisp and professional with the doctor's office;
- **default skills / intent** — the doctor's office → capture appointment details to the calendar; a friend → take a relaxed message;
- **trust posture** — a trusted entry may pre-arm a scoped capability for its own purpose, while strangers stay DEMO (ADR-0002).

This builds on the brain's existing per-caller preferences hook (`prefs.hint(call_context)`). It's the thesis in miniature: **Iris doesn't treat everyone the same, because a secretary doesn't** — your best friend and your doctor's office get genuinely different handling.

**Design stance — keep it light (operator, 2026-06-16):** the schema above is a deliberately minimal *start* — likely just identity + a freeform relationship/notes field + a coarse handling rule. We expect the **LLM to do the heavy lifting** of "act differently" from that context, rather than enumerating rigid behavior dimensions up front. Add structure only when direct user feedback shows a real gap.

**Dependency:** **Iris's contact roster** — a local, operator-curated store, `identity → {name, handling rule, relationship profile (tone / default skills / trust posture), notes}`, held warm by the daemon and seedable by importing phone contacts. Until it exists, fall back to **announce-only** (no auto-answer). The roster is a cross-cutting entity (calls, SMS, memory, and scheduling all key off it) and warrants its own design — see Consequences.

## Consequences / follow-ups

- **Build:** the resident daemon (own the warm pipeline + listeners; console becomes a client); generalize the listener to Messages + notifications; **Iris's contact roster**; the **pre-rendered disclosure WAV**; the dispatcher + priority model.
- **Iris's contact roster is its own design surface** — it's the organizing entity for the whole comms thesis (call policy here, plus SMS triage, memory, scheduling, and per-contact tone/trust). It should get its own ADR/design (candidate **ADR-0005**), ideally routed to the architect/designer like the memory layer (ADR-0003); it ties into the brain's per-caller `prefs`.
- **Known bug:** `iris/call_control.py` `_on_incoming(call_id)` mismatches tincan's `IncomingCall(caller_name, caller_number)` — fix the signature and thread `caller_number` into the contacts lookup. Tracked: **ti-389**.
- **Text/notification handling** (triage + surfacing) is detailed under the SMS-lane work, not here.
- **Resource note:** steady-state warm STT/TTS/LLM is a deliberate trade (resources for latency); revisit if the always-on footprint becomes a problem on the target box.

## References

ADR-0001, ADR-0002, ADR-0003 (bead `ti-wc2`), ARCHITECTURE.md §6 (tincan integration contract). Decided with the operator 2026-06-16.
