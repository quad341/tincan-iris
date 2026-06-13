"""Tier-2 driver — a persistent, lean Claude Code session driving cloud Haiku
as raw TEXT (no tools, no MCP; see ``docs/adr/0001``).

Approach (validated): keep one ``claude`` process alive in a tmux session,
inject prompts with ``tmux send-keys``, and scrape the answer from the pane.
Startup is paid once; warm turns return in ~1-3 s (latency scales with answer
length, so the system prompt forces brevity). This is deliberately the *only*
place that touches the cloud frontier model — and it does so through the
vendor's own TUI, never a raw API.

Caveat: this screen-scrapes a redrawing terminal UI. The fragility is contained
here so the rest of the brain sees a clean ``ask(text) -> str``.
"""
from __future__ import annotations

import subprocess
import time

_CHROME = "❯✻✶─╭╰│"  # pane glyphs that mark UI chrome, not answer text


def _extract_answer(pane: str) -> str:
    """Pull the latest assistant answer (the last ``●`` block) out of the pane."""
    lines = pane.splitlines()
    bullets = [i for i, line in enumerate(lines) if line.lstrip().startswith("●")]
    if not bullets:
        return ""
    out = [lines[bullets[-1]].lstrip()[1:].strip()]
    for line in lines[bullets[-1] + 1:]:
        s = line.strip()
        if not s or s[0] in _CHROME:
            break
        out.append(s)
    return " ".join(out).strip()


class ClaudeTuiSession:
    """A warm, persistent lean Claude Code session (cloud Haiku, text-only)."""

    def __init__(
        self,
        model: str = "claude-haiku-4-5",
        system_prompt: str = "Reply in one short sentence.",
        session: str = "iris-haiku",
        cwd: str = "/tmp",
        ready_timeout_s: float = 40.0,
    ) -> None:
        self.model = model
        self.system_prompt = system_prompt
        self.session = session
        self.cwd = cwd
        self.ready_timeout_s = ready_timeout_s
        self._started = False

    def _tmux(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["tmux", *args], capture_output=True, text=True)

    def _pane(self) -> str:
        return self._tmux("capture-pane", "-p", "-t", self.session).stdout

    def start(self) -> float:
        """Launch the session and block until the TUI is ready. Returns seconds."""
        self._tmux("kill-session", "-t", self.session)  # clear any stale session
        # Validated lean config: a tool-less system prompt makes Haiku text-only
        # in practice. (Hardening TODO: also pass --strict-mcp-config /
        # --disallowedTools to *guarantee* no tool or MCP can ever fire.)
        self._tmux(
            "new-session", "-d", "-s", self.session, "-c", self.cwd, "-x", "200", "-y", "50",
            "claude", "--model", self.model, "--dangerously-skip-permissions",
            "--system-prompt", self.system_prompt,
        )
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < self.ready_timeout_s:
            pane = self._pane()
            if "haiku" in pane.lower() and "❯" in pane:
                self._started = True
                return time.perf_counter() - t0
            time.sleep(0.3)
        self.close()
        raise RuntimeError("Claude TUI did not become ready in time")

    def ask(self, prompt: str, idle_s: float = 1.0, timeout_s: float = 60.0) -> str:
        """Send a prompt to the warm session and return Haiku's answer text."""
        if not self._started:
            self.start()
        self._tmux("send-keys", "-t", self.session, prompt)
        time.sleep(0.15)
        self._tmux("send-keys", "-t", self.session, "Enter")
        t0 = time.perf_counter()
        last, last_change, saw = self._pane(), time.perf_counter(), False
        while time.perf_counter() - t0 < timeout_s:
            time.sleep(0.2)
            pane = self._pane()
            now = time.perf_counter()
            if pane != last:
                last, last_change, saw = pane, now, True
            if saw and now - last_change > idle_s:
                return _extract_answer(pane)
        return _extract_answer(self._pane())  # timed out — best effort

    def close(self) -> None:
        self._tmux("kill-session", "-t", self.session)
        self._started = False

    def __enter__(self) -> "ClaudeTuiSession":
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
