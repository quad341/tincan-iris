"""Acceptance tests for the Call Card L1 extractors — STAGED, ahead of impl.

Written against the architect's documented `iris/capture` API (ti-rnlqo.2.3 /
.2.4) *before* the code lands, so they're ready the moment there's a baseline.

Safe to check in at any stage — never red:
  * `importorskip` → the whole module SKIPS until `iris.capture.processor` exists.
  * cases our library validation (PR #121) proved the naive impl fails are marked
    `xfail(strict=False)` → allowed to fail, and surface as XPASS the moment the
    gap is closed (flip to strict=True later to *enforce* them).

Only `_extract()` binds to the real API — if the builder's signature differs,
that's the one spot to reconcile at sling time.
"""
import pytest

pytest.importorskip(
    "iris.capture.processor", reason="iris.capture not built yet (ti-rnlqo.2.3)"
)

from iris.capture.processor import L1CaptureProcessor  # noqa: E402


def _extract(text, fact_type, *, speaker="far", turn_id=1, offset_s=100.0):
    """Run one utterance through the L1 processor; return the first fact of a type.

    The single API-binding point. Documented contract: process(text, speaker,
    turn_id, offset_s) -> list[CapturedFact | ActionItem], each with .fact_type,
    .normalized_value, .critical.
    """
    facts = L1CaptureProcessor().process(
        text, speaker=speaker, turn_id=turn_id, offset_s=offset_s
    )
    hits = [f for f in facts if getattr(f, "fact_type", None) == fact_type]
    return hits[0] if hits else None


# --- cue-anchored reference / case IDs (the slice-1 thesis) ---------------

@pytest.mark.parametrize(
    "utterance,expected",
    [
        ("your confirmation number is REF-88211", "REF-88211"),
        ("the case id: AB-9921", "AB-9921"),
        pytest.param(
            "reference number, that's 8 8 2 1 1",
            "88211",
            marks=pytest.mark.xfail(
                reason="KNOWN-HARD: spaced/spelled digits; naive regex grabbed 'number'",
                strict=False,
            ),
        ),
    ],
)
def test_cue_id_normalized(utterance, expected):
    f = _extract(utterance, "case_id")
    assert f is not None, f"no case_id extracted from {utterance!r}"
    assert f.normalized_value == expected
    assert f.critical is True  # case/reference IDs are ALWAYS critical


def test_cue_id_never_returns_the_cue_word():
    f = _extract("reference number, that's 8 8 2 1 1", "case_id")
    assert f is None or f.normalized_value.lower() != "number"


def test_non_cue_sentence_yields_no_id():
    assert _extract("okay so the weather is nice today", "case_id") is None


# --- amounts --------------------------------------------------------------

def test_amount_digit_form():
    f = _extract("a $129.00 cancellation fee", "amount")
    assert f is not None and f.normalized_value == "129.00"
    assert f.critical is True  # amounts are ALWAYS critical


@pytest.mark.xfail(
    reason="KNOWN-HARD: spoken word-amount needs word->number", strict=False
)
def test_amount_spoken_form():
    f = _extract("that'll be forty-seven fifty", "amount")
    assert f is not None and f.normalized_value == "47.50"


# --- dates / appointments -------------------------------------------------
# NOTE: deterministic date tests require the processor to accept a reference
# 'now' (so "Friday" resolves stably). Assumed injectable; reconcile at sling.

@pytest.mark.xfail(
    reason="KNOWN-HARD: dateparser returns None on 'next Tuesday at 2'", strict=False
)
def test_appointment_weekday_bare_hour():
    f = _extract("we'll have a tech out next Tuesday at 2", "date")
    assert f is not None and f.normalized_value.endswith("14:00")


# --- phone / email / name / action / contradiction ------------------------

def test_phone_e164():
    f = _extract("you can reach me at 415-555-1234", "phone")
    assert f is not None and f.normalized_value == "+14155551234"


def test_email_spoken_form():
    f = _extract("send the form to help dot desk at acme dot com", "email")
    assert f is not None and f.normalized_value == "helpdesk@acme.com"


def test_agent_name():
    f = _extract("my name is Karen from billing", "name", speaker="far")
    assert f is not None and "karen" in f.normalized_value.lower()


def test_action_item_owner_is_operator():
    f = _extract("I'll call you back by Friday", "action_item", speaker="operator")
    assert f is not None and f.owner == "operator"


def test_contradiction_flag():
    f = _extract(
        "wait, I thought you said it was already refunded", "flag", speaker="operator"
    )
    assert f is not None
