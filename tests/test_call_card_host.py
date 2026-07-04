"""Tests for CallCardHost.disclosure_ack / disclosure_skip (ti-ir12t hard-gate).

CaptureSession is mocked at the call_card_host module boundary (same technique
as test_daemon_api_cc.py mocking call_card_host itself one layer up) so these
tests isolate CallCardHost's own orchestration: does it write the right store
state, and does it start far-party capture only when it's supposed to.
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

from iris.daemon.call_card_host import CallCardHost


def _make_host():
    store = MagicMock()
    processor = MagicMock()
    api = MagicMock()
    cfg = MagicMock()
    return CallCardHost(store=store, processor=processor, api=api, cfg=cfg), store, api


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
