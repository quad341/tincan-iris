"""CallCardCloudSession — the single warm ClaudeTuiSession shared by Call
Card's post-call L3 passes (enrichment + recap). Owned by CallCardHost for
the daemon's full process lifetime: started lazily on first use, reused
across every call, closed once at shutdown.

Driven ONLY through the vendor Claude Code TUI (see ``iris/claude_tui.py``
and ``docs/adr/0001``) — never a raw Anthropic API key or SDK. The owner's
explicit directive (ti-pkt2r) is that Call Card's cloud LLM passes run
through a warm ``claude`` tmux session under the operator's own account, not
API spend.
"""
from __future__ import annotations

import threading

from iris.claude_tui import ClaudeTuiSession


class CallCardCloudSession:
    """Lock-guarded, lazy-start warm ClaudeTuiSession for Call Card's L3 passes.

    One instance is shared by PostCallEnricher and PostCallRecapGenerator
    across every call the daemon handles. The lock serializes concurrent
    ask() calls — one warm ``claude`` session can't answer two prompts at
    once — for the full duration of each call, including its one retry.
    """

    def __init__(self, cfg: object) -> None:
        self._cfg = cfg
        self._session: ClaudeTuiSession | None = None
        self._lock = threading.Lock()

    def ask(self, prompt: str) -> str:
        """Ask the warm session `prompt`, starting it first if needed.

        Raises whatever ClaudeTuiSession.start() raises if the session never
        becomes ready — callers already wrap their use of this in a broad
        except, so failures surface as a skipped pass, not a crashed thread.
        """
        with self._lock:
            if self._session is None:
                self._session = ClaudeTuiSession(
                    model=getattr(self._cfg, "call_card_llm_model", "claude-haiku-4-5"),
                    system_prompt=getattr(self._cfg, "call_card_llm_system_prompt", ""),
                    session=getattr(self._cfg, "call_card_llm_tmux_session", "iris-callcard-llm"),
                    ready_timeout_s=getattr(self._cfg, "call_card_llm_ready_timeout_s", 40.0),
                )
                self._session.start()
            timeout_s = getattr(self._cfg, "call_card_llm_ask_timeout_s", 120.0)
            return self._session.ask(prompt, timeout_s=timeout_s)

    def close(self) -> None:
        """Kill the warm session, if any. Called once at daemon shutdown."""
        with self._lock:
            if self._session is not None:
                self._session.close()
                self._session = None
