"""Unit tests for L1CaptureProcessor + 6 extractors (ti-rnlqo.2.4).

Tests are written BEFORE the implementation; they will fail (red) until
iris/capture/processor.py lands.  Only the _run()/_proc() helpers bind to
the processor API — reconcile the signature there if the builder's contract
differs slightly.

Documented contract:
  L1CaptureProcessor(session_id="", roster=None, now=None)
  .process(text, speaker, turn_id, offset_s) -> list[CapturedFact | ActionItem]

Each CapturedFact has: .fact_type (str-eq to FactType.*), .normalized_value,
.confidence, .critical, .speaker, .transcript_turn_id.
Each ActionItem has: .fact_type == "action_item", .owner, .description,
.trigger, .due_date (ISO date str or None).
"""
from __future__ import annotations

import datetime

import pytest

from iris.capture.processor import L1CaptureProcessor
from iris.capture.schemas import FactType

# Pin reference date so date-relative tests are deterministic.
_NOW = datetime.date(2026, 6, 30)

# A phone in the roster (should suppress critical flag).
_ROSTER_PHONE = "+15558675309"


def _proc(*, roster=None, now=_NOW):
    return L1CaptureProcessor(roster=roster, now=now)


def _run(text, fact_type, *, speaker="far", turn_id=1, offset_s=100.0, roster=None, now=_NOW):
    """Run one utterance through a fresh L1CaptureProcessor; return first matching fact."""
    facts = L1CaptureProcessor(roster=roster, now=now).process(
        text, speaker=speaker, turn_id=turn_id, offset_s=offset_s
    )
    hits = [f for f in facts if getattr(f, "fact_type", None) == fact_type]
    return hits[0] if hits else None


# ===========================================================================
# PhoneExtractor
# ===========================================================================


def test_phone_e164():
    f = _run("you can reach me at 415-555-1234", FactType.PHONE)
    assert f is not None
    assert f.normalized_value == "+14155551234"


def test_phone_formatted_normalized():
    f = _run("call me back at (555) 867-5309", FactType.PHONE)
    assert f is not None
    assert f.normalized_value == "+15558675309"


def test_phone_invalid_too_short_not_emitted():
    assert _run("dial 123-456", FactType.PHONE) is None


def test_phone_confidence():
    f = _run("my number is 415-555-1234", FactType.PHONE)
    assert f is not None
    assert f.confidence == pytest.approx(0.9)


# ===========================================================================
# CueIdExtractor
# ===========================================================================


def test_cueid_same_turn():
    f = _run("your confirmation number is REF-88211", FactType.CASE_ID)
    assert f is not None
    assert f.normalized_value == "REF-88211"


def test_cueid_various_cue_words():
    for utterance, expected in [
        ("the case id: AB-9921", "AB-9921"),
        ("here's your claim number XY-001", "XY-001"),
        ("reference number R88211", "R88211"),
    ]:
        f = _run(utterance, FactType.CASE_ID)
        assert f is not None, f"no case_id from {utterance!r}"
        assert f.normalized_value == expected


def test_cueid_prev_turn_carryover():
    """Cue word in turn N allows extracting ID in turn N+1."""
    proc = _proc()
    proc.process("what's the reference number?", speaker="far", turn_id=1, offset_s=5.0)
    facts2 = proc.process("it's REF-77400", speaker="far", turn_id=2, offset_s=8.0)
    hits = [f for f in facts2 if getattr(f, "fact_type", None) == FactType.CASE_ID]
    assert hits, "case_id should be extracted when cue was in previous turn"
    assert hits[0].normalized_value == "REF-77400"


def test_cueid_pure_numeric_without_cue_not_extracted():
    """A bare number with no cue word should not be emitted as case_id."""
    assert _run("the balance is 88211", FactType.CASE_ID) is None


def test_cueid_critical_always_true():
    f = _run("your ticket number is TK-5551", FactType.CASE_ID)
    assert f is not None
    assert f.critical is True


def test_cueid_confidence():
    f = _run("the order number is ORD-9900", FactType.CASE_ID)
    assert f is not None
    assert f.confidence == pytest.approx(0.95)


# ===========================================================================
# AmountExtractor
# ===========================================================================


def test_amount_dollar_sign():
    f = _run("there's a $47.50 cancellation fee", FactType.AMOUNT)
    assert f is not None
    assert f.normalized_value == "47.50"


def test_amount_dollar_sign_with_cents():
    f = _run("the charge is $129.00", FactType.AMOUNT)
    assert f is not None
    assert f.normalized_value == "129.00"


@pytest.mark.xfail(reason="KNOWN-HARD: spoken word-amount needs word→number pass", strict=False)
def test_amount_spoken_form():
    f = _run("that'll be twenty dollars", FactType.AMOUNT)
    assert f is not None and f.normalized_value == "20.00"


def test_amount_critical_always_true():
    f = _run("a $47.50 fee applies", FactType.AMOUNT)
    assert f is not None
    assert f.critical is True


def test_amount_confidence():
    f = _run("total is $55.00", FactType.AMOUNT)
    assert f is not None
    assert f.confidence == pytest.approx(0.9)


# ===========================================================================
# DateExtractor
# ===========================================================================


def test_date_future_iso8601():
    # "July 15th" is 15 days from _NOW (2026-06-30)
    f = _run("we'll resolve it by July 15th", FactType.DATE)
    assert f is not None
    assert f.normalized_value == "2026-07-15"


def test_date_today_skipped():
    # A date matching today should be filtered out (not a useful future deadline)
    assert _run("the policy renews today", FactType.DATE) is None


def test_date_confidence():
    f = _run("the appointment is July 15th", FactType.DATE)
    assert f is not None
    assert f.confidence == pytest.approx(0.8)


def test_date_critical_far_out():
    # >7 days from _NOW → critical=True
    f = _run("we'll have it resolved by July 15th", FactType.DATE, now=_NOW)
    assert f is not None
    assert f.critical is True


def test_date_not_critical_near():
    # ≤7 days from _NOW (July 3 is 3 days out) → critical=False
    f = _run("we'll call you back by July 3rd", FactType.DATE, now=_NOW)
    assert f is not None
    assert f.critical is False


@pytest.mark.xfail(
    reason="KNOWN-HARD: dateparser returns None on weekday+bare-hour combo", strict=False
)
def test_date_weekday_bare_hour():
    f = _run("we'll have a tech out next Tuesday at 2", FactType.DATE)
    assert f is not None and "14:00" in f.normalized_value


# ===========================================================================
# ActionExtractor
# ===========================================================================


def test_action_commitment_phrase_captured():
    f = _run("I'll send you the form today", "action_item", speaker="operator")
    assert f is not None


def test_action_owner_is_speaker():
    f = _run("I'll call you back by Friday", "action_item", speaker="operator")
    assert f is not None
    assert f.owner == "operator"


def test_action_far_speaker_owner():
    f = _run("we'll waive the fee", "action_item", speaker="far")
    assert f is not None
    assert f.owner == "far"


def test_action_description_is_full_utterance():
    utterance = "I'll send you the refund confirmation by email"
    f = _run(utterance, "action_item", speaker="operator")
    assert f is not None
    assert f.description == utterance


def test_action_trigger_is_matched_phrase():
    f = _run("I'll email you the form today", "action_item", speaker="operator")
    assert f is not None
    assert f.trigger  # non-empty; e.g. "I'll" or "I'll email"


def test_action_with_date_links_due_date():
    # "by Friday" is 3 days out from _NOW
    f = _run("I'll call you back by Friday", "action_item", speaker="operator", now=_NOW)
    assert f is not None
    assert f.due_date is not None  # DateExtractor result wired in


# ===========================================================================
# NameExtractor
# ===========================================================================


def test_name_far_party():
    f = _run("my name is Jane Smith", FactType.NAME, speaker="far")
    assert f is not None
    assert "jane" in f.normalized_value.lower() or "smith" in f.normalized_value.lower()


def test_name_operator_not_captured():
    # Operator utterances should NOT trigger NameExtractor
    assert _run("my name is Jane Smith", FactType.NAME, speaker="operator") is None


def test_name_confidence():
    f = _run("this is Karen from billing", FactType.NAME, speaker="far")
    assert f is not None
    assert f.confidence == pytest.approx(0.7)


# ===========================================================================
# Critical-flag rules (roster)
# ===========================================================================


def test_phone_not_in_roster_is_critical():
    f = _run("call me at 415-555-1234", FactType.PHONE, roster=frozenset())
    assert f is not None
    assert f.critical is True


def test_phone_in_roster_not_critical():
    f = _run(
        "call me at (555) 867-5309",
        FactType.PHONE,
        roster=frozenset({_ROSTER_PHONE}),
    )
    assert f is not None
    assert f.critical is False


# ===========================================================================
# Multi-match
# ===========================================================================


def test_multi_match_case_id_and_amount():
    """A single utterance yielding both case_id + amount — both critical."""
    facts = L1CaptureProcessor(now=_NOW).process(
        "Your case ID is REF-88211 and the total is $47.50",
        speaker="far",
        turn_id=1,
        offset_s=10.0,
    )
    types_found = {getattr(f, "fact_type", None) for f in facts}
    assert FactType.CASE_ID in types_found, "case_id not found in multi-match"
    assert FactType.AMOUNT in types_found, "amount not found in multi-match"

    for f in facts:
        if getattr(f, "fact_type", None) in {FactType.CASE_ID, FactType.AMOUNT}:
            assert f.critical is True, f"{f.fact_type} should be critical"


# ===========================================================================
# Edge cases
# ===========================================================================


def test_empty_text_returns_empty_list():
    assert L1CaptureProcessor().process("", speaker="far", turn_id=1, offset_s=0.0) == []


def test_whitespace_only_returns_empty_list():
    assert L1CaptureProcessor().process("   ", speaker="far", turn_id=1, offset_s=0.0) == []


def test_malformed_input_does_not_raise():
    garbage_inputs = [
        "!!@@##$$%%^^&&**()",
        "\x00\x01\x02",
        "a" * 10_000,
    ]
    proc = L1CaptureProcessor()
    for text in garbage_inputs:
        try:
            proc.process(text, speaker="far", turn_id=1, offset_s=0.0)
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"process() raised on malformed input {text[:40]!r}: {exc}")


def test_cue_ctx_maxlen():
    """Internal cue context window has exactly 2 slots."""
    proc = L1CaptureProcessor()
    assert hasattr(proc, "_cue_ctx"), "_cue_ctx attribute missing"
    assert proc._cue_ctx.maxlen == 2
