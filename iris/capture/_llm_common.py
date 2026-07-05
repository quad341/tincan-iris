"""Shared API-key resolution for capture-pipeline LLM call-sites (ti-6a1y3).

PostCallEnricher (L3 extraction) and PostCallRecapGenerator (post-call
restatement) both gate their optional LLM calls through this one helper, so
a future real Config.anthropic_api_key field benefits both without a second
edit.
"""
from __future__ import annotations

import os


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
