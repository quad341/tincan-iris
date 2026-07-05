"""Tests for CallCardHost — disclosure_ack/disclosure_skip hard-gate (ti-ir12t)
and _disclosure_script config wiring (ti-ajkht).

CaptureSession is mocked at the call_card_host module boundary so the hard-gate
tests isolate CallCardHost's own orchestration (store state + whether far-party
capture starts). The _disclosure_script tests construct CallCardHost directly —
no CaptureSession mocking needed since _disclosure_script never touches capture.
"""
from __future__ import annotations

import base64
import gzip
import json
import logging
import sqlite3
import sys
from unittest.mock import MagicMock, patch

import nacl.public

from iris.daemon.call_card_host import _DEFAULT_DISCLOSURE, CallCardHost


def _make_host():
    store = MagicMock()
    processor = MagicMock()
    api = MagicMock()
    cfg = MagicMock()
    cfg.eval_log_public_key = ""  # fail-closed default; MagicMock would otherwise auto-vivify truthy
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
# eval log: write-only encrypted STT archive (ti-qi76c / ti-x46ji)
#
# CallCardHost.stop_session() constructs a real EvalLogStore() (default
# constructor, no path arg) -- _DEFAULT_PATH is monkeypatched to a tmp file so
# these tests never touch ~/.local/share/iris/eval_log.db. CaptureSession is
# mocked per this file's convention; TranscriptStore is real (never mocked)
# so turns can be appended and the resulting sealed blob independently
# decrypted afterward. PostCallEnricher/PostCallRecapGenerator are mocked (or
# their import poisoned) in every test below so eval-log coverage never
# depends on incidental real L3-thread behavior.
# ---------------------------------------------------------------------------

def _eval_log_db_path(monkeypatch, tmp_path):
    db_path = tmp_path / "eval_log.db"
    monkeypatch.setattr("iris.capture.eval_log_store._DEFAULT_PATH", db_path)
    return db_path


@patch("iris.capture.recap.PostCallRecapGenerator")
@patch("iris.capture.enricher.PostCallEnricher")
@patch("iris.daemon.call_card_host.CaptureSession")
def test_stop_session_eval_log_noop_when_no_public_key_configured(
    mock_session_cls, _mock_enricher_cls, _mock_recap_cls, monkeypatch, tmp_path, caplog,
):
    db_path = _eval_log_db_path(monkeypatch, tmp_path)
    host = _make_host_with_cfg(MagicMock(eval_log_public_key=""))

    with caplog.at_level(logging.DEBUG, logger="iris.daemon.call_card_host"):
        host.start_session("s1", "+15550000")
        host.stop_session("s1")

    assert not db_path.exists(), "no key configured -- EvalLogStore must never be constructed"
    assert any("no eval_log_public_key configured" in r.getMessage() for r in caplog.records)


@patch("iris.capture.recap.PostCallRecapGenerator")
@patch("iris.capture.enricher.PostCallEnricher")
@patch("iris.daemon.call_card_host.CaptureSession")
def test_stop_session_eval_log_writes_exactly_one_row_when_key_configured(
    mock_session_cls, _mock_enricher_cls, _mock_recap_cls, monkeypatch, tmp_path,
):
    db_path = _eval_log_db_path(monkeypatch, tmp_path)
    private_key = nacl.public.PrivateKey.generate()
    public_key_b64 = base64.b64encode(bytes(private_key.public_key)).decode()
    host = _make_host_with_cfg(MagicMock(eval_log_public_key=public_key_b64))

    host.start_session("s1", "+15550000")
    host._session_transcript.append("hello", "operator", 0.0)
    host._session_transcript.append("hi there", "far", 1.5)
    host.stop_session("s1")

    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        "SELECT session_id, key_version, sealed_blob FROM eval_log_entries"
    ).fetchall()
    assert len(rows) == 1
    session_id, key_version, sealed_blob = rows[0]
    assert session_id == "s1"
    assert key_version == 1

    recovered = gzip.decompress(nacl.public.SealedBox(private_key).decrypt(sealed_blob))
    turns = json.loads(recovered)
    assert [t["text"] for t in turns] == ["hello", "hi there"]


@patch("iris.capture.recap.PostCallRecapGenerator")
@patch("iris.capture.enricher.PostCallEnricher")
@patch("iris.daemon.call_card_host.CaptureSession")
def test_stop_session_eval_log_writes_even_when_call_card_llm_disabled(
    mock_session_cls, _mock_enricher_cls, _mock_recap_cls, monkeypatch, tmp_path,
):
    """The eval log has its own independent gate (cfg.eval_log_public_key) --
    it must not also be tied to the L3 enrichment feature flag."""
    db_path = _eval_log_db_path(monkeypatch, tmp_path)
    private_key = nacl.public.PrivateKey.generate()
    public_key_b64 = base64.b64encode(bytes(private_key.public_key)).decode()
    cfg = MagicMock(eval_log_public_key=public_key_b64, call_card_llm_enabled=False)
    host = _make_host_with_cfg(cfg)

    host.start_session("s1", "+15550000")
    host.stop_session("s1")

    conn = sqlite3.connect(str(db_path))
    count = conn.execute("SELECT COUNT(*) FROM eval_log_entries").fetchone()[0]
    assert count == 1


@patch("iris.daemon.call_card_host.CaptureSession")
def test_stop_session_eval_log_writes_even_when_call_card_llm_extra_missing(
    mock_session_cls, monkeypatch, tmp_path,
):
    """Structural regression guard: the eval-log block sits BEFORE the L3
    enrichment import in stop_session() specifically so a missing/broken
    call-card LLM extra (pydantic) can never silently also skip eval logging.
    Poisoning the enricher/recap import (rather than mocking the classes)
    proves the ordering, not just the config flag."""
    db_path = _eval_log_db_path(monkeypatch, tmp_path)
    private_key = nacl.public.PrivateKey.generate()
    public_key_b64 = base64.b64encode(bytes(private_key.public_key)).decode()
    host = _make_host_with_cfg(MagicMock(eval_log_public_key=public_key_b64))
    host.start_session("s1", "+15550000")

    with patch.dict(sys.modules, {"iris.capture.enricher": None, "iris.capture.recap": None}):
        host.stop_session("s1")

    conn = sqlite3.connect(str(db_path))
    count = conn.execute("SELECT COUNT(*) FROM eval_log_entries").fetchone()[0]
    assert count == 1


@patch("iris.capture.recap.PostCallRecapGenerator")
@patch("iris.capture.enricher.PostCallEnricher")
@patch("iris.daemon.call_card_host.CaptureSession")
def test_stop_session_eval_log_missing_pynacl_logs_warning_and_does_not_raise(
    mock_session_cls, _mock_enricher_cls, _mock_recap_cls, monkeypatch, tmp_path, caplog,
):
    db_path = _eval_log_db_path(monkeypatch, tmp_path)
    public_key_b64 = base64.b64encode(bytes(32)).decode()
    host = _make_host_with_cfg(MagicMock(eval_log_public_key=public_key_b64))
    host.start_session("s1", "+15550000")

    with patch.dict(sys.modules, {"nacl.public": None}), \
         caplog.at_level(logging.WARNING, logger="iris.daemon.call_card_host"):
        host.stop_session("s1")  # must not raise

    assert not db_path.exists()
    assert any("PyNaCl not installed" in r.getMessage() for r in caplog.records)
