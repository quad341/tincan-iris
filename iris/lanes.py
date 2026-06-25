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
from .scope import ScopeManifest
from .skills import SkillRegistry


@dataclass
class SkillProposal:
    """A skill the model proposed (name + filtered args), NOT yet executed.

    The qwen lane returns this; the daemon (Brain) authorizes it and only then
    runs it — ADR-0005 §4: the model proposes, the daemon authorizes + executes.
    """
    skill: str
    args: dict


@dataclass
class LaneResult:
    text: str
    lane: str
    skill: str | None = None
    speaker: str = ""  # "operator" | "far" | "" — who spoke; propagated from the call site
    proposal: "SkillProposal | None" = None  # set when the lane proposed a skill to run


def _reply_text(result: object) -> str:
    """Collapse a skill's return value to the single spoken/displayed string.

    Most skills return a ``str``. The calendar skills (act-without-disclose)
    return a ``(spoken_reply, console_annotation)`` tuple; the lane and console
    speak ``LaneResult.text``, so we keep the spoken half and drop the
    console-only annotation (a dedicated annotation channel is future work —
    dropping it here is strictly better than speaking it).
    """
    if isinstance(result, tuple):
        return str(result[0]) if result else ""
    return result if isinstance(result, str) else str(result)


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
        domains = ScopeManifest.what_i_do()
        lines = ["Here's what I can help with:"]
        for domain, items in domains.items():
            lines.append(f"  {domain}: {'; '.join(items)}")
        return "\n".join(lines)

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
    """Local Qwen via llama-server. Warm and fast — the workhorse / orchestrator.

    When a ``SkillRegistry`` is provided and ``allow_skills=True``, the handler
    runs a grammar-constrained dispatch pass first. The grammar forces Qwen to
    emit ``{"skill":"<name>","args":{...}}``; if it chooses ``"none"`` the call
    falls through to a regular chat completion. Skills are only dispatched in
    FULL-trust turns — the brain passes ``allow_skills=False`` for far+DEMO.
    """

    name = "tier1-qwen"

    def __init__(self, cfg: Config, skills: SkillRegistry | None = None) -> None:
        self.cfg = cfg
        self.skills = skills
        # Grammar is cached per speaker scope — the operator and the far party
        # are offered different skill sets, so they need different grammars.
        self._grammar_cache: dict[str, str] = {}

    def _complete(self, prompt: str, n_predict: int, *, grammar: str | None = None) -> str:
        payload: dict = {
            "prompt": prompt, "n_predict": n_predict,
            "stream": False, "cache_prompt": True,
        }
        if grammar:
            payload["grammar"] = grammar
        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            self.cfg.qwen_base_url + "/completion",
            body,
            {"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.cfg.qwen_timeout_s) as resp:
            return json.loads(resp.read()).get("content", "").strip()

    def _build_grammar(self, speaker: str = "") -> str:
        """Generate a GBNF grammar that constrains Qwen to emit a dispatch JSON.

        Output shape: ``{"skill":"<name>","args":{...}}``. Skill name is one of
        the registered names or ``"none"`` (fall through to chat). The args
        object holds zero or more string-valued key/value pairs, so a skill that
        needs several arguments (e.g. calendar free/busy's ``start`` + ``end``)
        can be filled in one shot. Which keys to use is taught in the dispatch
        prompt; the daemon drops unknown keys and degrades on missing ones.

        ``speaker`` scopes the offered names so operator_only skills are never
        even nameable by the far party.
        """
        names = list(self.skills.names(speaker)) if self.skills else []
        skill_choices = " | ".join(f'"{n}"' for n in names) or '"none"'
        return "\n".join([
            'root         ::= "{" ws "\\"skill\\"" ws ":" ws "\\"" skill-choice "\\"" ws "," ws "\\"args\\"" ws ":" ws args-obj ws "}"',
            f'skill-choice ::= "none" | {skill_choices}',
            'args-obj     ::= "{" ws ( str-kv ( ws "," ws str-kv )* )? ws "}"',
            'str-kv       ::= "\\"" key "\\"" ws ":" ws "\\"" str-val "\\""',
            'key          ::= [a-z_]+',
            'str-val      ::= [^"\\\\\\n]*',
            'ws           ::= [ \\t\\n]*',
        ])

    def _dispatch_prompt(self, text: str, speaker: str = "") -> str:
        skills = self.skills
        lines = []
        for e in (skills.manifest(speaker) if skills else []):
            params = e.get("params") or []
            if params:
                arg_desc = ", ".join(
                    f'{p["name"]}{"" if p["required"] else "?"} ({p["description"]})'
                    for p in params
                )
                lines.append(f'"{e["name"]}" — {e["description"]} args: {arg_desc}')
            else:
                lines.append(f'"{e["name"]}" — {e["description"]} (no args)')
        skill_list = "; ".join(lines)
        now = _dt.datetime.now().strftime("%A %Y-%m-%dT%H:%M")
        # Few-shot examples teaching action-vs-conversation distinction.
        # Chitchat and open-ended Q&A → none; explicit action requests → skill.
        examples = (
            '<|im_start|>user\nhow are you doing today?<|im_end|>\n'
            '<|im_start|>assistant\n{"skill":"none","args":{}}<|im_end|>\n'
            '<|im_start|>user\ntell me a fun fact about otters<|im_end|>\n'
            '<|im_start|>assistant\n{"skill":"none","args":{}}<|im_end|>\n'
            '<|im_start|>user\nwhat do you think about jazz<|im_end|>\n'
            '<|im_start|>assistant\n{"skill":"none","args":{}}<|im_end|>\n'
            '<|im_start|>user\ndo you like dogs<|im_end|>\n'
            '<|im_start|>assistant\n{"skill":"none","args":{}}<|im_end|>\n'
        )
        return (
            '<|im_start|>system\nYou are Iris. Use a skill ONLY when the user requests '
            'an action you can perform with the listed skills. For conversation, opinions, '
            'or questions you can answer directly, output {"skill":"none","args":{}} and '
            'reply in natural language.\n'
            f'Right now it is {now} (local time); give any datetime arg as ISO 8601. '
            'Fill every required arg the chosen skill needs.\n'
            f'Available skills: {skill_list}<|im_end|>\n'
            f'{examples}'
            f'<|im_start|>user\n{text}<|im_end|>\n<|im_start|>assistant\n'
        )

    def _chat_prompt(self, text: str, context_hint: str = "") -> str:
        pref_line = f" Caller prefs — {context_hint}." if context_hint else ""
        return (
            f"<|im_start|>system\nYou are Iris, a warm, concise voice assistant.{pref_line} "
            "Reply in one or two short sentences.<|im_end|>\n"
            f"<|im_start|>user\n{text}<|im_end|>\n<|im_start|>assistant\n"
        )

    def handle(
        self,
        text: str,
        *,
        allow_skills: bool = True,
        context_hint: str = "",
        speaker: str = "",
    ) -> LaneResult:
        """Run the dispatch pass and, on a skill hit, return an *unexecuted*
        ``SkillProposal`` — the daemon (Brain) authorizes and runs it. On
        ``"none"`` (or no registry / DEMO) fall through to a chat completion.
        """
        if allow_skills and self.skills and self.skills.names(speaker):
            if self.skills.grammar_dirty:
                self._grammar_cache.clear()
                self.skills.grammar_dirty = False
            grammar = self._grammar_cache.get(speaker)
            if grammar is None:
                grammar = self._build_grammar(speaker)
                self._grammar_cache[speaker] = grammar
            raw = self._complete(self._dispatch_prompt(text, speaker), 96, grammar=grammar)
            try:
                dispatch = json.loads(raw)
                skill_name = dispatch.get("skill", "none")
                args = dispatch.get("args") or {}
            except (ValueError, AttributeError):
                skill_name = "none"
                args = {}
            if skill_name != "none":
                skill = self.skills.get(skill_name)
                if skill is not None:
                    known = {p.name for p in getattr(skill, "params", [])}
                    call_args = (
                        {k: v for k, v in args.items() if k in known}
                        if isinstance(args, dict) else {}
                    )
                    # Skills that declare a ``speaker`` param get the real channel
                    # so their own checks see who's calling on the dispatch path.
                    if "speaker" in known:
                        call_args["speaker"] = speaker or "operator"
                    # Propose — do NOT execute. The daemon authorizes, then runs.
                    return LaneResult(
                        "", self.name, skill=skill_name, speaker=speaker,
                        proposal=SkillProposal(skill_name, call_args),
                    )
        # no skill selected, DEMO mode, or no registry — regular chat completion
        return LaneResult(
            self._complete(self._chat_prompt(text, context_hint), self.cfg.qwen_max_tokens), self.name
        )


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
