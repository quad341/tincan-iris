"""PostCallEnricher — L3 post-call LLM extraction pass (ti-rnlqo.5.2,
ti-pkt2r.1).

Runs as a daemon thread spawned by CallCardHost after call_ended. Driven
through the daemon's warm CallCardCloudSession (a vendor Claude Code TUI
session, never a raw API key — see docs/adr/0001) to find entities the L1
pipeline missed, upserts results into CallCardStore, then broadcasts
call_card_enriched.

Per FR6 (ti-pkt2r trust-gate policy), the transcript sent to the model
includes operator-speaker turns plus any far-speaker turn stamped with full
(BOTH) trust at capture time — turns captured before the operator granted
full trust stay withheld even if the call is later elevated (ti-pkt2r.2).
"""
from __future__ import annotations

import logging
import threading

from pydantic import BaseModel

from iris.capture._llm_common import ask_structured
from iris.capture.schemas import CapturedFact, FactType
from iris.capture.store import CallCardStore
from iris.capture.transcript import TranscriptStore
from iris.trust import TrustMode

_log = logging.getLogger(__name__)

_SHAPE = (
    '{"new_facts": [{"fact_type": "...", "raw_text": "...", '
    '"normalized_value": "...", "transcript_turn_id": 0, "confidence": 0.0}], '
    '"enriched_items": [{"description": "...", "owner": "...", '
    '"due_date": null, "transcript_turn_id": 0, "confidence": 0.0}]}'
)


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class FactExtract(BaseModel):
    fact_type: str          # phone|case_id|amount|date|name|address|email
    raw_text: str
    normalized_value: str   # E.164 for phone, ISO date for date, etc.
    transcript_turn_id: int
    confidence: float       # 0.0–1.0


class ActionItemExtract(BaseModel):
    description: str
    owner: str              # 'operator' | 'far' | 'unknown'
    due_date: str | None    # ISO date or null
    transcript_turn_id: int
    confidence: float


class EnrichmentSchema(BaseModel):
    new_facts: list[FactExtract]           # entities NOT already in confirmed_entities
    enriched_items: list[ActionItemExtract] # action items with clarified desc/dates


def _build_prompt(confirmed_entities_block: str, transcript_block: str) -> str:
    return (
        f"Confirmed entities (do not re-extract):\n{confirmed_entities_block}"
        f"\n\nOperator-side transcript:\n{transcript_block}"
        "\n\nFind: (1) entity types spoken but NOT in the confirmed list; "
        "(2) action items needing clearer descriptions or due dates.\n\n"
        f"Reply with exactly this JSON shape, one line, no other text:\n{_SHAPE}"
    )


def _retry_prompt() -> str:
    return (
        "That reply was not valid JSON matching the required shape. Reply "
        f"again with ONLY the JSON, one line, matching exactly:\n{_SHAPE}"
    )


# ── Thread ────────────────────────────────────────────────────────────────────

class PostCallEnricher(threading.Thread):
    """Daemon thread for post-call LLM extraction. Spawned once per call."""

    def __init__(
        self,
        *,
        session_id: str,
        store: CallCardStore,
        transcript_store: TranscriptStore,
        api: object,    # DaemonAPI
        cfg: object,
        cloud: object,  # CallCardCloudSession | None
    ) -> None:
        super().__init__(daemon=True, name=f"enricher-{session_id[:8]}")
        self._session_id = session_id
        self._store = store
        self._transcript_store = transcript_store
        self._api = api
        self._cfg = cfg
        self._cloud = cloud

    def run(self) -> None:
        session_id = self._session_id
        if self._cloud is None:
            _log.warning("PostCallEnricher: no cloud session configured, skipping")
            return
        if self._transcript_store.is_empty():
            _log.debug("PostCallEnricher: empty transcript, skipping")
            return

        try:
            turns = self._transcript_store.get_turns()
            card = self._store.get_call_card(session_id)
            facts = card.get("facts", [])

            confirmed_entities_block = "\n".join(
                f"{f['fact_type']}: {f['normalized_value']}"
                for f in facts
                if f.get("normalized_value")
            ) or "(none)"

            # FR6 trust-gate policy — see module docstring.
            eligible_turns = [
                t for t in turns
                if t.speaker == "operator" or t.trust is TrustMode.BOTH
            ]
            transcript_block = "\n".join(
                f"{t.speaker}: {t.text}" for t in eligible_turns
            )

            prompt = _build_prompt(confirmed_entities_block, transcript_block)
            result = ask_structured(self._cloud, prompt, _retry_prompt(), EnrichmentSchema)
            if result is None:
                self._store.mark_enrichment_done(session_id, status=2)
                _log.warning(
                    "PostCallEnricher: no valid response for %s", session_id
                )
                return
            self._apply_result(session_id, result)

        except Exception as exc:
            self._store.mark_enrichment_done(session_id, status=2)
            _log.warning(
                "PostCallEnricher: enrichment failed for %s: %s", session_id, exc
            )

    def _apply_result(self, session_id: str, result: EnrichmentSchema) -> None:

        for fe in result.new_facts:
            try:
                fact_type = FactType(fe.fact_type)
            except ValueError:
                fact_type = FactType.NAME

            fact = CapturedFact(
                session_id=session_id,
                fact_type=fact_type,
                raw_text=fe.raw_text,
                normalized_value=fe.normalized_value,
                transcript_turn_id=fe.transcript_turn_id,
                transcript_offset_s=0.0,
                speaker="",
                confidence=fe.confidence,
                critical=False,
                source_layer=3,
            )
            self._store.add_fact(fact)

        for ai in result.enriched_items:
            self._store.upsert_enriched_action_item(
                session_id=session_id,
                turn_id=ai.transcript_turn_id,
                description=ai.description,
                owner=ai.owner,
                due_date=ai.due_date,
                confidence=ai.confidence,
            )

        self._store.mark_enrichment_done(session_id, status=1)
        self._api.broadcast({  # type: ignore[union-attr]
            "event": "call_card_enriched",
            "session_id": session_id,
        })
