"""PostCallRecapGenerator — grounded LLM restatement of a call's confirmed
facts/action items (ti-6a1y3, Call Card AFTER Action Flow AF1).

Runs as a daemon thread spawned by CallCardHost.stop_session(), strictly
after the PostCallEnricher (L3) thread it's given finishes. The prompt is
built ONLY from already-extracted, confirmed/high-confidence facts and
action items — the raw transcript is never included anywhere in this
module, which is the structural mechanism that enforces "restate, don't
invent" (ti-ve84d design doc, section 7-C).
"""
from __future__ import annotations

import concurrent.futures
import logging
import threading

from pydantic import BaseModel

from iris.capture._llm_common import _api_key
from iris.capture.store import CallCardStore

_log = logging.getLogger(__name__)

_MODEL = "claude-haiku-4-5-20251001"
_TIMEOUT_S = 30
_SYSTEM = (
    "You restate a call's confirmed facts and action items as one short, "
    "plain-language recap. Do not add, infer, or guess anything beyond what "
    "is given."
)


class OutcomeSummary(BaseModel):
    text: str


class PostCallRecapGenerator(threading.Thread):
    """Daemon thread for post-call recap generation. Spawned once per call.

    Always waits for the given PostCallEnricher thread to finish first, so
    the recap reflects L3-enriched facts/action items too.
    """

    def __init__(
        self,
        *,
        session_id: str,
        store: CallCardStore,
        enricher_thread: threading.Thread,
        api: object,    # DaemonAPI
        cfg: object,
        confidence_threshold: float = 0.8,
    ) -> None:
        super().__init__(daemon=True, name=f"recap-{session_id[:8]}")
        self._session_id = session_id
        self._store = store
        self._enricher_thread = enricher_thread
        self._api = api
        self._cfg = cfg
        self._confidence_threshold = confidence_threshold

    def run(self) -> None:
        self._enricher_thread.join()

        session_id = self._session_id
        api_key = _api_key(self._cfg)
        if not api_key:
            _log.warning("PostCallRecapGenerator: no api_key configured, skipping")
            return

        card = self._store.get_call_card(session_id)
        if not card:
            _log.warning("PostCallRecapGenerator: no call card for %s", session_id)
            return

        facts = [
            f for f in card["facts"]
            if f["confirmed"] or f["confidence"] >= self._confidence_threshold
        ]
        items = [
            i for i in card["action_items"]
            if i["confirmed"] or i["confidence"] >= self._confidence_threshold
        ]
        if not facts and not items:
            return

        try:
            summary = self._call_llm(api_key, facts, items)
        except Exception as exc:
            _log.warning(
                "PostCallRecapGenerator: recap failed for %s: %s", session_id, exc
            )
            return

        self._store.set_outcome_summary(session_id, summary)
        self._api.broadcast({  # type: ignore[union-attr]
            "event": "call_card_recap_ready",
            "session_id": session_id,
        })

    def _call_llm(self, api_key: str, facts: list[dict], items: list[dict]) -> str:
        import anthropic
        import instructor

        facts_block = "\n".join(
            f"{f['fact_type']}: {f['normalized_value']}" for f in facts
        ) or "(none)"
        items_block = "\n".join(
            f"{i['description']} (owner: {i['owner']}, due: {i['due_date'] or 'unspecified'})"
            for i in items
        ) or "(none)"
        user_prompt = (
            f"Confirmed facts:\n{facts_block}\n\n"
            f"Confirmed action items:\n{items_block}\n\n"
            "Restate the above as one short, plain-language recap sentence."
        )

        client = instructor.from_anthropic(anthropic.Anthropic(api_key=api_key))

        def _invoke() -> OutcomeSummary:
            return client.chat.completions.create(
                model=_MODEL,
                response_model=OutcomeSummary,
                max_retries=3,
                max_tokens=512,
                system=_SYSTEM,
                messages=[{"role": "user", "content": user_prompt}],
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(_invoke)
            result = future.result(timeout=_TIMEOUT_S)
        return result.text
