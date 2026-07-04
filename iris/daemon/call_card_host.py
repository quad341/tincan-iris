"""CallCardHost — top-level call-card lifecycle controller (ti-rnlqo.3.3+5.4)."""
from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import asdict

from iris.capture.processor import L1CaptureProcessor
from iris.capture.schemas import ActionItem, CapturedFact
from iris.capture.session import CaptureSession
from iris.capture.store import CallCardStore
from iris.capture.transcript import TranscriptStore

_log = logging.getLogger(__name__)

_DEFAULT_DISCLOSURE = (
    "I'm going to put you on speaker — I have an AI assistant that takes notes"
    " so I don't miss anything."
)


class CallCardHost:
    """Owns a CaptureSession for the duration of a call; broadcasts all call_card_* events.

    Wired by the daemon entry point into HandlingEngine (on_call_connected/on_call_ended)
    and DaemonAPI (confirm_fact, confirm_action_item, disclosure_ack, disclosure_skip,
    get_call_card).
    """

    def __init__(
        self,
        *,
        store: CallCardStore,
        processor: L1CaptureProcessor,
        api: object,      # DaemonAPI — typed as object to avoid circular import
        cfg: object,      # iris config; host reads cfg.call_card_disclosure_script
    ) -> None:
        self._store = store
        self._processor = processor
        self._api = api
        self._cfg = cfg
        self._lock = threading.Lock()
        self._session: CaptureSession | None = None
        self._session_id: str | None = None
        self._caller_number: str = ""
        self._fact_count: int = 0
        self._action_item_count: int = 0
        self._session_transcript: TranscriptStore | None = None

    @property
    def _disclosure_script(self) -> str:
        try:
            return self._cfg.call_card_disclosure_script or _DEFAULT_DISCLOSURE  # type: ignore[union-attr]
        except AttributeError:
            return _DEFAULT_DISCLOSURE

    # ── Session lifecycle ─────────────────────────────────────────────────────

    def start_session(self, session_id: str, caller_number: str) -> None:
        # tincand's CallConnected signal carries no call id yet (client-contract
        # gap, tincan-xbtct), so outbound calls arrive here with session_id="".
        # An empty id broke the whole DURING flow: broadcasts carried "", and the
        # API rejects disclosure_ack without a session_id, so the far channel
        # could never start (found live, 2026-07-04). Mint one instead.
        if not session_id:
            session_id = f"call-{uuid.uuid4().hex[:8]}"
            _log.info("CallCardHost.start_session: no call id from tincand — minted %s", session_id)
        with self._lock:
            if self._session is not None:
                _log.warning(
                    "CallCardHost.start_session: session %s already active, ignoring %s",
                    self._session_id, session_id,
                )
                return
            self._session_id = session_id
            self._caller_number = caller_number
            self._fact_count = 0
            self._action_item_count = 0
            transcript_store = TranscriptStore()
            self._session_transcript = transcript_store
            self._store.load_or_create(session_id, caller_number)
            session = CaptureSession(
                session_id=session_id,
                transcript_store=transcript_store,
                processor=self._processor,
                store=self._store,
                on_fact=self._on_fact,
                on_action_item=self._on_action_item,
            )
            self._session = session

        # Start audio threads and broadcast outside the lock. Operator channel only —
        # far-party capture is hard-gated on disclosure_ack (ti-ir12t/ti-rqhn precedent).
        session.start_operator()
        self._api.broadcast({"event": "call_card_started", "session_id": session_id,  # type: ignore[union-attr]
                              "caller_number": caller_number, "contact_name": ""})
        self._api.broadcast({"event": "call_card_disclosure_needed", "session_id": session_id,  # type: ignore[union-attr]
                              "script": self._disclosure_script})

    def stop_session(self, session_id: str) -> None:
        with self._lock:
            # Empty id = "the active session" — CallEnded carries no id either.
            if not session_id:
                session_id = self._session_id or ""
            if self._session is None or self._session_id != session_id:
                _log.warning(
                    "CallCardHost.stop_session: no active session matching %s", session_id
                )
                return
            session = self._session
            transcript_store = self._session_transcript
            fact_count = self._fact_count
            action_item_count = self._action_item_count
            self._session = None
            self._session_id = None
            self._session_transcript = None

        session.stop()
        self._store.mark_ended(session_id)
        self._api.broadcast({  # type: ignore[union-attr]
            "event": "call_card_ended",
            "session_id": session_id,
            "fact_count": fact_count,
            "action_item_count": action_item_count,
        })
        # L3 post-call enrichment is OPTIONAL (needs the `call-card` extra:
        # instructor + pydantic + anthropic). L1 capture works without it — if the
        # extra is absent, log loudly and skip (never a silent no-op).
        try:
            from iris.capture.enricher import PostCallEnricher  # noqa: PLC0415
        except ImportError as exc:
            _log.warning(
                "Post-call enrichment skipped — call-card LLM extra not installed "
                "(%s); run `pip install -e '.[call-card]'` for the L3 pass.", exc,
            )
            return
        enricher = PostCallEnricher(
            session_id=session_id,
            store=self._store,
            transcript_store=transcript_store,
            api=self._api,
            cfg=self._cfg,
        )
        enricher.start()
        # enricher is daemon=True; reference released so GC can collect when it finishes

    # ── Fact / action-item callbacks (called from audio threads) ─────────────

    def _on_fact(self, fact: CapturedFact) -> None:
        with self._lock:
            self._fact_count += 1
        self._api.broadcast({  # type: ignore[union-attr]
            "event": "call_card_fact",
            "session_id": fact.session_id,
            "fact": asdict(fact),
        })

    def _on_action_item(self, item: ActionItem) -> None:
        with self._lock:
            self._action_item_count += 1
        self._api.broadcast({  # type: ignore[union-attr]
            "event": "call_card_action_item",
            "session_id": item.session_id,
            "item": asdict(item),
        })

    # ── DaemonAPI command handlers ────────────────────────────────────────────

    def confirm_fact(
        self,
        session_id: str,
        fact_id: str,
        confirmed: bool,
        normalized_value: str | None,
    ) -> None:
        self._store.confirm_fact(fact_id, confirmed, normalized_value)

    def confirm_action_item(
        self,
        session_id: str,
        item_id: str,
        confirmed: bool,
        description: str | None,
        due_date: str | None,
    ) -> None:
        self._store.confirm_action_item(item_id, confirmed, description, due_date)

    def disclosure_ack(self, session_id: str) -> None:
        with self._lock:
            # Empty id = "the active session" (see start_session id minting).
            if not session_id:
                session_id = self._session_id or ""
        self._store.mark_disclosure_ack(session_id)
        with self._lock:
            session = self._session
            active_id = self._session_id
        if session is None or active_id != session_id:
            _log.warning(
                "CallCardHost.disclosure_ack: no active session matching %s", session_id
            )
            return
        session.start_far()
        # Re-validate identity after start_far()'s own (possibly slow) D-Bus/PipeWire
        # I/O: stop_session() runs on a different thread and could have torn this
        # session down while start_far() was in flight. Corrective, not preventive —
        # closing the lock across start_far() would block stop_session() unnecessarily.
        with self._lock:
            superseded = self._session is not session
        if superseded:
            _log.warning(
                "CallCardHost.disclosure_ack: session %s torn down while starting "
                "far capture — stopping orphaned CaptureSession", session_id,
            )
            session.stop()

    def disclosure_skip(self, session_id: str) -> None:
        # Operator explicitly declined — never call start_far(); far channel stays
        # off for the rest of this call (ti-ir12t hard-gate).
        with self._lock:
            if not session_id:  # empty id = the active session (see start_session)
                session_id = self._session_id or ""
        self._store.mark_disclosure_skipped(session_id)

    def get_call_card(self, session_id: str | None = None) -> dict:
        with self._lock:
            sid = session_id or self._session_id or ""
        return self._store.get_call_card(sid) if sid else {}
