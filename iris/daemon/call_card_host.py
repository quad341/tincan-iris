"""CallCardHost — top-level call-card lifecycle controller (ti-rnlqo.3.3+5.4)."""
from __future__ import annotations

import hashlib
import logging
import shutil
import threading
from dataclasses import asdict
from pathlib import Path

from iris.audio.endpoint import TincanSCOAudio, discover_sco_nodes
from iris.audio.tts import default_tts
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

_DISCLOSURE_WAV_CACHE = Path.home() / ".local" / "share" / "iris" / "call_card_disclosure.wav"


def _cached_disclosure_wav(script: str, tts: object, wav_path: Path = _DISCLOSURE_WAV_CACHE) -> str:
    """Render *script* to a WAV, reusing a cached rendering keyed on its content hash.

    Mirrors iris.disclosure.ensure_disclosure_wav's cache-sidecar shape, but keyed on
    the script text itself (CallCardHost has no operator-name concept) — keeps
    time-to-far-capture off the TTS synthesis cost on repeat calls with an unchanged
    disclosure_script config.
    """
    sidecar = wav_path.with_suffix(".hash")
    digest = hashlib.sha256(script.encode("utf-8")).hexdigest()
    try:
        cached = sidecar.read_text(encoding="utf-8").strip()
    except OSError:
        cached = ""
    if wav_path.exists() and cached == digest:
        return str(wav_path)

    wav_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = tts.synth(script)  # type: ignore[attr-defined]
    # shutil.move (not Path.replace): the tts tempfile is typically under /tmp, which
    # is often a separate filesystem/tmpfs from ~/.local/share, and a plain rename()
    # can't cross devices. move() tries rename() first (atomic, same-device) and only
    # falls back to copy+delete cross-device.
    shutil.move(tmp, str(wav_path))
    sidecar.write_text(digest, encoding="utf-8")
    return str(wav_path)


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
        tts: object | None = None,
    ) -> None:
        self._store = store
        self._processor = processor
        self._api = api
        self._cfg = cfg
        self._tts = tts if tts is not None else default_tts()
        self._lock = threading.Lock()
        self._session: CaptureSession | None = None
        self._session_id: str | None = None
        self._caller_number: str = ""
        self._fact_count: int = 0
        self._action_item_count: int = 0
        self._session_transcript: TranscriptStore | None = None
        self._announce_proc = None

    @property
    def _disclosure_script(self) -> str:
        try:
            return self._cfg.call_card_disclosure_script or _DEFAULT_DISCLOSURE  # type: ignore[union-attr]
        except AttributeError:
            return _DEFAULT_DISCLOSURE

    # ── Session lifecycle ─────────────────────────────────────────────────────

    def start_session(self, session_id: str, caller_number: str) -> None:
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
        self._auto_disclose(session_id)

    def _auto_disclose(self, session_id: str) -> None:
        threading.Thread(
            target=self._run_auto_disclose, args=(session_id,), daemon=True,
        ).start()

    def _run_auto_disclose(self, session_id: str) -> None:
        """Best-effort: synthesize + play the disclosure script on the SCO uplink,
        then hand off to the existing disclosure_ack() flow on confirmed playback.

        Fail-closed like _announce_then_hear_far (ti-rqhn): any failure — no SCO
        sink, TTS/playback error — leaves disclosure_state at 'pending' and the
        manual [D]/[S] keys as the only path forward. Never a timeout-based
        auto-disclose-anyway fallback.
        """
        sink, source = discover_sco_nodes()
        if not sink:
            _log.warning(
                "CallCardHost auto-disclose: no SCO sink found for %s — falling back "
                "to manual [D]/[S] (consent gate fail-closed)", session_id,
            )
            return
        handle = None
        ok = False
        try:
            wav_path = _cached_disclosure_wav(self._disclosure_script, self._tts)
            handle = TincanSCOAudio(sink, source).start_playback(wav_path)
            with self._lock:
                superseded = self._session_id != session_id
                if not superseded:
                    self._announce_proc = handle
            if superseded:
                # Session already superseded before we could register the handle —
                # stop the stray playback outside the lock (stop() can block on the
                # subprocess exiting) rather than leave it running unregistered.
                handle.stop()
                return
            handle.wait()
            ok = True
        except Exception as exc:  # noqa: BLE001 — any failure => fail closed (manual [D]/[S] still works)
            _log.warning("CallCardHost auto-disclose failed for %s: %s", session_id, exc)
        finally:
            with self._lock:
                if handle is not None and self._announce_proc is handle:
                    self._announce_proc = None
        if ok:
            self.disclosure_ack(session_id)

    def stop_session(self, session_id: str) -> None:
        with self._lock:
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
            current = self._store.get_call_card(session_id).get("disclosure_state")
            if current is not None and current != "pending":
                # First transition already won (manual keypress and the automatic
                # TTS path can land within microseconds of each other) — no-op
                # rather than re-triggering start_far() or clobbering a skip.
                _log.debug(
                    "CallCardHost.disclosure_ack: %s already %s, no-op", session_id, current,
                )
                return
            self._store.mark_disclosure_ack(session_id)
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
        self._api.broadcast({"event": "call_card_disclosed", "session_id": session_id})  # type: ignore[union-attr]

    def disclosure_skip(self, session_id: str) -> None:
        # Operator explicitly declined — never call start_far(); far channel stays
        # off for the rest of this call (ti-ir12t hard-gate).
        with self._lock:
            current = self._store.get_call_card(session_id).get("disclosure_state")
            if current is not None and current != "pending":
                _log.debug(
                    "CallCardHost.disclosure_skip: %s already %s, no-op", session_id, current,
                )
                return
            # Persist the skip before touching any in-flight announcement: this is
            # the authoritative fail-closed signal disclosure_ack's own guard reads,
            # so it must land before releasing the lock lets the announce thread's
            # blocked .wait() unblock from the .stop() call below (ti-uk58b AF2/UC4:
            # otherwise a concurrent auto-disclose could read "pending" a moment
            # after being interrupted and call disclosure_ack anyway).
            self._store.mark_disclosure_skipped(session_id)
            proc = self._announce_proc
        if proc is not None:
            proc.stop()
        self._api.broadcast({"event": "call_card_skipped", "session_id": session_id})  # type: ignore[union-attr]

    def get_call_card(self, session_id: str | None = None) -> dict:
        with self._lock:
            sid = session_id or self._session_id or ""
        return self._store.get_call_card(sid) if sid else {}
