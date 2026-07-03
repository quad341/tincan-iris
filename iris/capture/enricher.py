"""PostCallEnricher — L3 post-call LLM extraction pass (ti-rnlqo.5.2).

Runs as a daemon thread spawned by CallCardHost after call_ended. Uses
instructor[anthropic] + Pydantic to find entities the L1 pipeline missed,
upserts results into CallCardStore, then broadcasts call_card_enriched.
"""
from __future__ import annotations

import concurrent.futures
import logging
import os
import threading
from typing import TYPE_CHECKING

from pydantic import BaseModel

from iris.capture.schemas import CapturedFact, FactType
from iris.capture.store import CallCardStore
from iris.capture.transcript import TranscriptStore

if TYPE_CHECKING:
    pass

_log = logging.getLogger(__name__)

_MODEL = "claude-haiku-4-5-20251001"
_TIMEOUT_S = 30
_SYSTEM = (
    "You are a precise call-note extractor. "
    "Do not re-extract facts in confirmed_entities."
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


# ── Helper ────────────────────────────────────────────────────────────────────

def _api_key(cfg: object) -> str:
    try:
        key = cfg.anthropic_api_key  # type: ignore[union-attr]
        if key:
            return key
    except AttributeError:
        pass
    try:
        key = cfg.call_card.anthropic_api_key  # type: ignore[union-attr]
        if key:
            return key
    except AttributeError:
        pass
    return os.environ.get("IRIS_ANTHROPIC_API_KEY", "") or os.environ.get("ANTHROPIC_API_KEY", "")


def _cloud_enrichment_enabled(cfg: object) -> bool:
    """Explicit opt-in, independent of whether an API key is resolvable.

    Fails closed (False) when cfg doesn't carry the flag at all — matching the
    no-cloud-by-default posture rather than assuming consent from key presence.
    """
    try:
        return bool(cfg.call_card_cloud_enrichment_enabled)  # type: ignore[union-attr]
    except AttributeError:
        pass
    try:
        return bool(cfg.call_card.call_card_cloud_enrichment_enabled)  # type: ignore[union-attr]
    except AttributeError:
        pass
    return False


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
    ) -> None:
        super().__init__(daemon=True, name=f"enricher-{session_id[:8]}")
        self._session_id = session_id
        self._store = store
        self._transcript_store = transcript_store
        self._api = api
        self._cfg = cfg

    def run(self) -> None:
        session_id = self._session_id
        if not _cloud_enrichment_enabled(self._cfg):
            _log.debug("PostCallEnricher: cloud enrichment disabled by config, skipping")
            return
        api_key = _api_key(self._cfg)
        if not api_key:
            _log.warning("PostCallEnricher: no api_key configured, skipping")
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

            transcript_block = "\n".join(
                f"{t.speaker}: {t.text}" for t in turns
            )

            user_prompt = (
                f"Confirmed entities (do not re-extract):\n{confirmed_entities_block}"
                f"\n\nFull transcript:\n{transcript_block}"
                "\n\nFind: (1) entity types spoken but NOT in the confirmed list; "
                "(2) action items needing clearer descriptions or due dates."
            )

            result = self._call_llm(api_key, user_prompt)
            self._apply_result(session_id, result)

        except concurrent.futures.TimeoutError:
            self._store.mark_enrichment_done(session_id, status=2)
            _log.warning(
                "PostCallEnricher: enrichment timed out for %s", session_id
            )
        except Exception as exc:
            self._store.mark_enrichment_done(session_id, status=2)
            _log.warning(
                "PostCallEnricher: enrichment failed for %s: %s", session_id, exc
            )

    def _call_llm(self, api_key: str, user_prompt: str) -> EnrichmentSchema:
        import anthropic
        import instructor

        client = instructor.from_anthropic(
            anthropic.Anthropic(api_key=api_key)
        )

        def _invoke() -> EnrichmentSchema:
            return client.chat.completions.create(
                model=_MODEL,
                response_model=EnrichmentSchema,
                max_retries=3,
                max_tokens=2048,
                system=_SYSTEM,
                messages=[{"role": "user", "content": user_prompt}],
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(_invoke)
            return future.result(timeout=_TIMEOUT_S)

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
