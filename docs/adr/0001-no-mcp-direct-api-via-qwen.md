# ADR-0001 — No MCP at runtime: direct-API skills orchestrated by a warm local model

- **Status:** accepted (2026-06-13)
- **Context doc:** [docs/LATENCY.md](../LATENCY.md)

## Context

Iris must feel responsive. We measured the brain tiers on the target box
(an AMD "Strix Halo" APU; local models on the iGPU via llama.cpp):

- **Local Qwen (llama.cpp):** ~16 ms time-to-first-token (warm), ~64 tok/s — fast.
- **Cloud Haiku via the Claude Code TUI:** ~1–2 s as *raw text* in a lean
  config, but ~3 s+ as a full agent — and **each MCP tool call adds another
  round-trip on top of that.** MCP-through-the-cloud-agent is the slowest path
  we have.

Two further forces:

- **Security.** Public MCP skill marketplaces have a poor track record — the
  2026 OpenClaw / ClawHub incident saw ~12% of marketplace skills turn out to
  be malware, and a one-click RCE that exfiltrated agent auth tokens. Iris
  ingests untrusted inbound content (SMS, app notifications, caller audio), so a
  large third-party tool surface is a real, not theoretical, risk.
- **House rule.** Online frontier models are only ever driven through the
  vendor's own TUI (as the rest of our toolchain does), never a raw API.

## Decision

1. **The cloud frontier model (Haiku) never touches a tool or an MCP server.**
   It is a *raw text / knowledge* lane only, driven through the Claude Code TUI
   in a lean, tool-less, MCP-less configuration.
2. **Actions are self-authored direct-API adapters** ("skills") — calendar via
   the Google Calendar REST API, email via IMAP/SMTP, messaging & call control
   via tincan's D-Bus interface, and so on. **No MCP servers at runtime.**
3. **The warm local model (Qwen) orchestrates the skills** — it does the NLU,
   selects a skill, and calls it. Kept warm so dispatch stays sub-second.

## Consequences

- ➕ Removes the slowest lane (cloud agent + per-hop MCP round-trips).
- ➕ Eliminates the MCP / marketplace supply-chain and token-exfiltration surface.
- ➕ Credentials (OAuth, etc.) stay local to our own adapters and are never
  exposed to the cloud model. They load at runtime and are never committed.
- ➕ Clean separation of concerns: the cloud model **thinks**, local code **does**.
- ➖ We implement and maintain each integration ourselves — the cost of giving
  up drop-in MCP reusability. Accepted for the speed + security it buys.
- ➖ Local function-calling reliability (Qwen) must be validated per skill.
