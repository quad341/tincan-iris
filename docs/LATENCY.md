# Iris — measured latency budget

Measured 2026-06-13 on the target box (an AMD Ryzen AI MAX+ "Strix Halo" APU
with a Radeon 8060S iGPU; local models run on the iGPU via llama.cpp). Numbers
are warm (prompt cached / session live).

## Lanes — cheapest viable lane wins

| lane | path | latency | role |
|---|---|---|---|
| **0 · hard rules** | local code | **<1 ms** | known actions (deterministic) |
| **1 · local Qwen** | llama-server (`Qwen3-Coder-30B-A3B`, MoE ~3B active) | **~16 ms** TTFT, **~64 tok/s** (~640 ms for a short reply) | NLU, dispatch, short replies, skill orchestration |
| **2 · raw Haiku** | Claude Code TUI, lean (no tools/MCP) | **~1–2 s** | frontier knowledge / language — **text only** |

## Notes

- With streaming, a short reply can start TTS at ~250 ms (first clause), so the
  local lane feels near-instant.
- The **full** Claude Code agent costs ~3 s/turn; stripping the dynamic system
  prompt + tools (`--system-prompt … --exclude-dynamic-system-prompt-sections
  --tools …`) roughly halves it. Tools/MCP stay off Haiku entirely — see
  [ADR-0001](adr/0001-no-mcp-direct-api-via-qwen.md).
- A raw `claude -p` per call costs ~4–6 s (full boot each time) and is **not**
  used; a persistent session is required.
- STT (whisper.cpp) and TTS (Kokoro) are not yet benchmarked — added when the
  voice I/O lands.

## Mitigations (how we defend the budget)

- Push the vast majority of turns to lanes **0/1** (instant–fast).
- Mask the rare cloud-text turn with a beat of local filler ("umm, one sec…").
- Never put a cloud round-trip — or an MCP hop — on the *action* path. Actions
  are local direct-API adapters ([ADR-0001](adr/0001-no-mcp-direct-api-via-qwen.md)).
