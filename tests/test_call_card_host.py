"""Tests for CallCardHost — disclosure_ack/disclosure_skip hard-gate (ti-ir12t)
and _disclosure_script config wiring (ti-ajkht).

CaptureSession is mocked at the call_card_host module boundary so the hard-gate
tests isolate CallCardHost's own orchestration (store state + whether far-party
capture starts). The _disclosure_script tests construct CallCardHost directly —
no CaptureSession mocking needed since _disclosure_script never touches capture.
"""
from __future__ import annotations

import hashlib
import logging
from unittest.mock import MagicMock, patch

from iris.daemon.call_card_host import _DEFAULT_DISCLOSURE, CallCardHost, _cached_disclosure_wav


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
# disclosure_ack / disclosure_skip -- new broadcasts + announce_proc (ti-iv69h)
# ---------------------------------------------------------------------------

@patch("iris.daemon.call_card_host.CaptureSession")
def test_disclosure_ack_broadcasts_call_card_disclosed(mock_session_cls):
    host, _store, api = _make_host()
    mock_session_cls.return_value = MagicMock()

    host.start_session("s1", "+15550000")
    host.disclosure_ack("s1")

    api.broadcast.assert_any_call({"event": "call_card_disclosed", "session_id": "s1"})


@patch("iris.daemon.call_card_host.CaptureSession")
def test_disclosure_skip_broadcasts_call_card_skipped(mock_session_cls):
    host, _store, api = _make_host()
    mock_session_cls.return_value = MagicMock()

    host.start_session("s1", "+15550000")
    host.disclosure_skip("s1")

    api.broadcast.assert_any_call({"event": "call_card_skipped", "session_id": "s1"})


@patch("iris.daemon.call_card_host.CaptureSession")
def test_disclosure_skip_stops_in_flight_announce_proc(mock_session_cls):
    host, _store, _api = _make_host()
    mock_session_cls.return_value = MagicMock()
    host.start_session("s1", "+15550000")
    proc = MagicMock()
    host._announce_proc = proc

    host.disclosure_skip("s1")

    proc.stop.assert_called_once_with()


@patch("iris.daemon.call_card_host.CaptureSession")
def test_disclosure_skip_with_no_announce_proc_does_not_raise(mock_session_cls):
    host, _store, _api = _make_host()
    mock_session_cls.return_value = MagicMock()
    host.start_session("s1", "+15550000")
    assert host._announce_proc is None

    host.disclosure_skip("s1")  # must not raise trying to .stop() a None proc

    assert host._announce_proc is None


# ---------------------------------------------------------------------------
# disclosure_ack / disclosure_skip -- cross-guard once disclosure_state has
# left "pending" (ti-uk58b AF2/UC4: automatic TTS completion and a manual
# [D]/[S] press can land within microseconds of each other).
#
# _make_host()'s store is a static MagicMock -- get_call_card always returns
# disclosure_state="pending" no matter what mark_disclosure_ack/
# mark_disclosure_skipped write, so it can't exercise this guard for real.
# These tests use a small dict-backed fake that actually remembers state.
# ---------------------------------------------------------------------------

class _StatefulStore:
    """Dict-backed fake CallCardStore whose disclosure_state actually changes."""

    def __init__(self):
        self._cards = {}

    def load_or_create(self, session_id, caller_number):
        self._cards[session_id] = {"disclosure_state": "pending"}

    def get_call_card(self, session_id):
        return self._cards.get(session_id, {})

    def mark_disclosure_ack(self, session_id):
        self._cards.setdefault(session_id, {})["disclosure_state"] = "disclosed"

    def mark_disclosure_skipped(self, session_id):
        self._cards.setdefault(session_id, {})["disclosure_state"] = "skipped"

    def mark_ended(self, session_id):
        pass

    def confirm_fact(self, *args, **kwargs):
        pass

    def confirm_action_item(self, *args, **kwargs):
        pass


def _make_stateful_host():
    store = _StatefulStore()
    host = CallCardHost(
        store=store, processor=MagicMock(), api=MagicMock(), cfg=MagicMock(), tts=MagicMock(),
    )
    return host, store


def test_disclosure_skip_then_ack_is_noop():
    host, store = _make_stateful_host()
    session_mock = MagicMock()
    host._session = session_mock
    host._session_id = "s1"
    store.load_or_create("s1", "+15550000")

    host.disclosure_skip("s1")
    host.disclosure_ack("s1")

    assert store.get_call_card("s1")["disclosure_state"] == "skipped"
    session_mock.start_far.assert_not_called()


def test_disclosure_ack_then_skip_is_noop():
    host, store = _make_stateful_host()
    host._session = MagicMock()
    host._session_id = "s1"
    store.load_or_create("s1", "+15550000")
    proc = MagicMock()

    host.disclosure_ack("s1")
    host._announce_proc = proc  # simulate an announce still "in flight" post-ack
    host.disclosure_skip("s1")

    assert store.get_call_card("s1")["disclosure_state"] == "disclosed"
    proc.stop.assert_not_called()


# ---------------------------------------------------------------------------
# _run_auto_disclose (ti-iv69h) -- fail-closed on no sink / any exception,
# never a timeout-based "disclose anyway" fallback.
#
# start_session() spawns _auto_disclose's own background thread, which would
# race a deliberately-synchronous, mocked-discover_sco_nodes call to
# _run_auto_disclose here. So these tests poke self._session/_session_id
# directly instead of going through start_session().
# ---------------------------------------------------------------------------

@patch("iris.daemon.call_card_host.TincanSCOAudio")
@patch("iris.daemon.call_card_host.discover_sco_nodes")
def test_run_auto_disclose_no_sink_fails_closed(mock_discover, mock_sco_cls, caplog):
    mock_discover.return_value = (None, None)
    host, store, _api = _make_host()

    with caplog.at_level(logging.WARNING, logger="iris.daemon.call_card_host"):
        host._run_auto_disclose("s1")

    mock_sco_cls.assert_not_called()
    store.mark_disclosure_ack.assert_not_called()
    assert host._announce_proc is None
    assert any("no SCO sink" in r.getMessage() for r in caplog.records)


@patch("iris.daemon.call_card_host._cached_disclosure_wav", return_value="/fake/disclosure.wav")
@patch("iris.daemon.call_card_host.TincanSCOAudio")
@patch("iris.daemon.call_card_host.discover_sco_nodes")
def test_run_auto_disclose_playback_exception_fails_closed(
    mock_discover, mock_sco_cls, _mock_wav, caplog,
):
    mock_discover.return_value = ("sink0", "source0")
    handle = MagicMock()
    handle.wait.side_effect = RuntimeError("playback died")
    mock_sco_cls.return_value.start_playback.return_value = handle
    host, store, _api = _make_host()
    host._session_id = "s1"  # matches the session_id under test -- not "superseded"

    with caplog.at_level(logging.WARNING, logger="iris.daemon.call_card_host"):
        host._run_auto_disclose("s1")

    store.mark_disclosure_ack.assert_not_called()
    assert host._announce_proc is None  # cleared in `finally` despite the exception
    assert any("auto-disclose failed" in r.getMessage() for r in caplog.records)


@patch("iris.daemon.call_card_host._cached_disclosure_wav", return_value="/fake/disclosure.wav")
@patch("iris.daemon.call_card_host.TincanSCOAudio")
@patch("iris.daemon.call_card_host.discover_sco_nodes")
def test_run_auto_disclose_happy_path_acks_and_starts_far(mock_discover, mock_sco_cls, _mock_wav):
    mock_discover.return_value = ("sink0", "source0")
    handle = MagicMock()
    mock_sco_cls.return_value.start_playback.return_value = handle
    host, store, _api = _make_host()
    session_mock = MagicMock()
    host._session = session_mock
    host._session_id = "s1"

    host._run_auto_disclose("s1")

    handle.wait.assert_called_once_with()
    store.mark_disclosure_ack.assert_called_once_with("s1")
    session_mock.start_far.assert_called_once_with()
    assert host._announce_proc is None


@patch("iris.daemon.call_card_host._cached_disclosure_wav", return_value="/fake/disclosure.wav")
@patch("iris.daemon.call_card_host.TincanSCOAudio")
@patch("iris.daemon.call_card_host.discover_sco_nodes")
def test_run_auto_disclose_bails_if_session_superseded_before_handle_registered(
    mock_discover, mock_sco_cls, _mock_wav,
):
    mock_discover.return_value = ("sink0", "source0")
    handle = MagicMock()
    mock_sco_cls.return_value.start_playback.return_value = handle
    host, store, _api = _make_host()
    host._session_id = "s2"  # a concurrent start_session() already superseded "s1"

    host._run_auto_disclose("s1")

    handle.stop.assert_called_once_with()
    handle.wait.assert_not_called()
    store.mark_disclosure_ack.assert_not_called()
    assert host._announce_proc is None


# ---------------------------------------------------------------------------
# _cached_disclosure_wav (ti-iv69h) -- content-hash-keyed WAV render cache,
# mirroring iris.disclosure.ensure_disclosure_wav's sidecar shape.
# ---------------------------------------------------------------------------

def _fake_tts_writing(tmp_path):
    """A tts stand-in whose .synth() really writes a file, so shutil.move has
    something real to move -- mirrors the real TTS returning a temp WAV path.
    """
    tts = MagicMock()

    def _synth(script):
        rendered = tmp_path / f"rendered-{hashlib.sha256(script.encode()).hexdigest()}.wav"
        rendered.write_bytes(script.encode("utf-8"))
        return str(rendered)

    tts.synth.side_effect = _synth
    return tts


def test_cached_disclosure_wav_synthesizes_on_first_call(tmp_path):
    wav_path = tmp_path / "disclosure.wav"
    tts = _fake_tts_writing(tmp_path)

    result = _cached_disclosure_wav("hello world", tts, wav_path)

    assert result == str(wav_path)
    assert wav_path.read_bytes() == b"hello world"
    tts.synth.assert_called_once_with("hello world")
    assert wav_path.with_suffix(".hash").exists()


def test_cached_disclosure_wav_reuses_cache_for_unchanged_script(tmp_path):
    wav_path = tmp_path / "disclosure.wav"
    tts = _fake_tts_writing(tmp_path)
    _cached_disclosure_wav("hello world", tts, wav_path)
    tts.synth.reset_mock()

    result = _cached_disclosure_wav("hello world", tts, wav_path)

    assert result == str(wav_path)
    tts.synth.assert_not_called()


def test_cached_disclosure_wav_resynthesizes_on_script_change(tmp_path):
    wav_path = tmp_path / "disclosure.wav"
    tts = _fake_tts_writing(tmp_path)
    _cached_disclosure_wav("script one", tts, wav_path)

    result = _cached_disclosure_wav("script two", tts, wav_path)

    assert result == str(wav_path)
    assert tts.synth.call_count == 2
    assert wav_path.read_bytes() == b"script two"
