"""Tests for ConversationContext — window lookup, gist recall, disambiguation,
no-match fallback, privacy notice, and non-blocking gist compression.

Transcript-tier paths are tagged xfail (ti-ccc.11.1.2 not yet implemented).
No network, no disk access, no LLM calls.
"""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

import pytest

from iris.context import (
    GIST_PREFIX,
    NO_MATCH_REPLY,
    PRIVACY_NOTICE,
    WINDOW_PREFIX,
    ConversationContext,
    ContextTurn,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ctx_with_gist(gist_text: str) -> ConversationContext:
    """Return a context with gist state set directly (no thread wait needed)."""
    ctx = ConversationContext()
    ctx._gist = gist_text
    ctx._gist_active = True
    return ctx


# ---------------------------------------------------------------------------
# Window tier — happy path
# ---------------------------------------------------------------------------

def test_window_reply_starts_with_window_prefix():
    ctx = ConversationContext()
    ctx.add("far", "The budget is eighty thousand dollars")
    result = ctx.lookup("budget number")
    assert result.reply.startswith(WINDOW_PREFIX)


def test_window_tier_label():
    ctx = ConversationContext()
    ctx.add("far", "The budget is eighty thousand dollars")
    result = ctx.lookup("budget")
    assert result.tier == "window"


def test_window_reply_contains_matching_text():
    ctx = ConversationContext()
    ctx.add("far", "The budget is eighty thousand dollars")
    result = ctx.lookup("budget")
    assert "eighty thousand" in result.reply or "budget" in result.reply


def test_window_matches_list_populated():
    ctx = ConversationContext()
    ctx.add("far", "The budget is eighty thousand dollars")
    result = ctx.lookup("budget")
    assert len(result.matches) >= 1
    assert result.matches[0].tier == "window"


# ---------------------------------------------------------------------------
# Window — capacity and eviction
# ---------------------------------------------------------------------------

def test_window_holds_at_most_12_turns():
    ctx = ConversationContext()
    for i in range(15):
        ctx.add("far", f"turn {i}")
    assert ctx.window_size == 12


def test_window_evicts_oldest():
    ctx = ConversationContext()
    for i in range(13):
        ctx.add("far", f"unique-token-{i} filler here")
    # turn 0 is gone; turn 12 is present
    result_old = ctx.lookup("unique-token-0")
    result_new = ctx.lookup("unique-token-12")
    assert result_new.tier == "window"
    assert result_old.tier != "window"


# ---------------------------------------------------------------------------
# Speaker field — frozen ContextTurn
# ---------------------------------------------------------------------------

def test_context_turn_speaker_is_immutable():
    turn = ContextTurn(speaker="far", text="hello")
    with pytest.raises((AttributeError, TypeError)):
        turn.speaker = "operator"  # type: ignore[misc]


def test_add_preserves_speaker_in_matches():
    ctx = ConversationContext()
    ctx.add("far", "Far party relevant text here")
    result = ctx.lookup("party relevant text")
    assert any(m.speaker == "far" for m in result.matches)


def test_add_speaker_not_overwritten_by_lookup():
    ctx = ConversationContext()
    ctx.add("far", "Far said something interesting")
    ctx.lookup("something")
    # Trigger lookup — should not mutate existing turns
    result = ctx.lookup("interesting far")
    assert any(m.speaker == "far" for m in result.matches)


# ---------------------------------------------------------------------------
# Gist tier
# ---------------------------------------------------------------------------

def test_gist_reply_starts_with_gist_prefix():
    # Use text without trailing period to avoid score mismatch
    ctx = _ctx_with_gist("Acme Logistics was mentioned as the shipping vendor")
    result = ctx.lookup("which vendor")
    assert result.reply.startswith(GIST_PREFIX)


def test_gist_tier_label():
    ctx = _ctx_with_gist("Vendor is Acme Logistics")
    result = ctx.lookup("vendor")
    assert result.tier == "gist"


def test_gist_hedging_fires_for_digit_number():
    ctx = _ctx_with_gist("Budget $80,000 was approved")
    result = ctx.lookup("budget")
    assert result.hedged is True
    assert "confirm" in result.reply.lower()


def test_gist_hedging_fires_for_written_amount():
    ctx = _ctx_with_gist("Budget is eighty thousand dollars")
    result = ctx.lookup("budget")
    assert result.hedged is True


def test_gist_hedging_fires_for_proper_name():
    ctx = _ctx_with_gist("Sarah Johnson confirmed the order")
    result = ctx.lookup("confirmed")
    assert result.hedged is True


def test_gist_hedging_fires_for_code():
    ctx = _ctx_with_gist("Reference RL-4492 was provided")
    result = ctx.lookup("reference")
    assert result.hedged is True


def test_gist_hedging_not_fired_for_general_statement():
    ctx = _ctx_with_gist("She mentioned shipping would be handled quickly")
    result = ctx.lookup("shipping")
    assert result.hedged is False
    assert "confirm" not in result.reply.lower()


def test_gist_inactive_not_used():
    ctx = ConversationContext()
    ctx._gist = "Vendor Acme Logistics"
    ctx._gist_active = False  # explicit: inactive
    result = ctx.lookup("vendor")
    assert result.tier != "gist"


# ---------------------------------------------------------------------------
# No-match fallback
# ---------------------------------------------------------------------------

def test_no_match_reply_equals_constant():
    ctx = ConversationContext()
    result = ctx.lookup("completely unrelated xyz 99999")
    assert result.reply == NO_MATCH_REPLY


def test_no_match_tier_is_none():
    ctx = ConversationContext()
    result = ctx.lookup("xyzzy nothing here")
    assert result.tier == "none"


def test_no_match_matches_list_is_empty():
    ctx = ConversationContext()
    result = ctx.lookup("nothing here at all")
    assert result.matches == []


def test_no_match_reply_has_no_technical_details():
    ctx = ConversationContext()
    result = ctx.lookup("unrelated")
    assert "exception" not in result.reply.lower()
    assert "traceback" not in result.reply.lower()


# ---------------------------------------------------------------------------
# Disambiguation — verbal cap 2, annotation has full ranked list
# ---------------------------------------------------------------------------

def test_disambiguation_verbal_has_at_most_two_options():
    ctx = ConversationContext()
    ctx.add("far", "The delivery schedule is tight")
    ctx.add("far", "The project timeline is next week")
    ctx.add("far", "We should schedule a follow-up")
    result = ctx.lookup("schedule")
    assert result.reply.startswith(WINDOW_PREFIX)
    # Verbal body: "top1; top2" → at most one semicolon
    verbal_body = result.reply[len(WINDOW_PREFIX):].strip()
    parts = [p for p in verbal_body.split(";") if p.strip()]
    assert len(parts) <= 2


def test_disambiguation_matches_has_all_scoring_turns():
    ctx = ConversationContext()
    ctx.add("far", "The delivery schedule is tight")
    ctx.add("far", "The project schedule is packed")
    ctx.add("far", "We should schedule a follow-up soon")
    result = ctx.lookup("schedule")
    assert len(result.matches) >= 2


# ---------------------------------------------------------------------------
# Privacy notice — emitted via callback on first add()
# ---------------------------------------------------------------------------

def test_privacy_notice_emitted_on_first_add():
    events: list = []
    ctx = ConversationContext(emit=events.append)
    ctx.add("far", "Hello")
    notice_events = [e for e in events if isinstance(e, tuple) and e[1] == "privacy_notice"]
    assert len(notice_events) == 1


def test_privacy_notice_text_matches_constant():
    events: list = []
    ctx = ConversationContext(emit=events.append)
    ctx.add("far", "Hello")
    notice = next(e for e in events if isinstance(e, tuple) and e[1] == "privacy_notice")
    assert notice[2] == PRIVACY_NOTICE


def test_privacy_notice_emitted_only_once():
    events: list = []
    ctx = ConversationContext(emit=events.append)
    ctx.add("far", "Hello")
    ctx.add("operator", "Hi")
    ctx.add("far", "Bye")
    notices = [e for e in events if isinstance(e, tuple) and e[1] == "privacy_notice"]
    assert len(notices) == 1


# ---------------------------------------------------------------------------
# Background gist compression — non-blocking
# ---------------------------------------------------------------------------

def test_gist_compression_does_not_block_add():
    slow_started = threading.Event()

    def slow_compress(prompt: str) -> str:
        slow_started.set()
        time.sleep(0.3)
        return "compressed summary"

    ctx = ConversationContext(compress=slow_compress)
    for i in range(12):
        ctx.add("far", f"turn {i}")

    t0 = time.monotonic()
    ctx.add("far", "turn 12 — triggers eviction and compression")
    elapsed = time.monotonic() - t0
    assert elapsed < 0.15, f"add() blocked for {elapsed:.3f}s — compression must be async"


def test_gist_compression_updates_gist_eventually():
    compress_done = threading.Event()

    def mock_compress(prompt: str) -> str:
        compress_done.set()
        return "Vendor Acme Logistics"

    ctx = ConversationContext(compress=mock_compress)
    for i in range(12):
        ctx.add("far", f"turn {i}")
    ctx.add("far", "turn 12 — trigger eviction")

    compress_done.wait(timeout=2.0)
    time.sleep(0.05)
    assert ctx.gist_active is True
    assert "Acme Logistics" in ctx.gist


def test_gist_updated_event_emitted():
    events: list = []
    compress_done = threading.Event()

    def mock_compress(prompt: str) -> str:
        compress_done.set()
        return "summary text"

    ctx = ConversationContext(compress=mock_compress, emit=events.append)
    for i in range(12):
        ctx.add("far", f"turn {i}")
    ctx.add("far", "turn 12 — trigger eviction")

    compress_done.wait(timeout=2.0)
    time.sleep(0.05)
    kinds = [e[1] for e in events if isinstance(e, tuple)]
    assert "gist_updated" in kinds


# ---------------------------------------------------------------------------
# Transcript tier — xfail stubs (ti-ccc.11.1.2)
# ---------------------------------------------------------------------------

@pytest.mark.xfail(reason="ti-ccc.11.1.2: on-demand transcript tier not yet implemented",
                   strict=False)
def test_transcript_checking_prefix_when_store_available():
    """When transcript store is available, reply must include 'Checking the transcript'."""
    from iris.context import TranscriptContext  # noqa: F401 — not yet implemented

    store = MagicMock()
    store.query.return_value = [MagicMock(text="Reference RL-4492", at_s=120.0)]
    ctx = TranscriptContext(base=ConversationContext(), transcript_store=store)
    result = ctx.lookup("reference number at 2 minutes")
    assert "Checking the transcript" in result.reply


@pytest.mark.xfail(reason="ti-ccc.11.1.2: on-demand transcript tier not yet implemented",
                   strict=False)
def test_transcript_unavailable_returns_fallback():
    from iris.context import TranscriptContext  # noqa: F401

    ctx = TranscriptContext(base=ConversationContext(), transcript_store=None)
    result = ctx.lookup("reference number")
    assert "don't have the earlier part" in result.reply.lower()


@pytest.mark.xfail(reason="ti-ccc.11.1.2: on-demand transcript tier not yet implemented",
                   strict=False)
def test_transcript_unavailable_annotation_distinct():
    """PM decision: [context: transcript store not yet available — clarification sent]."""
    from iris.context import TranscriptContext  # noqa: F401

    ctx = TranscriptContext(base=ConversationContext(), transcript_store=None)
    result = ctx.lookup("anything")
    ann_text = " ".join(m.text for m in result.matches)
    assert "not yet available" in ann_text.lower()
