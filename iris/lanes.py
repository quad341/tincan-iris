"""Lanes — the tiered brain. The cheapest viable lane wins.

Measured budget (target box, 2026-06-13; see ``docs/LATENCY.md``):

    Tier 0  hard rules        <1 ms     known actions (deterministic, LOCAL)
    Tier 1  local Qwen        ~16 ms TTFT / ~64 tok/s   NLU, dispatch, replies
    Tier 2  raw Haiku (TUI)   ~1-2 s    frontier text/knowledge — NO tools/MCP
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from .config import Config
from .skills import SkillRegistry


@dataclass
class LaneResult:
    text: str
    lane: str
    skill: str | None = None
    speaker: str = ""  # "operator" | "far" | "" — who spoke; propagated from the call site


_INTRO = (
    "Hi, I'm Iris — a voice assistant, and I'll always tell you I'm an AI. I ride "
    "along on tincan to help with calls and messages, and I keep things local and "
    "quick whenever I can."
)


class Tier0Rules:
    """Deterministic, LOCAL commands — sub-millisecond, no model, no network.

    The command table is the source of truth: it drives matching, the spoken
    help list, and the discoverability banner. "stop" is first and highest
    priority — the local "stand down" handle that must work even offline.
    """

    name = "tier0-rules"

    def __init__(self, skills: SkillRegistry) -> None:
        self.skills = skills
        # (name, pattern, handler() -> str, example for help/banner)
        self._commands: list[tuple[str, re.Pattern[str], Callable[[], str], str]] = [
            ("stop", re.compile(
                r"^\s*(?:iris[,\s]+)?(?:stop|stand[ -]?down|cancel|never ?mind|abort|"
                r"that'?s enough|quiet|shush)\b", re.I),
             lambda: "Okay — standing down.", "iris, stop"),
            ("time", re.compile(r"\bwhat(?:'s| is)? the time\b|\bwhat time is it\b", re.I),
             self._time, "what time is it"),
            ("date", re.compile(r"\bwhat(?:'s| is)?(?: the| today'?s)? date\b|\bwhat day is it\b", re.I),
             self._date, "what's the date"),
            ("introduce", re.compile(
                r"\bintroduce yourself\b|\bwho are you\b|\bwhat are you\b|\btell me about yourself\b", re.I),
             lambda: _INTRO, "introduce yourself"),
            ("greet", re.compile(r"^\s*(?:hi|hello|hey|good morning|good afternoon|good evening)\b", re.I),
             lambda: "Hi — I'm Iris, and I'm an AI. What can I do for you?", "hi / hello"),
            ("thanks", re.compile(r"^\s*(?:thanks|thank you|cheers|appreciate it)\b", re.I),
             lambda: "Anytime!", "thank you"),
            ("bye", re.compile(r"^\s*(?:bye|goodbye|see you|good ?night|talk later)\b", re.I),
             lambda: "Talk soon — bye!", "goodbye"),
            ("help", re.compile(
                r"\bwhat can (?:you do|i (?:ask|say))\b|\b(?:your )?commands\b|\bhelp\b|\bwhat do you do\b", re.I),
             self._help, "what can you do"),
        ]

    def _time(self) -> str:
        skill = self.skills.get("time")
        return skill.run() if skill is not None else "I can't read the clock right now."

    def _date(self) -> str:
        return _dt.datetime.now().strftime("Today is %A, %B %-d.")

    def _help(self) -> str:
        examples = "; ".join(f'"{ex}"' for _n, _p, _h, ex in self._commands if _n != "help")
        return (
            "You can say things like: " + examples
            + ". Ask me anything else and I'll think it through, or say "
            '"ask Haiku about" something to reach the cloud.'
        )

    def handle(self, text: str) -> LaneResult | None:
        for name, pattern, handler, _ex in self._commands:
            if pattern.search(text):
                return LaneResult(handler(), self.name, skill=name)
        return None  # not a known command; let a smarter lane handle it

    def examples(self) -> list[str]:
        return [ex for _n, _p, _h, ex in self._commands]

    def commands(self) -> list[tuple[str, str]]:
        """(name, example) for every known command — drives the console's dump."""
        return [(name, ex) for name, _p, _h, ex in self._commands]


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
