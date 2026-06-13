# Iris — what you can say

Iris routes every line to the cheapest lane that can handle it (see
[LATENCY.md](LATENCY.md)). The commands below are **Tier 0** — parsed *locally*
and instantly, with **no model and no network**, so they work even if Qwen,
Haiku, or your connection is down.

## Local commands (Tier 0 — instant, offline)

| Say… | Iris… |
|---|---|
| **"iris, stop"** · "stand down" · "cancel" · "never mind" | halts and stands down |
| "what time is it" | tells the time |
| "what's the date" · "what day is it" | tells the date |
| "introduce yourself" · "who are you" | introduces herself (with AI disclosure) |
| "hi" · "hello" | greets you |
| "thank you" | "Anytime!" |
| "goodbye" · "good night" | signs off |
| **"what can you do"** · "help" | lists these commands |

## Everything else

- A normal question → **local Qwen** (fast, ~sub-second when the box is free).
- **"ask Haiku about X"** → the cloud **raw-text** tier (frontier knowledge; a
  few seconds, with a spoken "umm…" while it thinks).

## Stopping her (two local, can't-fail handles)

1. **Ctrl-C** — the guaranteed stop. It's an OS-level interrupt (SIGINT), so it
   can't be swallowed by a hung model or a dead network, and because the fillers
   play as a foreground process it also cuts the sound mid-playback. Use it to
   kill a runaway "umm…" loop. Iris says *"Okay — stopping."* and returns to idle.
2. **"iris, stop"** / "stand down" — the spoken Tier-0 version (needs STT up).
   Highest-priority local command.

> Full barge-in (interrupting *while* Iris is mid-sentence on a real answer)
> arrives with the live mic; the stop-word parsing and the Ctrl-C handle are
> already local and ready.

When a lane lags, Iris fills the pause with a randomized natural phrase ("let me
think", "hang on", …); if it blows the deadline (~6 s), she falls back gracefully
instead of leaving dead air.
