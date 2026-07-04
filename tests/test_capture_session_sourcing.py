"""CaptureSession audio sourcing (ti-wunrs) + start_operator/start_far split (ti-ir12t).

The DURING far channel must target the live SCO downlink (bluez_input), not the
default source — with ambient AEC the default source is the operator's own
(echo-cancelled) mic, so a bare default capture would double-record the operator
instead of the far party.

ti-ir12t split start() into start_operator() (operator channel only, called
immediately on call connect) and start_far() (far channel only, called after an
explicit disclosure ack) — the hard-gate for far-party consent. start() itself
is unchanged (bundles both) and its existing tests below are untouched.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from iris.audio.streaming import StreamingTranscriber
from iris.capture.session import CaptureSession


def _make_session() -> CaptureSession:
    return CaptureSession(
        session_id="s1",
        transcript_store=MagicMock(),
        processor=MagicMock(),
        store=MagicMock(),
        on_fact=MagicMock(),
        on_action_item=MagicMock(),
    )


@patch("iris.audio.endpoint.discover_sco_nodes")
@patch("iris.capture.session.StreamingTranscriber")
def test_far_channel_targets_sco_downlink(mock_st, mock_discover) -> None:
    op, far = MagicMock(), MagicMock()
    mock_st.side_effect = [op, far]  # __init__ builds operator first, then far
    mock_discover.return_value = ("bluez_output.AA_BB.1", "bluez_input.AA_BB.1")

    sess = _make_session()
    sess.start()

    # Far is pointed at the discovered downlink and started; operator uses the default.
    assert far.source == "bluez_input.AA_BB.1"
    op.start.assert_called_once()
    far.start.assert_called_once()


@patch("iris.audio.endpoint.discover_sco_nodes")
@patch("iris.capture.session.StreamingTranscriber")
def test_far_channel_skipped_when_no_downlink(mock_st, mock_discover) -> None:
    op, far = MagicMock(), MagicMock()
    mock_st.side_effect = [op, far]
    mock_discover.return_value = (None, None)  # no live call

    sess = _make_session()
    sess.start()

    # Operator still captures; far is NOT started (nothing to capture, no double-record).
    op.start.assert_called_once()
    far.start.assert_not_called()


# ---------------------------------------------------------------------------
# start_operator() / start_far() split (ti-ir12t hard-gate)
# ---------------------------------------------------------------------------

@patch("iris.audio.endpoint.discover_sco_nodes")
@patch("iris.capture.session.StreamingTranscriber")
def test_start_operator_starts_only_operator_channel(mock_st, mock_discover) -> None:
    op, far = MagicMock(), MagicMock()
    mock_st.side_effect = [op, far]

    sess = _make_session()
    sess.start_operator()

    op.start.assert_called_once()
    far.start.assert_not_called()
    # start_operator() never touches SCO discovery — that's start_far()'s concern.
    mock_discover.assert_not_called()


@patch("iris.audio.endpoint.discover_sco_nodes")
@patch("iris.capture.session.StreamingTranscriber")
def test_start_far_targets_sco_downlink_and_starts_only_far(mock_st, mock_discover) -> None:
    op, far = MagicMock(), MagicMock()
    mock_st.side_effect = [op, far]
    mock_discover.return_value = ("bluez_output.AA_BB.1", "bluez_input.AA_BB.1")

    sess = _make_session()
    sess.start_far()

    assert far.source == "bluez_input.AA_BB.1"
    far.start.assert_called_once()
    op.start.assert_not_called()


@patch("iris.audio.endpoint.discover_sco_nodes")
@patch("iris.capture.session.StreamingTranscriber")
def test_start_far_skipped_when_no_downlink(mock_st, mock_discover) -> None:
    op, far = MagicMock(), MagicMock()
    mock_st.side_effect = [op, far]
    mock_discover.return_value = (None, None)

    sess = _make_session()
    sess.start_far()

    far.start.assert_not_called()


# ---------------------------------------------------------------------------
# stop() regression: safe no-op on a never-started far channel (ti-ir12t)
# ---------------------------------------------------------------------------

@patch("iris.audio.endpoint.discover_sco_nodes")
@patch("iris.capture.session.StreamingTranscriber")
def test_stop_safe_when_only_operator_started(mock_st, mock_discover) -> None:
    """Regression for the new split: a call where the operator channel started but
    disclosure never happened (call ended first) must tear down cleanly.

    far is a REAL StreamingTranscriber (never mocked) so this exercises the actual
    guard in iris/audio/streaming.py's stop() — `if proc and proc.poll() is None` —
    rather than merely asserting a mock's .stop() was called.
    """
    op = MagicMock()
    far_real = StreamingTranscriber(lambda *a: None, label="far", backend="pw")
    mock_st.side_effect = [op, far_real]

    sess = _make_session()
    sess.start_operator()
    op.start.assert_called_once()

    sess.stop()  # must not raise

    op.stop.assert_called_once()
    # far_real's .start() was never called, so _rec/_worker were already None —
    # stop()'s guard no-ops rather than touching a non-existent process.
    assert far_real._rec is None
    assert far_real._worker is None
