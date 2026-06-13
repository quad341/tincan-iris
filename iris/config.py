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
    # (Claude Code), in a lean, tool-less, MCP-less config. See docs/adr/0001.
    haiku_model: str = "claude-haiku-4-5"
    haiku_enabled: bool = False  # off until the TUI driver lands (next PR)


DEFAULT = Config()
