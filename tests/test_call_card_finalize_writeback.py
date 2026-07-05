"""Tests for CallCardHost.finalize_writeback — the AFTER writeback orchestration
(ti-hb2dx / ti-05kyj).

AfterStore/NotesStore are mocked at the call_card_host module boundary so these
tests isolate the *orchestration* logic — which card fields become which
AfterStore rows, the confirmed/durable filtering, the far/operator→direction
mapping, and the fail-safe guards. AfterStore's own SQL behaviour is covered
separately in test_after_store.py.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from iris.daemon.call_card_host import CallCardHost


def _make_host():
    store = MagicMock()
    api = MagicMock()
    host = CallCardHost(store=store, processor=MagicMock(), api=api, cfg=MagicMock())
    return host, store, api


def _action_item(**over):
    base = {
        "confirmed": True,
        "owner": "far",
        "description": "send the check",
        "amount": None,
        "due_date": None,
        "transcript_turn_id": 1,
        "transcript_offset_s": 0.0,
    }
    base.update(over)
    return base


def _fact(**over):
    base = {"confirmed": True, "fact_type": "account_id", "normalized_value": "AB-123"}
    base.update(over)
    return base


# --- fail-safe guards -------------------------------------------------------

@patch("iris.daemon.call_card_host.NotesStore")
@patch("iris.daemon.call_card_host.AfterStore")
def test_no_call_card_is_noop(mock_after_cls, _mock_notes):
    host, store, api = _make_host()
    store.get_call_card.return_value = None

    host.finalize_writeback("missing")

    mock_after_cls.assert_not_called()
    store.mark_written_back.assert_not_called()
    api.broadcast.assert_not_called()


@patch("iris.daemon.call_card_host.NotesStore")
@patch("iris.daemon.call_card_host.AfterStore")
def test_no_resolved_contact_skips_writeback(mock_after_cls, _mock_notes):
    """contact_id is None (unregistered number) — AfterStore's NOT NULL FK has
    nowhere to write, so writeback is skipped and written_back stays 0 for a
    clean retry (no rows, no mark, no raise)."""
    host, store, api = _make_host()
    store.get_call_card.return_value = {"contact_id": None}

    host.finalize_writeback("sess-anon")

    mock_after_cls.assert_not_called()
    store.mark_written_back.assert_not_called()
    api.broadcast.assert_not_called()


# --- happy path -------------------------------------------------------------

@patch("iris.daemon.call_card_host.NotesStore")
@patch("iris.daemon.call_card_host.AfterStore")
def test_happy_path_writes_filtered_rows_and_marks(mock_after_cls, mock_notes_cls):
    host, store, api = _make_host()
    after = mock_after_cls.return_value
    after.insert_call_log.return_value = 42
    store.get_call_card.return_value = {
        "contact_id": 7,
        "started_at": 100.0,
        "ended_at": 200.0,
        "disclosure_ack_ts": 150.0,
        "outcome_summary": "resolved",
        "action_items": [
            _action_item(owner="far", description="they send check", amount="$50",
                         due_date="2026-08-01", transcript_turn_id=3, transcript_offset_s=9.0),
            _action_item(owner="operator", description="I call back", transcript_turn_id=4),
            _action_item(confirmed=False, owner="far", description="unconfirmed — skip"),
        ],
        "facts": [
            _fact(fact_type="account_id", normalized_value="AB-123"),   # durable  -> upsert
            _fact(fact_type="name", normalized_value="Pat"),            # non-durable -> skip
            _fact(confirmed=False, fact_type="member_id", normalized_value="M-9"),  # unconfirmed -> skip
        ],
    }

    host.finalize_writeback("sess-x")

    # call_log written once with the card's fields + fixed agent_name.
    after.insert_call_log.assert_called_once_with(
        7, "sess-x", 100.0, 200.0,
        agent_name="iris", disclosed_at=150.0, outcome_summary="resolved",
    )

    # Only the two CONFIRMED action items become commitments; direction maps
    # far -> they_promised, operator -> i_promised.
    assert after.insert_commitment.call_count == 2
    directions = [c.args[2] for c in after.insert_commitment.call_args_list]
    assert directions == ["they_promised", "i_promised"]
    # commitments carry the call_log id returned above.
    assert all(c.args[1] == 42 for c in after.insert_commitment.call_args_list)

    # i_promised also drops a self-note; they_promised does not.
    mock_notes_cls.return_value.capture.assert_called_once_with("I call back")

    # Only the confirmed + durable fact is promoted (name is non-durable,
    # member_id is unconfirmed).
    after.upsert_contact_fact.assert_called_once_with(
        7, "account_id", "AB-123", label="", session_id="sess-x",
    )

    # Marked written-back + broadcast only after every insert succeeded.
    store.mark_written_back.assert_called_once_with("sess-x")
    api.broadcast.assert_called_once()
    event = api.broadcast.call_args.args[0]
    assert event["event"] == "call_card_written_back"
    assert event["session_id"] == "sess-x"
