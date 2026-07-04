"""HandlingEngine — verb dispatch skeleton (ADR-0006).

Receives IncomingCall signals, resolves verb via PolicyResolver, dispatches to
the appropriate flow path, and broadcasts the incoming_call event to all clients.

Flow spawning is stubbed in this skeleton (ti-gxpt.3 DoD: skeleton only, no flows
wired).  Flow wiring happens in ti-gxpt.5.

AttentionLock: a single-attention gate.  While a call is being handled, a second
IncomingCall is acknowledged with a log line and a standard-priority desktop
notification; no choice-set is pushed to clients.
"""
from __future__ import annotations

import logging
import threading
import uuid
from typing import Callable

from ..notify_sink import DesktopNotifySink
from .policy import PolicyResolver

_log = logging.getLogger(__name__)


class AttentionLock:
    """Guards the single call-handling slot.

    acquire() returns True and records the call_id if the slot is free.
    Returns False (slot occupied) without blocking if already acquired.
    release() must be called when the call ends or fails.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active_call_id: str | None = None

    def acquire(self, call_id: str) -> bool:
        with self._lock:
            if self._active_call_id is not None:
                return False
            self._active_call_id = call_id
            return True

    def release(self, call_id: str) -> None:
        with self._lock:
            if self._active_call_id == call_id:
                self._active_call_id = None

    @property
    def active_call_id(self) -> str | None:
        with self._lock:
            return self._active_call_id

    @property
    def is_busy(self) -> bool:
        with self._lock:
            return self._active_call_id is not None


class HandlingEngine:
    """Routes incoming calls to the correct handling path.

    Dependencies injected at construction — no globals, all testable.

    :param ctrl:         callable-duck-typed call control (has answer/hangup).
    :param tts:          TTS object with synth() for announcements (may be None).
    :param resolver:     PolicyResolver instance.
    :param notify_sink:  DesktopNotifySink for out-of-band desktop alerts.
    :param broadcast:    Callable[[dict], None] — push an event to all clients.
                         Stubbed in tests; wired to DaemonAPI in ti-gxpt.4.
    """

    def __init__(
        self,
        *,
        ctrl: object,
        tts: object | None,
        resolver: PolicyResolver,
        notify_sink: DesktopNotifySink,
        broadcast: Callable[[dict], None],
        call_card_host: object | None = None,
        brain_host: object | None = None,
    ) -> None:
        self._ctrl = ctrl
        self._tts = tts
        self._resolver = resolver
        self._notify = notify_sink
        self._broadcast = broadcast
        self._call_card_host = call_card_host
        self._brain_host = brain_host
        self._pending_contact: object | None = None
        self._attention = AttentionLock()

    # --- public entry points ---

    def on_incoming_call(self, caller_number: str, call_id: str | None = None) -> None:
        """Handle an IncomingCall signal.

        If AttentionLock is held (in-call), logs + notifies at normal priority without
        pushing a choice-set.  Otherwise resolves, acquires the lock, dispatches.
        """
        if call_id is None:
            call_id = str(uuid.uuid4())

        if self._attention.is_busy:
            result = self._resolver.resolve(caller_number, call_id)
            caller_name = result.contact.display_name if result.contact else caller_number
            _log.info(
                "AttentionLock held — second call from %s; ignoring choice-set", caller_name
            )
            self._notify.notify(
                f"Missed call: {caller_name}",
                "",
                urgency="normal",
            )
            return

        result = self._resolver.resolve(caller_number, call_id)
        self._pending_contact = result.contact
        verb = result.verb
        caller_name = result.contact.display_name if result.contact else caller_number

        if verb == "ignore":
            self._dispatch_ignore(call_id)
            return

        if not self._attention.acquire(call_id):
            _log.warning(
                "AttentionLock race: acquired by another call between is_busy check and acquire"
            )
            return

        self._broadcast(result.event)
        self._dispatch_verb(verb, call_id, caller_name, caller_number)

    def on_choose(self, call_id: str, action_id: str) -> None:
        """Process an operator choice from a connected client.

        INVARIANT: NEVER writes contacts.handling_rule.  Choices apply to this call
        only and are ephemeral.
        """
        if self._attention.active_call_id != call_id:
            _log.warning("on_choose: call_id %s not active (active=%s)", call_id, self._attention.active_call_id)
            return
        _log.info("Operator chose %r for call %s", action_id, call_id)
        # Flow dispatch on choices is wired in ti-gxpt.5.

    def on_call_connected(self, call_id: str) -> None:
        """Set brain call context and notify call-card host that the call has been answered."""
        contact = self._pending_contact
        caller_number = (
            getattr(contact, "phone_e164", None) or ""
        ) if contact is not None else ""

        if self._brain_host is not None and contact is not None:
            self._brain_host.set_call_context(  # type: ignore[union-attr]
                contact.id,  # type: ignore[union-attr]
                contact.display_name,  # type: ignore[union-attr]
                caller_number,
            )

        if self._call_card_host is not None:
            contact_id = contact.id if contact is not None else None  # type: ignore[union-attr]
            self._call_card_host.start_session(call_id, caller_number, contact_id)  # type: ignore[union-attr]

    def on_call_ended(self, call_id: str) -> None:
        """Release the attention lock and clear brain call context when a call ends."""
        if self._call_card_host is not None:
            self._call_card_host.stop_session(call_id)  # type: ignore[union-attr]
        self._attention.release(call_id)
        self._pending_contact = None
        if self._brain_host is not None:
            self._brain_host.clear_call_context()  # type: ignore[union-attr]

    # --- private dispatch ---

    def _dispatch_ignore(self, call_id: str) -> None:
        """ignore verb: answer + immediate hangup (no AttentionLock, no event)."""
        _log.info("HandlingEngine: ignoring call %s (answer+hangup)", call_id)
        self._ctrl_answer(call_id)
        self._ctrl_hangup(call_id)

    def _dispatch_verb(
        self,
        verb: str,
        call_id: str,
        caller_name: str,
        caller_number: str,
    ) -> None:
        if verb == "ring_with_announcement":
            self._handle_ring_with_announcement(call_id, caller_name, caller_number)
        elif verb == "ring_through":
            self._handle_ring_through(call_id, caller_name)
        elif verb == "screen":
            self._handle_screen(call_id, caller_name)
        elif verb == "take_message":
            self._handle_take_message(call_id, caller_name)
        else:
            _log.error("HandlingEngine: unknown verb %r for call %s", verb, call_id)
            self._attention.release(call_id)

    def _handle_ring_with_announcement(
        self, call_id: str, caller_name: str, caller_number: str
    ) -> None:
        """ring_with_announcement: TTS announcement + critical desktop notify; NO Answer()."""
        display = caller_name or caller_number
        if self._tts is not None:
            try:
                self._tts.say(f"Call from {display}.")
            except Exception:
                _log.exception("ring_with_announcement: TTS say() failed")
        self._notify.notify(f"📞 {display} calling", "", urgency="critical")

    def _handle_ring_through(self, call_id: str, caller_name: str) -> None:
        """ring_through: desktop notify only; NO Answer()."""
        display = caller_name or call_id
        self._notify.notify(f"📞 {display} calling", "Phone ringing", urgency="normal")

    def _handle_screen(self, call_id: str, caller_name: str) -> None:
        """screen: Answer() + spawn ScreenCallFlow.  Flow wired in ti-gxpt.5."""
        self._ctrl_answer(call_id)
        _log.info("HandlingEngine: screen — ScreenCallFlow stub (ti-gxpt.5)")
        # Flow spawning is wired in ti-gxpt.5.

    def _handle_take_message(self, call_id: str, caller_name: str) -> None:
        """take_message: Answer() + spawn TakeMessageFlow.  Flow wired in ti-gxpt.5."""
        self._ctrl_answer(call_id)
        _log.info("HandlingEngine: take_message — TakeMessageFlow stub (ti-gxpt.5)")
        # Flow spawning is wired in ti-gxpt.5.

    # --- call-control helpers (forward to ctrl object) ---

    def _ctrl_answer(self, call_id: str) -> None:
        try:
            self._ctrl._answer(call_id)  # noqa: SLF001
        except Exception:
            _log.exception("ctrl._answer(%s) failed", call_id)

    def _ctrl_hangup(self, call_id: str) -> None:
        try:
            self._ctrl._hangup(call_id)  # noqa: SLF001
        except Exception:
            _log.exception("ctrl._hangup(%s) failed", call_id)
