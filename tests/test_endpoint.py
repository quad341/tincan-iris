"""Tests for LocalAudio. Subprocess + sleep are mocked — no real audio devices,
so these run anywhere (incl. CI)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from iris.audio.endpoint import LocalAudio


def test_player_cmd_prefers_explicit_override() -> None:
    la = LocalAudio(player=["myplayer", "-q"])
    assert la._player_cmd("/tmp/a.wav") == ["myplayer", "-q", "/tmp/a.wav"]


def test_recorder_cmd_explicit_override() -> None:
    la = LocalAudio(recorder=["myrec"])
    assert la._recorder_cmd("/tmp/a.wav") == ["myrec", "/tmp/a.wav"]


def test_recorder_cmd_pw_record_builds_16k_mono() -> None:
    la = LocalAudio(rate=16000, channels=1)
    with patch(
        "iris.audio.endpoint.shutil.which", side_effect=lambda b: b == "pw-record"
    ):
        cmd = la._recorder_cmd("/tmp/a.wav")
    assert cmd[0] == "pw-record"
    assert "--rate" in cmd and "16000" in cmd
    assert "--channels" in cmd and "1" in cmd
    assert cmd[-1] == "/tmp/a.wav"


def test_recorder_cmd_raises_when_none_found() -> None:
    la = LocalAudio()
    with patch("iris.audio.endpoint.shutil.which", return_value=None):
        with pytest.raises(RuntimeError, match="no audio recorder"):
            la._recorder_cmd("/tmp/a.wav")


def test_capture_starts_records_and_stops() -> None:
    la = LocalAudio(recorder=["myrec"])
    fake_proc = MagicMock()
    with patch("iris.audio.endpoint.subprocess.Popen", return_value=fake_proc) as popen, \
         patch("iris.audio.endpoint.time.sleep") as sleep:
        wav = la.capture(2.0)
    popen.assert_called_once()
    sleep.assert_called_once_with(2.0)
    fake_proc.send_signal.assert_called_once()  # SIGINT finalizes the WAV
    assert wav.endswith(".wav")
