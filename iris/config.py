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
    # Forced brevity keeps it voice-appropriate AND fast — latency scales with
    # answer length, so a one-line spoken answer comes back in ~1-2 s.
    haiku_system_prompt: str = (
        "You are Iris, answering aloud on the user's behalf. Reply in ONE short, "
        "warm, spoken sentence (under ~30 words). No markdown, no lists, no preamble."
    )


DEFAULT = Config()
