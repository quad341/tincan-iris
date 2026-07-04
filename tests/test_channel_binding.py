"""Tests: far-channel binding integrity (ti-3p688 / mom-call findings 2026-07-04).

PipeWire silently reroutes a capture stream to the DEFAULT source when its
--target is missing or disappears (verified live: node.dont-reconnect is set on
the stream but not honored) — which relabeled the operator's mic as "far".
These tests cover the countermeasures: unique stream node names, link-graph
verification, unexpected-death reporting, and the CaptureSession watchdog.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from iris.audio import streaming
from iris.audio.streaming import StreamingTranscriber
from iris.capture.session import CaptureSession

_DOWNLINK = "bluez_input.D0_6B_78_33_46_20.0"


def _far_transcriber(**kw):
    t = StreamingTranscriber(lambda text, label: None, backend="pw",
                             source=f"{_DOWNLINK}", label="far", **kw)
    return t


# ---------------------------------------------------------------------------
# Recorder command: unique node name + dont-reconnect
# ---------------------------------------------------------------------------

def test_pw_recorder_sets_unique_node_name_and_dont_reconnect():
    t1, t2 = _far_transcriber(), _far_transcriber()
    cmd = t1._recorder_cmd()
    props = cmd[cmd.index("-P") + 1]
    assert t1.stream_node_name in props
    assert "node.dont-reconnect = true" in props
    assert t1.stream_node_name != t2.stream_node_name


# ---------------------------------------------------------------------------
# verify_target_bound
# ---------------------------------------------------------------------------

def _graph(stream: str, feeder: str) -> str:
    return (
        f"{feeder}:capture_MONO\n"
        f"  |-> {stream}:input_MONO\n"
        f"{stream}:input_MONO\n"
        f"  |<- {feeder}:capture_MONO\n"
    )


def test_verify_ok_when_fed_by_intended_target(monkeypatch):
    t = _far_transcriber()
    monkeypatch.setattr(streaming, "_run_pw_link_l",
                        lambda: _graph(t.stream_node_name, _DOWNLINK))
    ok, detail = t.verify_target_bound()
    assert ok, detail


def test_verify_fails_when_rerouted_to_default_mic(monkeypatch):
    """The live failure mode: session manager silently rewires us to the mic."""
    t = _far_transcriber()
    monkeypatch.setattr(streaming, "_run_pw_link_l",
                        lambda: _graph(t.stream_node_name, "iris_aec_src"))
    ok, detail = t.verify_target_bound()
    assert not ok
    assert "rerouted" in detail


def test_verify_fails_when_stream_has_no_links(monkeypatch):
    t = _far_transcriber()
    monkeypatch.setattr(streaming, "_run_pw_link_l", lambda: "other:port\n")
    ok, detail = t.verify_target_bound()
    assert not ok
    assert "no incoming links" in detail


def test_verify_trivially_ok_without_explicit_pw_target():
    t = StreamingTranscriber(lambda text, label: None, label="operator")
    ok, _ = t.verify_target_bound()
    assert ok


# ---------------------------------------------------------------------------
# Unexpected pipeline death → on_stream_end (but not after stop())
# ---------------------------------------------------------------------------

def test_read_loop_end_fires_on_stream_end_when_not_stopping():
    seen = []
    t = _far_transcriber(on_stream_end=seen.append)
    t._worker = MagicMock()
    t._worker.stdout = iter([])  # EOF immediately
    t._read_loop()
    assert seen == ["far"]


def test_read_loop_end_silent_after_requested_stop():
    seen = []
    t = _far_transcriber(on_stream_end=seen.append)
    t._stop_requested = True
    t._worker = MagicMock()
    t._worker.stdout = iter([])
    t._read_loop()
    assert seen == []


# ---------------------------------------------------------------------------
# CaptureSession far watchdog
# ---------------------------------------------------------------------------

def _session(on_far_lost):
    return CaptureSession(
        session_id="s1",
        transcript_store=MagicMock(),
        processor=MagicMock(),
        store=MagicMock(),
        on_fact=lambda f: None,
        on_action_item=lambda a: None,
        on_far_lost=on_far_lost,
    )


def test_far_lost_stops_far_and_reports_once():
    lost = []
    sess = _session(lost.append)
    sess._far = MagicMock()
    sess._report_far_lost("rerouted to mic")
    sess._report_far_lost("second report suppressed")
    sess._far.stop.assert_called_once()
    assert lost == ["rerouted to mic"]


def test_far_stream_death_reports_far_lost():
    lost = []
    sess = _session(lost.append)
    sess._far = MagicMock()
    sess._on_far_stream_end("far")
    assert lost and "exited unexpectedly" in lost[0]


def test_watchdog_kills_far_on_bad_binding():
    lost = []
    sess = _session(lost.append)
    sess._far = MagicMock()
    sess._far.verify_target_bound.return_value = (False, "fed by ['iris_aec_src'] — rerouted")
    with patch.object(sess._far_watchdog_stop, "wait", side_effect=[False, True]):
        sess._far_binding_watchdog()
    sess._far.stop.assert_called_once()
    assert lost and "rerouted" in lost[0]


def test_watchdog_keeps_running_while_binding_ok():
    lost = []
    sess = _session(lost.append)
    sess._far = MagicMock()
    sess._far.verify_target_bound.return_value = (True, "bound")
    with patch.object(sess._far_watchdog_stop, "wait", side_effect=[False, False, True]):
        sess._far_binding_watchdog()
    sess._far.stop.assert_not_called()
    assert lost == []


def test_pw_recorder_targets_by_serial_when_resolvable(monkeypatch):
    """Name-based --target falls back to the default mic when the session
    manager can't resolve it (verified live); serial targeting binds
    deterministically, so it's preferred when available."""
    monkeypatch.setattr(streaming, "resolve_node_serial",
                        lambda name: "4242" if name == _DOWNLINK else None)
    t = _far_transcriber()
    cmd = t._recorder_cmd()
    assert cmd[cmd.index("--target") + 1] == "4242"


def test_pw_recorder_falls_back_to_name_when_serial_unresolvable(monkeypatch):
    monkeypatch.setattr(streaming, "resolve_node_serial", lambda name: None)
    t = _far_transcriber()
    cmd = t._recorder_cmd()
    assert cmd[cmd.index("--target") + 1] == _DOWNLINK
