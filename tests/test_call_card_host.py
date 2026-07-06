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

from iris.daemon.call_card_host import _DEFAULT_DISCLOSURE, CallCardHost


def _make_host():
    store = MagicMock()
    store.get_call_card.return_value = {"disclosure_state": "pending"}
    processor = MagicMock()
    api = MagicMock()
    cfg = MagicMock()
    tts = MagicMock()
    return CallCardHost(store=store, processor=processor, api=api, cfg=cfg, tts=tts), store, api


def _make_host_with_cfg(cfg):
    return CallCardHost(
        store=MagicMock(), processor=MagicMock(), api=MagicMock(), cfg=cfg, tts=MagicMock(),
    )


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
# disclosure_skip -- active-session guard (ti-429tt consent-integrity fix).
#
# self._announce_proc is a single instance-level slot, not keyed by
# session_id -- a delayed skip for a call that has already ended must not
# touch whatever the *new* active call has since registered there, nor tell
# clients that call's card was skipped (ti-429tt adjudication, ti-fjsmz
# finding 1).
# ---------------------------------------------------------------------------

@patch("iris.daemon.call_card_host.CaptureSession")
def test_disclosure_skip_stale_session_id_does_not_touch_announce_proc_or_broadcast(
    mock_session_cls,
):
    host, store, api = _make_host()
    host.start_session("A", "+15550000")
    # Simulate call B becoming active without properly ending A in the mock
    # (matches how test_empty_id_resolves_to_active_session_for_ack_and_stop
    # already manipulates state).
    host._session_id = "B"
    fake_proc = MagicMock()
    host._announce_proc = fake_proc  # B's own in-flight auto-disclose handle

    host.disclosure_skip("A")  # a delayed skip for the call that's no longer active

    store.mark_disclosure_skipped.assert_called_once_with("A")  # store write still happens
    fake_proc.stop.assert_not_called()
    skipped = [c.args[0] for c in api.broadcast.call_args_list
               if c.args[0].get("event") == "call_card_skipped"]
    assert skipped == []


@patch("iris.daemon.call_card_host.CaptureSession")
def test_disclosure_skip_active_session_stops_announce_proc_and_broadcasts(
    mock_session_cls,
):
    # Contrast with the stale-session case above: when the skip's session_id
    # IS the active one, the in-flight handle is stopped and clients are told.
    host, store, api = _make_host()
    host.start_session("s1", "+15550000")
    fake_proc = MagicMock()
    host._announce_proc = fake_proc

    host.disclosure_skip("s1")

    fake_proc.stop.assert_called_once_with()
    skipped = [c.args[0] for c in api.broadcast.call_args_list
               if c.args[0].get("event") == "call_card_skipped"]
    assert skipped and skipped[0]["session_id"] == "s1"


# ---------------------------------------------------------------------------
# stop_session -- clearing/stopping self._announce_proc (ti-429tt). A call can
# end mid-disclosure (hangup before the auto-disclose TTS finishes); the
# in-flight handle must be stopped rather than left to keep playing to a dead
# call (ti-429tt adjudication, ti-fjsmz finding 1).
# ---------------------------------------------------------------------------

@patch("iris.capture.enricher.PostCallEnricher")
@patch("iris.daemon.call_card_host.CaptureSession")
def test_stop_session_stops_in_flight_announce_proc(mock_session_cls, _mock_enricher_cls):
    host, store, _api = _make_host()
    host.start_session("s1", "+15550000")
    fake_proc = MagicMock()
    host._announce_proc = fake_proc  # simulates an in-flight auto-disclose TTS handle

    host.stop_session("s1")

    fake_proc.stop.assert_called_once_with()
    assert host._announce_proc is None


@patch("iris.capture.enricher.PostCallEnricher")
@patch("iris.daemon.call_card_host.CaptureSession")
def test_stop_session_with_no_in_flight_announce_does_not_raise(
    mock_session_cls, _mock_enricher_cls,
):
    host, store, _api = _make_host()
    host.start_session("s1", "+15550000")
    assert host._announce_proc is None  # nothing in flight

    host.stop_session("s1")  # must not unconditionally call .stop() on None

    assert host._announce_proc is None


# ---------------------------------------------------------------------------
# _run_auto_disclose -- a handle cut short (stopped=True) must never advance
# to disclosure_ack; only a natural completion does (ti-429tt adjudication,
# ti-fjsmz finding 1).
# ---------------------------------------------------------------------------

@patch("iris.daemon.call_card_host._cached_disclosure_wav", return_value="/tmp/fake-disclosure.wav")
@patch("iris.daemon.call_card_host.TincanSCOAudio")
@patch("iris.daemon.call_card_host.discover_sco_nodes", return_value=("sink1", "source1"))
def test_run_auto_disclose_stopped_handle_does_not_call_disclosure_ack(
    _mock_discover, mock_sco_cls, _mock_wav,
):
    host, _store, _api = _make_host()
    host._session_id = "s1"  # active session -- no CaptureSession needed for this unit

    handle = MagicMock()
    handle.stopped = False

    def _wait_side_effect():
        handle.stopped = True  # disclosure_skip()/stop_session() cut the TTS short mid-wait

    handle.wait.side_effect = _wait_side_effect
    mock_sco_cls.return_value.start_playback.return_value = handle

    with patch.object(host, "disclosure_ack") as mock_ack:
        host._run_auto_disclose("s1")

    mock_ack.assert_not_called()
    assert host._announce_proc is None  # cleared in the finally block regardless of outcome


@patch("iris.daemon.call_card_host._cached_disclosure_wav", return_value="/tmp/fake-disclosure.wav")
@patch("iris.daemon.call_card_host.TincanSCOAudio")
@patch("iris.daemon.call_card_host.discover_sco_nodes", return_value=("sink1", "source1"))
def test_run_auto_disclose_completed_handle_calls_disclosure_ack(
    _mock_discover, mock_sco_cls, _mock_wav,
):
    # Contrast with the stopped-handle case above: wait() returns because
    # playback finished naturally, stopped stays False, so disclosure_ack fires.
    host, _store, _api = _make_host()
    host._session_id = "s1"

    handle = MagicMock()
    handle.stopped = False
    mock_sco_cls.return_value.start_playback.return_value = handle

    with patch.object(host, "disclosure_ack") as mock_ack:
        host._run_auto_disclose("s1")

    mock_ack.assert_called_once_with("s1")


# ---------------------------------------------------------------------------
# End-to-end: the ti-fjsmz/ti-429tt failure sequence -- call A ends
# mid-disclosure, call B starts and registers its own handle, then a delayed
# disclosure_skip("A") arrives late. B's handle must be untouched and B's own
# disclosure_ack path must still complete normally when B's playback finishes.
# ---------------------------------------------------------------------------

@patch("iris.capture.enricher.PostCallEnricher")
@patch("iris.daemon.call_card_host.CaptureSession")
def test_end_to_end_stale_skip_after_call_rollover_does_not_disrupt_next_calls_disclosure(
    mock_session_cls, _mock_enricher_cls, monkeypatch,
):
    host, store, api = _make_host()
    mock_session_cls.return_value = MagicMock()
    # Auto-disclose is driven explicitly below (simulating the in-flight handle
    # a background thread would otherwise register) -- no real thread needed.
    monkeypatch.setattr(host, "_auto_disclose", lambda session_id: None)

    # Call A starts; its auto-disclose handle is still "in flight" when it ends.
    host.start_session("A", "+15550000")
    handle_a = MagicMock()
    handle_a.stopped = False
    host._announce_proc = handle_a
    host.stop_session("A")
    handle_a.stop.assert_called_once_with()

    # Call B starts and registers its OWN in-flight handle.
    host.start_session("B", "+15550001")
    handle_b = MagicMock()
    handle_b.stopped = False
    host._announce_proc = handle_b

    # A's disclosure_skip arrives late -- after A ended and B became active.
    host.disclosure_skip("A")

    handle_b.stop.assert_not_called()
    skipped = [c.args[0] for c in api.broadcast.call_args_list
               if c.args[0].get("event") == "call_card_skipped"]
    assert skipped == []

    # B's own auto-disclose then completes naturally and its disclosure_ack fires.
    with patch("iris.daemon.call_card_host.discover_sco_nodes", return_value=("sink1", "source1")), \
         patch("iris.daemon.call_card_host.TincanSCOAudio") as mock_sco_cls, \
         patch("iris.daemon.call_card_host._cached_disclosure_wav", return_value="/tmp/fake.wav"):
        mock_sco_cls.return_value.start_playback.return_value = handle_b
        host._run_auto_disclose("B")

    mock_session_cls.return_value.start_far.assert_called_once_with()
    store.mark_disclosure_ack.assert_called_once_with("B")
