"""Tests for CallCardHost — disclosure_ack/disclosure_skip hard-gate (ti-ir12t)
and _disclosure_script config wiring (ti-ajkht).

CaptureSession is mocked at the call_card_host module boundary so the hard-gate
tests isolate CallCardHost's own orchestration (store state + whether far-party
capture starts). The _disclosure_script tests construct CallCardHost directly —
no CaptureSession mocking needed since _disclosure_script never touches capture.
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

from iris.capture.schemas import ActionItem, CapturedFact, FactType
from iris.daemon.call_card_host import _DEFAULT_DISCLOSURE, CallCardHost
from iris.daemon.engine import HandlingEngine
from iris.daemon.policy import PolicyResolver, ResolveResult
from iris.roster import Contact


def _make_host():
    store = MagicMock()
    processor = MagicMock()
    api = MagicMock()
    cfg = MagicMock()
    return CallCardHost(store=store, processor=processor, api=api, cfg=cfg), store, api


def _make_host_with_cfg(cfg):
    return CallCardHost(store=MagicMock(), processor=MagicMock(), api=MagicMock(), cfg=cfg)


# ---------------------------------------------------------------------------
# disclosure_ack
# ---------------------------------------------------------------------------

@patch("iris.daemon.call_card_host.CaptureSession")
def test_disclosure_ack_starts_far_for_active_session(mock_session_cls):
    host, store, _api = _make_host()
    session_mock = MagicMock()
    mock_session_cls.return_value = session_mock

    host.start_session("s1", "+15550000")
    host.disclosure_ack("s1")

    store.mark_disclosure_ack.assert_called_once_with("s1")
    session_mock.start_far.assert_called_once_with()


@patch("iris.daemon.call_card_host.CaptureSession")
def test_disclosure_ack_mismatched_session_is_noop_for_far_but_still_writes_store(
    mock_session_cls, caplog,
):
    host, store, _api = _make_host()
    session_mock = MagicMock()
    mock_session_cls.return_value = session_mock

    host.start_session("s1", "+15550000")
    with caplog.at_level(logging.WARNING, logger="iris.daemon.call_card_host"):
        host.disclosure_ack("stale-session")

    # Store write happens regardless -- the ack itself is real, only the
    # far-capture side-effect is gated on the session still being current.
    store.mark_disclosure_ack.assert_called_once_with("stale-session")
    session_mock.start_far.assert_not_called()
    assert any("stale-session" in r.getMessage() for r in caplog.records)


@patch("iris.daemon.call_card_host.CaptureSession")
def test_disclosure_ack_no_active_session_is_noop(mock_session_cls, caplog):
    host, store, _api = _make_host()

    with caplog.at_level(logging.WARNING, logger="iris.daemon.call_card_host"):
        host.disclosure_ack("s1")  # no start_session() call at all

    store.mark_disclosure_ack.assert_called_once_with("s1")
    assert caplog.records


# ---------------------------------------------------------------------------
# disclosure_ack -- TOCTOU corrective fix (ti-s6kz3 Finding 1, commit 546212f)
#
# session.start_far() runs outside the lock, so a concurrent stop_session()
# for the same session can tear it down while start_far() is still in
# flight. The fix re-validates session identity after start_far() returns
# and stops the orphaned session correctively if it was superseded.
# ---------------------------------------------------------------------------

@patch("iris.capture.enricher.PostCallEnricher")
@patch("iris.daemon.call_card_host.CaptureSession")
def test_disclosure_ack_race_during_start_far_stops_orphaned_session(
    mock_session_cls, _mock_enricher_cls, caplog,
):
    host, _store, _api = _make_host()
    session_mock = MagicMock()
    mock_session_cls.return_value = session_mock

    def _concurrent_teardown():
        # A different thread's stop_session() interleaves while this
        # start_far() call (still running on the disclosure_ack thread) is
        # in flight -- the exact window 546212f closes.
        host.stop_session("s1")
        session_mock.stop.reset_mock()  # isolate disclosure_ack's own corrective call

    session_mock.start_far.side_effect = _concurrent_teardown

    host.start_session("s1", "+15550000")
    with caplog.at_level(logging.WARNING, logger="iris.daemon.call_card_host"):
        host.disclosure_ack("s1")

    session_mock.stop.assert_called_once_with()
    assert host._session is None
    assert any(
        "torn down while starting far capture" in r.getMessage() for r in caplog.records
    )


@patch("iris.daemon.call_card_host.CaptureSession")
def test_disclosure_ack_no_race_does_not_spuriously_stop(mock_session_cls):
    host, _store, _api = _make_host()
    session_mock = MagicMock()
    mock_session_cls.return_value = session_mock

    host.start_session("s1", "+15550000")
    host.disclosure_ack("s1")

    session_mock.start_far.assert_called_once_with()
    session_mock.stop.assert_not_called()
    assert host._session is session_mock


@patch("iris.capture.enricher.PostCallEnricher")
@patch("iris.daemon.call_card_host.CaptureSession")
def test_disclosure_ack_then_later_stop_session_does_not_double_stop(
    mock_session_cls, _mock_enricher_cls,
):
    host, _store, _api = _make_host()
    session_mock = MagicMock()
    mock_session_cls.return_value = session_mock

    host.start_session("s1", "+15550000")
    host.disclosure_ack("s1")  # completes cleanly, no interleaving
    session_mock.stop.assert_not_called()

    host.stop_session("s1")  # legitimate teardown, strictly after ack returns

    session_mock.stop.assert_called_once_with()


# ---------------------------------------------------------------------------
# disclosure_skip
# ---------------------------------------------------------------------------

@patch("iris.daemon.call_card_host.CaptureSession")
def test_disclosure_skip_never_calls_start_far(mock_session_cls):
    host, store, _api = _make_host()
    session_mock = MagicMock()
    mock_session_cls.return_value = session_mock

    host.start_session("s1", "+15550000")
    host.disclosure_skip("s1")

    store.mark_disclosure_skipped.assert_called_once_with("s1")
    session_mock.start_far.assert_not_called()


@patch("iris.daemon.call_card_host.CaptureSession")
def test_disclosure_skip_with_no_active_session_still_writes_store(mock_session_cls):
    host, store, _api = _make_host()

    host.disclosure_skip("s1")  # no start_session() call at all -- must not raise

    store.mark_disclosure_skipped.assert_called_once_with("s1")


# ---------------------------------------------------------------------------
# _disclosure_script (ti-ajkht config wiring)
# ---------------------------------------------------------------------------

def test_disclosure_script_reflects_nonempty_cfg_value():
    cfg = MagicMock(call_card_disclosure_script="Please note this call is recorded.")
    host = _make_host_with_cfg(cfg)
    assert host._disclosure_script == "Please note this call is recorded."


def test_disclosure_script_falls_back_to_default_when_cfg_value_empty():
    cfg = MagicMock(call_card_disclosure_script="")
    host = _make_host_with_cfg(cfg)
    assert host._disclosure_script == _DEFAULT_DISCLOSURE


def test_disclosure_script_falls_back_to_default_when_cfg_lacks_attribute():
    host = _make_host_with_cfg(object())  # no call_card_disclosure_script attribute
    assert host._disclosure_script == _DEFAULT_DISCLOSURE


def test_disclosure_script_falls_back_to_default_when_cfg_is_none():
    host = _make_host_with_cfg(None)
    assert host._disclosure_script == _DEFAULT_DISCLOSURE


# ---------------------------------------------------------------------------
# Empty call id from tincand (ti-wunrs live finding, 2026-07-04)
# ---------------------------------------------------------------------------

@patch("iris.daemon.call_card_host.CaptureSession")
def test_start_session_mints_id_when_tincand_gives_none(mock_session_cls):
    """tincand's CallConnected carries no call id (tincan-xbtct gap): outbound
    calls arrive with session_id="". The host must mint a real id — an empty id
    broke every downstream ack (the API rejects disclosure_ack without one), so
    the far channel could never start (found live, 2026-07-04)."""
    host, store, api = _make_host()
    host.start_session("", "+18155550100")
    started = [c.args[0] for c in api.broadcast.call_args_list
               if c.args[0].get("event") == "call_card_started"]
    assert started and started[0]["session_id"], "broadcast must carry a minted id"
    assert host._session_id, "host must track the minted id"


@patch("iris.daemon.call_card_host.CaptureSession")
def test_empty_id_resolves_to_active_session_for_ack_and_stop(mock_session_cls):
    """disclosure_ack('') and stop_session('') act on the active session — the
    CallEnded signal carries no id either."""
    host, store, api = _make_host()
    host.start_session("", "+18155550100")
    minted = host._session_id
    host.disclosure_ack("")
    mock_session_cls.return_value.start_far.assert_called_once()
    host.stop_session("")
    assert host._session is None
    ended = [c.args[0] for c in api.broadcast.call_args_list
             if c.args[0].get("event") == "call_card_ended"]
    assert ended and ended[0]["session_id"] == minted


# ---------------------------------------------------------------------------
# start_session / stop_session broadcast contract (ti-rnlqo.3.4)
#
# Carried forward from gc-validator-f7bde7842f0c commit dbb7480, updated for
# the current CallCardHost API: transcript_store is now created internally
# (no longer a constructor param) and start_session gained contact_id.
# ---------------------------------------------------------------------------

def _make_fact(session_id="sess-1"):
    return CapturedFact(
        session_id=session_id,
        fact_type=FactType.PHONE,
        raw_text="call me at 415-555-1234",
        normalized_value="+14155551234",
        transcript_turn_id=1,
        transcript_offset_s=10.0,
        speaker="far",
        confidence=0.9,
        critical=True,
    )


def _make_action_item(session_id="sess-1"):
    return ActionItem(
        session_id=session_id,
        description="I'll call you back",
        trigger="I'll",
        owner="operator",
        transcript_turn_id=2,
        transcript_offset_s=20.0,
        speaker="operator",
        confidence=0.85,
    )


def _broadcast_events(api):
    return [c.args[0] for c in api.broadcast.call_args_list]


@patch("iris.daemon.call_card_host.CaptureSession")
def test_start_session_broadcasts_started_and_disclosure_needed(mock_session_cls):
    host, _store, api = _make_host()
    mock_session_cls.return_value = MagicMock()
    host.start_session("sess-1", "+15550001111")

    names = [e.get("event") for e in _broadcast_events(api)]
    assert "call_card_started" in names
    assert "call_card_disclosure_needed" in names
    assert names.index("call_card_started") < names.index("call_card_disclosure_needed"), (
        "call_card_started must precede call_card_disclosure_needed"
    )


@patch("iris.daemon.call_card_host.CaptureSession")
def test_start_session_started_event_carries_session_id(mock_session_cls):
    host, _store, api = _make_host()
    mock_session_cls.return_value = MagicMock()
    host.start_session("sess-1", "+15550001111")

    started = next(e for e in _broadcast_events(api) if e.get("event") == "call_card_started")
    assert started["session_id"] == "sess-1"


@patch("iris.daemon.call_card_host.CaptureSession")
def test_start_session_disclosure_event_includes_script(mock_session_cls):
    host, _store, api = _make_host()
    mock_session_cls.return_value = MagicMock()
    host.start_session("sess-1", "+15550001111")

    disclosure = next(
        e for e in _broadcast_events(api) if e.get("event") == "call_card_disclosure_needed"
    )
    assert disclosure["session_id"] == "sess-1"
    assert disclosure.get("script")


@patch("iris.daemon.call_card_host.CaptureSession")
def test_start_session_reentrancy_guard_no_double_broadcast(mock_session_cls):
    host, _store, api = _make_host()
    mock_session_cls.return_value = MagicMock()
    host.start_session("sess-1", "+15550001111")
    first_count = api.broadcast.call_count
    host.start_session("sess-1", "+15550001111")  # same session_id, still active
    assert api.broadcast.call_count == first_count, (
        "Second start_session while active must not broadcast additional events"
    )


@patch("iris.capture.enricher.PostCallEnricher")
@patch("iris.daemon.call_card_host.CaptureSession")
def test_stop_session_broadcasts_call_card_ended(mock_session_cls, _mock_enricher_cls):
    host, _store, api = _make_host()
    mock_session_cls.return_value = MagicMock()
    host.start_session("sess-1", "+15550001111")
    host._on_fact(_make_fact())
    host._on_action_item(_make_action_item())
    host._on_fact(_make_fact())

    api.broadcast.reset_mock()
    host.stop_session("sess-1")

    ended = next(
        (e for e in _broadcast_events(api) if e.get("event") == "call_card_ended"), None
    )
    assert ended is not None, "call_card_ended not broadcast"
    assert ended["session_id"] == "sess-1"
    assert ended["fact_count"] == 2
    assert ended["action_item_count"] == 1


def test_on_fact_broadcasts_call_card_fact():
    host, _store, api = _make_host()
    fact = _make_fact()
    host._on_fact(fact)

    fact_events = [e for e in _broadcast_events(api) if e.get("event") == "call_card_fact"]
    assert len(fact_events) == 1
    assert fact_events[0]["session_id"] == fact.session_id
    assert fact_events[0]["fact"]["id"] == fact.id


def test_on_action_item_broadcasts_call_card_action_item():
    host, _store, api = _make_host()
    item = _make_action_item()
    host._on_action_item(item)

    ai_events = [e for e in _broadcast_events(api) if e.get("event") == "call_card_action_item"]
    assert len(ai_events) == 1
    assert ai_events[0]["session_id"] == item.session_id
    assert ai_events[0]["item"]["id"] == item.id


# ---------------------------------------------------------------------------
# HandlingEngine wiring: on_call_connected -> call_card_host.start_session
# (ti-rnlqo.3.4). on_call_connected now takes only call_id -- caller_number
# and contact_id come from _pending_contact, set by a prior on_incoming_call.
# ---------------------------------------------------------------------------

def _contact(*, id=42, display_name="Alice", phone_e164="+15550001111", handling_rule="screen"):
    return Contact(
        id=id,
        display_name=display_name,
        phone_e164=phone_e164,
        handling_rule=handling_rule,
        trust_tier="demo",
        relationship_notes="",
        created_at=0.0,
        updated_at=0.0,
    )


def _mock_resolver(contact=None, verb="screen"):
    resolver = MagicMock(spec=PolicyResolver)
    resolver.resolve.return_value = ResolveResult(
        verb=verb,
        contact=contact,
        event={
            "event": "incoming_call",
            "call_id": "call-123",
            "caller_name": contact.display_name if contact else "",
            "caller_number": contact.phone_e164 if contact else "+15550001111",
            "verb": verb,
            "choices": [],
        },
    )
    return resolver


def _make_engine(*, call_card_host=None, contact=None):
    c = _contact() if contact is None else contact
    return HandlingEngine(
        ctrl=MagicMock(),
        tts=None,
        resolver=_mock_resolver(contact=c),
        notify_sink=MagicMock(),
        broadcast=MagicMock(),
        call_card_host=call_card_host,
    )


def test_on_call_connected_no_host_does_not_raise():
    """HandlingEngine.on_call_connected with call_card_host=None does not raise."""
    engine = _make_engine(call_card_host=None)
    engine.on_incoming_call("+15550001111", call_id="call-123")
    engine.on_call_connected("call-123")  # must not raise


def test_on_call_connected_with_host_calls_start_session():
    """HandlingEngine.on_call_connected calls
    call_card_host.start_session(call_id, caller_number, contact_id)."""
    mock_host = MagicMock()
    contact = _contact(id=7, phone_e164="+15550001111")
    engine = _make_engine(call_card_host=mock_host, contact=contact)
    engine.on_incoming_call("+15550001111", call_id="call-123")
    engine.on_call_connected("call-123")
    mock_host.start_session.assert_called_once_with("call-123", "+15550001111", 7)
