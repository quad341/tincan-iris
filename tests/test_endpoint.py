"""Tests for LocalAudio. Subprocess + sleep are mocked — no real audio devices,
so these run anywhere (incl. CI)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from iris.audio.endpoint import LocalAudio, VirtualDeviceAudio, default_endpoint


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


# --- VirtualDeviceAudio (Discord/Zoom routing) --------------------------------

def test_virtual_device_targets_sink_and_source():
    va = VirtualDeviceAudio("iris_mic", "mysource")
    assert va._player_cmd("/tmp/a.wav") == [
        "paplay", "--device=iris_mic", "/tmp/a.wav"
    ]
    rec = va._recorder_cmd("/tmp/a.wav")
    assert rec[0] == "parecord"
    assert "--device=mysource" in rec
    assert rec[-1] == "/tmp/a.wav"


def test_virtual_device_capture_defaults_to_default_mic():
    # No capture target -> default mic via pw-record (finalizes cleanly on SIGINT,
    # unlike parecord which truncated paused speech).
    va = VirtualDeviceAudio("iris_mic")
    with patch("iris.audio.endpoint.shutil.which", side_effect=lambda b: b == "pw-record"):
        rec = va._recorder_cmd("/tmp/a.wav")
    assert rec[0] == "pw-record"
    assert not any(a.startswith("--device=") for a in rec)


def test_default_endpoint_is_local_without_env(monkeypatch):
    monkeypatch.delenv("IRIS_PLAYBACK_TARGET", raising=False)
    assert type(default_endpoint()) is LocalAudio


def test_default_endpoint_is_virtual_with_env(monkeypatch):
    monkeypatch.setenv("IRIS_PLAYBACK_TARGET", "iris_mic")
    monkeypatch.setenv("IRIS_CAPTURE_TARGET", "src")
    ep = default_endpoint()
    assert isinstance(ep, VirtualDeviceAudio)
    assert ep.playback_target == "iris_mic"
    assert ep.capture_target == "src"
