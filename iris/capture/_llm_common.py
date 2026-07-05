"""ask_structured — shared single-line-JSON contract for Call Card's L3 LLM
passes (ti-pkt2r.1). PostCallEnricher and PostCallRecapGenerator both drive
the same warm CallCardCloudSession through this one helper: ask, strip any
code fence, parse JSON, validate against the caller's schema, retry once,
give up (None) on a second failure.
"""
from __future__ import annotations

import json
import logging

from pydantic import BaseModel, ValidationError

_log = logging.getLogger(__name__)


def _strip_code_fence(text: str) -> str:
    """Strip a ```/```json fence around a model answer, if the model added one."""
    s = text.strip()
    if not s.startswith("```"):
        return s
    lines = s.splitlines()[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def ask_structured(
    cloud: object,          # CallCardCloudSession
    prompt: str,
    retry_prompt: str,
    schema: type[BaseModel],
) -> BaseModel | None:
    """Ask `cloud` for JSON matching `schema`, retrying once with `retry_prompt`.

    Returns None only when both attempts fail to produce valid JSON for
    `schema` — callers treat that as "skip this pass, log a warning."
    `cloud.ask()` itself raising (e.g. the warm session never became ready)
    is NOT caught here; it propagates to the caller's own except block.
    """
    for attempt_prompt in (prompt, retry_prompt):
        answer = cloud.ask(attempt_prompt)
        cleaned = _strip_code_fence(answer)
        try:
            data = json.loads(cleaned)
            return schema.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as exc:
            _log.warning("ask_structured: invalid response (%s): %r", exc, cleaned[:200])
    return None
