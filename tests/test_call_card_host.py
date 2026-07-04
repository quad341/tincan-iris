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
