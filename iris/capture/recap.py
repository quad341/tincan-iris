"""PostCallRecapGenerator — grounded LLM restatement of a call's confirmed
facts/action items (ti-6a1y3, Call Card AFTER Action Flow AF1, ti-pkt2r.1).

Runs as a daemon thread spawned by CallCardHost.stop_session(), strictly
after the PostCallEnricher (L3) thread it's given finishes. The prompt is
built ONLY from already-extracted, confirmed/high-confidence facts and
action items — the raw transcript is never included anywhere in this
module, which is the structural mechanism that enforces "restate, don't
invent" (ti-ve84d design doc, section 7-C). No FR6 speaker filter is needed
here: operator confirmation is itself trust-elevating, unlike the raw
transcript enrichment reads.

Driven through the daemon's warm CallCardCloudSession (a vendor Claude Code
TUI session) — never a raw Anthropic API key or SDK; see docs/adr/0001.
"""
from __future__ import annotations

import logging
import threading

from pydantic import BaseModel

from iris.capture._llm_common import ask_structured
from iris.capture.store import CallCardStore

_log = logging.getLogger(__name__)

_SHAPE = '{"text": "<one short, plain-language recap sentence>"}'


class OutcomeSummary(BaseModel):
    text: str


def _build_prompt(facts_block: str, items_block: str) -> str:
    return (
        f"Confirmed facts:\n{facts_block}\n\n"
        f"Confirmed action items:\n{items_block}\n\n"
        "Restate the above as one short, plain-language recap sentence — "
        "nothing beyond what is given here.\n\n"
        f"Reply with exactly this JSON shape, one line, no other text:\n{_SHAPE}"
    )


def _retry_prompt() -> str:
    return (
        "That reply was not valid JSON matching the required shape. Reply "
        f"again with ONLY the JSON, one line, matching exactly:\n{_SHAPE}"
    )


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
        cloud: object,  # CallCardCloudSession | None
        confidence_threshold: float = 0.8,
    ) -> None:
        super().__init__(daemon=True, name=f"recap-{session_id[:8]}")
        self._session_id = session_id
        self._store = store
        self._enricher_thread = enricher_thread
        self._api = api
        self._cfg = cfg
        self._cloud = cloud
        self._confidence_threshold = confidence_threshold

    def run(self) -> None:
        self._enricher_thread.join()

        session_id = self._session_id
        if self._cloud is None:
            _log.warning("PostCallRecapGenerator: no cloud session configured, skipping")
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

        facts_block = "\n".join(
            f"{f['fact_type']}: {f['normalized_value']}" for f in facts
        ) or "(none)"
        items_block = "\n".join(
            f"{i['description']} (owner: {i['owner']}, due: {i['due_date'] or 'unspecified'})"
            for i in items
        ) or "(none)"

        try:
            prompt = _build_prompt(facts_block, items_block)
            result = ask_structured(self._cloud, prompt, _retry_prompt(), OutcomeSummary)
            if result is None:
                _log.warning("PostCallRecapGenerator: no valid response for %s", session_id)
                return
        except Exception as exc:
            _log.warning(
                "PostCallRecapGenerator: recap failed for %s: %s", session_id, exc
            )
            return

        self._store.set_outcome_summary(session_id, result.text)
        self._api.broadcast({  # type: ignore[union-attr]
            "event": "call_card_recap_ready",
            "session_id": session_id,
        })
