"""Delegation skills — iris → mayor hand-off (ti-h9di.1, ti-h9di.2).

Two-phase, operator-only, mirroring the dial_skill.py pattern:
  Phase 1 — DelegateSkill.run(): parse utterance, stage pending, return confirm prompt.
             Enforces 200-char body cap; asks operator to rephrase if exceeded.
  Phase 2 — ConfirmDelegateSkill.run(): subprocess gc mail send; one silent retry.
             CancelDelegateSkill.run(): clear staged, return cancel ack.

ADR-0002 compliance: far-party (bluez_input) utterances rejected before dispatch.
ADR-0005 compliance: confirm required before mail is sent — no silent dispatch.
"""
from __future__ import annotations

import hashlib
import subprocess
import threading
from collections.abc import Callable

import iris.settings as _settings

_REPLY_TIMEOUT_S: float = 30.0 * 60.0  # 30 minutes default; patchable in tests
_BODY_LIMIT = 200


def _read_timeout_s() -> float:
    """Read delegation.reply_timeout_minutes from config; return as seconds."""
    minutes = _settings.get_float("IRIS_DELEGATION_REPLY_TIMEOUT_MINUTES", 30.0)
    return minutes * 60.0


class _DelegateState:
    """Mutable holder for a staged pending-confirm and the in-flight FIFO queue."""

    def __init__(self) -> None:
        self._staged_subject: str = ""
        self._staged_body: str = ""
        self._queue: dict[str, tuple[str, str]] = {}
        self._timers: dict[str, threading.Timer] = {}

    # ------------------------------------------------------------------
    # Staged section (pending operator confirm)
    # ------------------------------------------------------------------

    @property
    def has_staged(self) -> bool:
        return bool(self._staged_body)

    def stage(self, subject: str, body: str) -> None:
        self._staged_subject = subject
        self._staged_body = body

    def pop_staged(self) -> tuple[str, str]:
        subject, body = self._staged_subject, self._staged_body
        self.clear_staged()
        return subject, body

    def clear_staged(self) -> None:
        self._staged_subject = ""
        self._staged_body = ""

    # ------------------------------------------------------------------
    # In-flight queue (confirmed, awaiting mayor reply)
    # ------------------------------------------------------------------

    @property
    def queue_count(self) -> int:
        return len(self._queue)

    def enqueue(
        self,
        entry_id: str,
        subject: str,
        body: str,
        on_timeout: Callable[[str], None] | None = None,
    ) -> None:
        self._queue[entry_id] = (subject, body)
        if on_timeout is not None:
            def _fire() -> None:
                self.dequeue(entry_id)
                on_timeout(entry_id)

            timer = threading.Timer(_read_timeout_s(), _fire)
            timer.daemon = True
            timer.start()
            self._timers[entry_id] = timer

    def dequeue(self, entry_id: str) -> None:
        self._queue.pop(entry_id, None)
        timer = self._timers.pop(entry_id, None)
        if timer is not None:
            timer.cancel()

    def status_bar_text(self) -> str:
        n = self.queue_count
        if n == 0:
            return ""
        return f"{n} pending"


class DelegateSkill:
    """Parse operator utterance, stage pending delegation, return confirmation prompt."""

    name = "delegate_to_mayor"
    description = "Ask the mayor to handle something on the operator's behalf. Operator-only."
    operator_only = True

    def __init__(self, state: _DelegateState) -> None:
        self._state = state

    def run(self, utterance: str = "", speaker: str = "operator", **_: object) -> str | None:
        if speaker == "far":
            return None  # ADR-0002: reject far-party utterances
        utterance = utterance.strip()
        if not utterance:
            return "What would you like me to ask the mayor?"
        if len(utterance) > _BODY_LIMIT:
            return "That's a bit long — could you rephrase it more briefly?"
        subject = (
            f"Request from Iris: {utterance[:50]}"
            if len(utterance) > 50
            else f"Request from Iris: {utterance}"
        )
        self._state.stage(subject, utterance)
        excerpt = utterance[:60] + ("..." if len(utterance) > 60 else "")
        return f'I\'ll tell the mayor: "{excerpt}". Shall I send it?'


class ConfirmDelegateSkill:
    """Fire gc mail send after operator confirms; one silent retry on non-zero exit."""

    name = "delegate_confirm"
    description = "Confirm and send the staged mayor delegation."
    operator_only = True

    def __init__(
        self,
        state: _DelegateState,
        gc_bin: str = "gc",
        on_sent: Callable[[str], None] | None = None,
    ) -> None:
        self._state = state
        self._gc_bin = gc_bin
        self._on_sent = on_sent

    def run(self, **_: object) -> str:
        if not self._state.has_staged:
            return "There's nothing to confirm."
        subject, body = self._state.pop_staged()
        cmd = [self._gc_bin, "mail", "send", "mayor", subject, body]
        for attempt in range(2):
            try:
                subprocess.run(cmd, check=True)
                entry_id = f"del-{hashlib.sha256(body.encode()).hexdigest()[:8]}"
                self._state.enqueue(entry_id, subject, body)
                if self._on_sent is not None:
                    self._on_sent(entry_id)
                return "Message sent to the mayor."
            except subprocess.CalledProcessError:
                if attempt == 1:
                    return "I'm sorry, I couldn't reach the mayor."
        return "I'm sorry, I couldn't reach the mayor."


class CancelDelegateSkill:
    """Clear staged delegation without sending."""

    name = "delegate_cancel"
    description = "Cancel the staged mayor delegation without sending."
    operator_only = True

    def __init__(self, state: _DelegateState) -> None:
        self._state = state

    def run(self, **_: object) -> str:
        self._state.clear_staged()
        return "OK, skipping that."


def delegation_skills(
    gc_bin: str = "gc",
    on_sent: Callable[[str], None] | None = None,
) -> list:
    """Operator-only iris→mayor delegation lane — the two-phase skill set.

    The three skills share one ``_DelegateState`` so the stage→confirm handshake
    and the in-flight queue line up. ``on_sent`` (optional) fires with the queue
    entry id after a successful send — the hook ``MayorReplyListener`` uses to
    begin listening for the mayor's async reply. That listener stays dormant
    until the gascity SSE endpoint (ga-ty8cfb) ships, so ``on_sent`` is wired
    only once a reply channel exists.
    """
    state = _DelegateState()
    return [
        DelegateSkill(state),
        ConfirmDelegateSkill(state, gc_bin=gc_bin, on_sent=on_sent),
        CancelDelegateSkill(state),
    ]
