"""Lanes — the tiered brain. The cheapest viable lane wins.

Measured budget (target box, 2026-06-13; see ``docs/LATENCY.md``):

    Tier 0  hard rules        <1 ms     known actions (deterministic)
    Tier 1  local Qwen        ~16 ms TTFT / ~64 tok/s   NLU, dispatch, replies
    Tier 2  raw Haiku (TUI)   ~1-2 s    frontier text/knowledge — NO tools/MCP
"""
from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass

from .config import Config
from .skills import SkillRegistry


@dataclass
class LaneResult:
    text: str
    lane: str
    skill: str | None = None


class Tier0Rules:
    """Deterministic keyword/regex intents. Sub-millisecond, no model."""

    name = "tier0-rules"

    def __init__(self, skills: SkillRegistry) -> None:
        self.skills = skills

    def handle(self, text: str) -> LaneResult | None:
        t = text.lower().strip()
        if re.search(r"\bwhat(?:'s| is)? the time\b|\bwhat time is it\b", t):
            skill = self.skills.get("time")
            if skill is not None:
                return LaneResult(skill.run(), self.name, skill="time")
        if t in {"hi", "hello", "hey"}:
            return LaneResult(
                "Hi — I'm Iris, and I'm an AI. What can I do for you?", self.name
            )
        return None  # not a known action; let a smarter lane handle it


class Tier1Qwen:
    """Local Qwen via llama-server. Warm and fast — the workhorse / orchestrator."""

    name = "tier1-qwen"

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    def _complete(self, prompt: str, n_predict: int) -> str:
        body = json.dumps(
            {"prompt": prompt, "n_predict": n_predict, "stream": False, "cache_prompt": True}
        ).encode()
        req = urllib.request.Request(
            self.cfg.qwen_base_url + "/completion",
            body,
            {"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.cfg.qwen_timeout_s) as resp:
            return json.loads(resp.read()).get("content", "").strip()

    def handle(self, text: str) -> LaneResult:
        prompt = (
            "<|im_start|>system\nYou are Iris, a warm, concise voice assistant. "
            "Reply in one or two short sentences.<|im_end|>\n"
            f"<|im_start|>user\n{text}<|im_end|>\n<|im_start|>assistant\n"
        )
        return LaneResult(self._complete(prompt, self.cfg.qwen_max_tokens), self.name)


class Tier2RawHaiku:
    """Cloud Haiku as raw TEXT only — driven through a persistent lean Claude
    Code TUI session, NEVER tools/MCP (``docs/adr/0001``).

    Lazy-started on first use and kept warm so subsequent turns skip the boot.
    """

    name = "tier2-haiku"

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._session = None

    def _ensure(self):
        if self._session is None:
            from .claude_tui import ClaudeTuiSession

            self._session = ClaudeTuiSession(
                model=self.cfg.haiku_model,
                system_prompt=self.cfg.haiku_system_prompt,
                session=self.cfg.haiku_tmux_session,
                ready_timeout_s=self.cfg.haiku_ready_timeout_s,
            )
            self._session.start()
        return self._session

    def handle(self, text: str) -> LaneResult:
        return LaneResult(self._ensure().ask(text), self.name)

    def close(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None
