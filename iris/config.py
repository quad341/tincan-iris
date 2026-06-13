"""Configuration — provider slots and endpoints.

NO secrets and NO PII live here. Real credentials (OAuth tokens for calendar /
email, etc.) load from the local environment or a gitignored secrets file at
runtime, used only by our own direct-API skill adapters — never committed, and
never handed to the cloud model (see ``docs/adr/0001``).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    # --- Latency masking. Fire a filler at first_filler_s, repeat every
    # repeat_filler_s; if a lane runs past lane_deadline_s, abandon it and fall
    # back (the box is shared with the city, so the local model can stall).
    first_filler_s: float = 0.6
    repeat_filler_s: float = 2.5
    lane_deadline_s: float = 6.0
    lane_timeout_reply: str = (
        "Sorry — I'm running slow right now. Let me get back to you on that."
    )

    # --- Tier 1: local brain (warm). llama.cpp server, OpenAI/Anthropic-compatible.
    qwen_base_url: str = "http://127.0.0.1:8080"
    qwen_timeout_s: float = 30.0
    qwen_max_tokens: int = 96

    # --- Tier 2: cloud raw-text tier. Driven ONLY through the vendor TUI
    # (Claude Code), lean + text-only, NEVER tools/MCP. See docs/adr/0001.
    haiku_enabled: bool = True
    haiku_model: str = "claude-haiku-4-5"
    haiku_tmux_session: str = "iris-haiku"
    haiku_ready_timeout_s: float = 40.0
    haiku_system_prompt: str = (
        "You are Iris, answering aloud on the user's behalf. Reply in ONE short, "
        "warm, spoken sentence (under ~30 words). No markdown, no lists, no preamble."
    )


DEFAULT = Config()
