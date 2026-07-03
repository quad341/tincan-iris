"""CaptureSession audio sourcing (ti-wunrs).

The DURING far channel must target the live SCO downlink (bluez_input), not the
default source — with ambient AEC the default source is the operator's own
(echo-cancelled) mic, so a bare default capture would double-record the operator
instead of the far party.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

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
