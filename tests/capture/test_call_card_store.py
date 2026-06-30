"""Unit tests for iris/capture/store.py — CallCardStore (ti-rnlqo.3.4).

Tests are written BEFORE the implementation lands on this branch; they will
fail (red) until iris/capture/store.py and iris/capture/schemas.py are present.

Documented contract:
  CallCardStore(db_path=Path)
    .load_or_create(session_id, caller_number, contact_id=None, context_notes=None)
    .add_fact(fact: CapturedFact)              # session_id lives on the fact
    .add_action_item(item: ActionItem)         # session_id lives on the item
    .confirm_fact(fact_id, confirmed, normalized_value=None)
    .mark_ended(session_id)
    .mark_disclosure_ack(session_id, skipped=False)
    .mark_enrichment_done(session_id, status=1)  # 0=pending, 1=success, 2=failed
    .get_call_card(session_id) -> dict         # {session_id, facts, action_items,
                                               #  disclosure_ack: bool, enrichment_done: int}
  PRAGMA journal_mode=WAL on every new store.
  Thread-safe: check_same_thread=False + per-write threading.Lock.
"""
from __future__ import annotations

import sqlite3
import threading

import pytest

from iris.capture.schemas import ActionItem, CapturedFact, FactType
from iris.capture.store import CallCardStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _store(tmp_path):
    return CallCardStore(db_path=tmp_path / "test.db")


def _fact(session_id="sess-1", *, fact_type=FactType.PHONE):
    return CapturedFact(
        session_id=session_id,
        fact_type=fact_type,
        raw_text="call me at 415-555-1234",
        normalized_value="+14155551234",
        transcript_turn_id=1,
        transcript_offset_s=10.0,
        speaker="far",
        confidence=0.9,
        critical=True,
    )


def _action_item(session_id="sess-1"):
    return ActionItem(
        session_id=session_id,
        description="I'll call you back by Friday",
        trigger="I'll",
        owner="operator",
        transcript_turn_id=2,
        transcript_offset_s=20.0,
        speaker="operator",
        confidence=0.85,
        due_date="2026-07-03",
    )


# ---------------------------------------------------------------------------
# 1. WAL pragma
# ---------------------------------------------------------------------------


def test_wal_journal_mode(tmp_path):
    """CallCardStore sets PRAGMA journal_mode=WAL on creation."""
    _store(tmp_path)
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    row = conn.execute("PRAGMA journal_mode").fetchone()
    conn.close()
    assert row[0] == "wal"


# ---------------------------------------------------------------------------
# 2. load_or_create
# ---------------------------------------------------------------------------


def test_load_or_create_creates_row(tmp_path):
    """load_or_create inserts a call_card row for the session_id."""
    store = _store(tmp_path)
    store.load_or_create("sess-1", "+15550001111")
    card = store.get_call_card("sess-1")
    assert card.get("session_id") == "sess-1"


def test_load_or_create_second_call_idempotent(tmp_path):
    """Second load_or_create with the same session_id is a no-op — no error, row unchanged."""
    store = _store(tmp_path)
    store.load_or_create("sess-1", "+15550001111")
    store.load_or_create("sess-1", "+15550001111")
    card = store.get_call_card("sess-1")
    assert card.get("session_id") == "sess-1"


# ---------------------------------------------------------------------------
# 3. add_fact
# ---------------------------------------------------------------------------


def test_add_fact_persists_and_readable_via_get_call_card(tmp_path):
    """add_fact persists a CapturedFact; it shows up in get_call_card['facts']."""
    store = _store(tmp_path)
    store.load_or_create("sess-1", "+15550001111")
    fact = _fact()
    store.add_fact(fact)
    card = store.get_call_card("sess-1")
    assert len(card["facts"]) == 1
    stored = card["facts"][0]
    assert stored["id"] == fact.id
    assert stored["fact_type"] == fact.fact_type.value


# ---------------------------------------------------------------------------
# 4. add_action_item
# ---------------------------------------------------------------------------


def test_add_action_item_persists_and_readable_via_get_call_card(tmp_path):
    """add_action_item persists an ActionItem; it shows up in get_call_card['action_items']."""
    store = _store(tmp_path)
    store.load_or_create("sess-1", "+15550001111")
    item = _action_item()
    store.add_action_item(item)
    card = store.get_call_card("sess-1")
    assert len(card["action_items"]) == 1
    stored = card["action_items"][0]
    assert stored["id"] == item.id
    assert stored["description"] == item.description


# ---------------------------------------------------------------------------
# 5. confirm_fact
# ---------------------------------------------------------------------------


def test_confirm_fact_updates_confirmed_and_normalized_value(tmp_path):
    """confirm_fact(fact_id, True, new_value) sets confirmed=1 and normalized_value."""
    store = _store(tmp_path)
    store.load_or_create("sess-1", "+15550001111")
    fact = _fact()
    store.add_fact(fact)
    store.confirm_fact(fact.id, True, "415-555-1234")
    stored = store.get_call_card("sess-1")["facts"][0]
    assert stored["confirmed"] == 1
    assert stored["normalized_value"] == "415-555-1234"


def test_confirm_fact_without_normalized_value_preserves_existing(tmp_path):
    """confirm_fact with no normalized_value only updates the confirmed flag."""
    store = _store(tmp_path)
    store.load_or_create("sess-1", "+15550001111")
    fact = _fact()
    original_value = fact.normalized_value
    store.add_fact(fact)
    store.confirm_fact(fact.id, True)
    stored = store.get_call_card("sess-1")["facts"][0]
    assert stored["confirmed"] == 1
    assert stored["normalized_value"] == original_value


# ---------------------------------------------------------------------------
# 6. mark_ended
# ---------------------------------------------------------------------------


def test_mark_ended_updates_ended_at(tmp_path):
    """mark_ended sets ended_at to a positive timestamp (was NULL before)."""
    store = _store(tmp_path)
    store.load_or_create("sess-1", "+15550001111")
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    before = conn.execute(
        "SELECT ended_at FROM call_cards WHERE session_id='sess-1'"
    ).fetchone()[0]
    conn.close()
    assert before is None

    store.mark_ended("sess-1")

    conn = sqlite3.connect(str(tmp_path / "test.db"))
    after = conn.execute(
        "SELECT ended_at FROM call_cards WHERE session_id='sess-1'"
    ).fetchone()[0]
    conn.close()
    assert after is not None
    assert after > 0


# ---------------------------------------------------------------------------
# 7. mark_disclosure_ack
# ---------------------------------------------------------------------------


def test_mark_disclosure_ack_sets_flag(tmp_path):
    """mark_disclosure_ack flips disclosure_ack to True in get_call_card."""
    store = _store(tmp_path)
    store.load_or_create("sess-1", "+15550001111")
    assert store.get_call_card("sess-1")["disclosure_ack"] is False

    store.mark_disclosure_ack("sess-1")
    assert store.get_call_card("sess-1")["disclosure_ack"] is True


# ---------------------------------------------------------------------------
# 8. mark_enrichment_done
# ---------------------------------------------------------------------------


def test_mark_enrichment_done_defaults_to_success(tmp_path):
    """mark_enrichment_done() (no status arg) sets enrichment_done=1 (success)."""
    store = _store(tmp_path)
    store.load_or_create("sess-1", "+15550001111")
    assert store.get_call_card("sess-1")["enrichment_done"] == 0

    store.mark_enrichment_done("sess-1")
    assert store.get_call_card("sess-1")["enrichment_done"] == 1


def test_mark_enrichment_done_failure_status(tmp_path):
    """mark_enrichment_done(status=2) records failure status."""
    store = _store(tmp_path)
    store.load_or_create("sess-1", "+15550001111")
    store.mark_enrichment_done("sess-1", status=2)
    assert store.get_call_card("sess-1")["enrichment_done"] == 2


# ---------------------------------------------------------------------------
# 9. get_call_card
# ---------------------------------------------------------------------------


def test_get_call_card_returns_empty_dict_for_unknown_session(tmp_path):
    """get_call_card for an unknown session_id returns an empty dict (not raises)."""
    store = _store(tmp_path)
    result = store.get_call_card("nonexistent")
    assert result == {}


def test_get_call_card_includes_facts_and_action_items(tmp_path):
    """get_call_card returns both facts and action_items lists."""
    store = _store(tmp_path)
    store.load_or_create("sess-1", "+15550001111")
    store.add_fact(_fact())
    store.add_action_item(_action_item())
    card = store.get_call_card("sess-1")
    assert len(card["facts"]) == 1
    assert len(card["action_items"]) == 1


# ---------------------------------------------------------------------------
# 10. Thread safety (smoke test)
# ---------------------------------------------------------------------------


def test_concurrent_add_fact_does_not_corrupt(tmp_path):
    """Concurrent add_fact calls from multiple threads all persist without error."""
    store = _store(tmp_path)
    store.load_or_create("sess-t", "+15550001111")
    errors: list[Exception] = []

    def _worker():
        try:
            store.add_fact(_fact(session_id="sess-t"))
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=_worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Thread errors: {errors}"
    card = store.get_call_card("sess-t")
    assert len(card["facts"]) == 10
