"""Unit tests for CallCardStore (ti-rnlqo.3.1)."""
from __future__ import annotations

import sqlite3
import threading
import time

import pytest

from iris.capture.schemas import ActionItem, CapturedFact, FactType
from iris.capture.store import CallCardStore


@pytest.fixture
def store():
    return CallCardStore(":memory:")


def _fact(session_id: str, fact_id: str = "f1") -> CapturedFact:
    return CapturedFact(
        id=fact_id,
        session_id=session_id,
        fact_type=FactType.PHONE,
        raw_text="555-0100",
        normalized_value="+15550100",
        critical=True,
        confidence=0.95,
        confirmed=None,
        transcript_turn_id=1,
        transcript_offset_s=1.0,
        speaker="far",
    )


def _action(session_id: str, item_id: str = "a1") -> ActionItem:
    return ActionItem(
        id=item_id,
        session_id=session_id,
        description="Call back tomorrow",
        trigger="I will",
        owner="operator",
        due_date=None,
        confidence=0.8,
        confirmed=None,
        transcript_turn_id=2,
        transcript_offset_s=5.0,
        speaker="operator",
    )


def test_load_or_create_creates_row(store):
    store.load_or_create("sess-1", "+15550000")
    card = store.get_call_card("sess-1")
    assert card["session_id"] == "sess-1"


def test_get_call_card_includes_caller_number(store):
    store.load_or_create("sess-1", "+15550000")
    card = store.get_call_card("sess-1")
    assert card["caller_number"] == "+15550000"


def test_load_or_create_idempotent(store):
    store.load_or_create("sess-1", "+15550000")
    store.load_or_create("sess-1", "+15550000")  # must not raise
    card = store.get_call_card("sess-1")
    assert card["session_id"] == "sess-1"


def test_add_fact_and_get_call_card(store):
    store.load_or_create("sess-1", "+15550000")
    store.add_fact(_fact("sess-1"))
    card = store.get_call_card("sess-1")
    assert len(card["facts"]) == 1
    assert card["facts"][0]["id"] == "f1"


def test_confirm_fact(store):
    store.load_or_create("sess-1", "+15550000")
    store.add_fact(_fact("sess-1"))
    store.confirm_fact("f1", confirmed=True, normalized_value="+15550100")
    card = store.get_call_card("sess-1")
    assert card["facts"][0]["confirmed"] == 1


def test_add_action_item_and_get(store):
    store.load_or_create("sess-1", "+15550000")
    store.add_action_item(_action("sess-1"))
    card = store.get_call_card("sess-1")
    assert len(card["action_items"]) == 1
    assert card["action_items"][0]["id"] == "a1"


def test_confirm_action_item(store):
    store.load_or_create("sess-1", "+15550000")
    store.add_action_item(_action("sess-1"))
    store.confirm_action_item("a1", confirmed=True, description="Ring tomorrow", due_date="2026-07-01")
    card = store.get_call_card("sess-1")
    assert card["action_items"][0]["confirmed"] == 1


def test_upsert_enriched_action_item_update_path(store):
    store.load_or_create("sess-1", "+15550000")
    store.add_action_item(_action("sess-1"))  # transcript_turn_id=2, source_layer=1
    store.upsert_enriched_action_item("sess-1", 2, "Ring back", "operator", "2026-07-02", 0.9)
    card = store.get_call_card("sess-1")
    assert card["action_items"][0]["description"] == "Ring back"


def test_upsert_enriched_action_item_insert_path(store):
    store.load_or_create("sess-ins", "+15550000")
    store.upsert_enriched_action_item("sess-ins", 99, "New task", "operator", None, 0.7)
    card = store.get_call_card("sess-ins")
    assert len(card["action_items"]) == 1
    assert card["action_items"][0]["description"] == "New task"


def test_mark_enrichment_done(store):
    store.load_or_create("sess-1", "+15550000")
    store.mark_enrichment_done("sess-1", status=1)
    card = store.get_call_card("sess-1")
    assert card["enrichment_done"] == 1


def test_mark_disclosure_ack(store):
    store.load_or_create("sess-1", "+15550000")
    store.mark_disclosure_ack("sess-1")
    card = store.get_call_card("sess-1")
    assert card["disclosure_ack"] is True
    assert card["disclosure_state"] == "disclosed"


def test_disclosure_state_defaults_to_pending(store):
    store.load_or_create("sess-1", "+15550000")
    card = store.get_call_card("sess-1")
    assert card["disclosure_state"] == "pending"
    assert card["disclosure_ack"] is False


def test_mark_disclosure_skipped(store):
    store.load_or_create("sess-1", "+15550000")
    store.mark_disclosure_skipped("sess-1")
    card = store.get_call_card("sess-1")
    assert card["disclosure_state"] == "skipped"
    # skip is not an ack -- the boolean field stays false, distinct from disclosed.
    assert card["disclosure_ack"] is False


def test_mark_disclosure_ack_then_skipped_last_write_wins(store):
    # Not a realistic call flow (real code only calls one or the other), but pins
    # down that the two writers don't share hidden state beyond the row itself.
    store.load_or_create("sess-1", "+15550000")
    store.mark_disclosure_ack("sess-1")
    store.mark_disclosure_skipped("sess-1")
    card = store.get_call_card("sess-1")
    assert card["disclosure_state"] == "skipped"
    assert card["disclosure_ack"] is True  # mark_disclosure_skipped never clears it


def test_migrate_disclosure_state_backfills_pre_existing_db(tmp_path):
    """A call_cards.db created before ti-ir12t has no disclosure_state column.

    Opening it via CallCardStore must add the column and backfill existing
    disclosure_ack=1 rows to disclosure_state='disclosed', so the two fields
    never disagree after the upgrade.
    """
    db_path = tmp_path / "legacy_call_cards.db"

    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE call_cards (
            session_id        TEXT PRIMARY KEY,
            caller_number     TEXT,
            contact_id        TEXT,
            context_notes     TEXT,
            disclosure_ack    INTEGER DEFAULT 0,
            disclosure_ack_ts REAL,
            enrichment_done   INTEGER DEFAULT 0,
            started_at        REAL,
            ended_at          REAL,
            created_at        REAL NOT NULL
        )
        """
    )
    conn.execute(
        "INSERT INTO call_cards (session_id, caller_number, disclosure_ack, created_at) "
        "VALUES (?, ?, ?, ?)",
        ("legacy-acked", "+15550000", 1, time.time()),
    )
    conn.execute(
        "INSERT INTO call_cards (session_id, caller_number, disclosure_ack, created_at) "
        "VALUES (?, ?, ?, ?)",
        ("legacy-never-acked", "+15550001", 0, time.time()),
    )
    conn.commit()
    conn.close()

    store = CallCardStore(db_path)  # triggers _migrate_disclosure_state() on open

    cols = {r["name"] for r in store._conn.execute("PRAGMA table_info(call_cards)").fetchall()}
    assert "disclosure_state" in cols

    acked = store.get_call_card("legacy-acked")
    assert acked["disclosure_state"] == "disclosed"
    assert acked["disclosure_ack"] is True

    never_acked = store.get_call_card("legacy-never-acked")
    assert never_acked["disclosure_state"] == "pending"
    assert never_acked["disclosure_ack"] is False


def test_thread_safety_concurrent_add_facts(store):
    store.load_or_create("sess-t", "+15550000")
    errors: list[Exception] = []

    def add_facts(offset: int) -> None:
        try:
            for i in range(20):
                store.add_fact(_fact("sess-t", f"f-{offset}-{i}"))
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=add_facts, args=(idx * 100,)) for idx in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    card = store.get_call_card("sess-t")
    assert len(card["facts"]) == 80
