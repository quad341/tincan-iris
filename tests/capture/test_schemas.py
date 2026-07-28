"""Unit tests for iris/capture/schemas.py (ti-rnlqo.2.4)."""
from __future__ import annotations

from iris.capture.schemas import ActionItem, CapturedFact, ContactRoster, FactType


def test_facttype_values():
    assert FactType.PHONE == "phone"
    assert FactType.CASE_ID == "case_id"
    assert FactType.AMOUNT == "amount"
    assert FactType.DATE == "date"
    assert FactType.NAME == "name"
    assert FactType.EMAIL == "email"


def test_facttype_is_str_subclass():
    assert isinstance(FactType.PHONE, str)


def test_captured_fact_instantiation():
    f = CapturedFact(
        session_id="sess-1",
        fact_type=FactType.PHONE,
        raw_text="call me at 415-555-1234",
        normalized_value="+14155551234",
        transcript_turn_id=1,
        transcript_offset_s=10.0,
        speaker="far",
        confidence=0.9,
        critical=True,
    )
    assert f.fact_type == FactType.PHONE
    assert f.normalized_value == "+14155551234"
    assert f.critical is True
    assert f.confirmed is None
    assert f.source_layer == 1
    assert f.id  # auto-generated


def test_captured_fact_ids_are_unique():
    make = lambda: CapturedFact(  # noqa: E731
        session_id="s",
        fact_type=FactType.AMOUNT,
        raw_text="$10",
        normalized_value="10.00",
        transcript_turn_id=1,
        transcript_offset_s=0.0,
        speaker="far",
        confidence=0.9,
        critical=True,
    )
    assert make().id != make().id


def test_action_item_instantiation():
    a = ActionItem(
        session_id="sess-1",
        description="I'll call you back by Friday",
        trigger="I'll",
        owner="operator",
        transcript_turn_id=3,
        transcript_offset_s=25.0,
        speaker="operator",
        confidence=0.85,
        due_date="2026-07-03",
    )
    assert a.owner == "operator"
    assert a.due_date == "2026-07-03"
    assert a.confirmed is None
    assert a.source_layer == 1
    assert a.id


def test_contact_roster_is_frozenset():
    roster: ContactRoster = frozenset({"+14155551234", "+15558675309"})
    assert isinstance(roster, frozenset)
    assert "+14155551234" in roster
