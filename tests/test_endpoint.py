"""Tests for LocalAudio. Subprocess + sleep are mocked — no real audio devices,
so these run anywhere (incl. CI)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from iris.audio.endpoint import (
    LocalAudio,
    TincanSCOAudio,
    VirtualDeviceAudio,
    _pactl_short,
    _pick_sco,
    default_endpoint,
)


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
    monkeypatch.delenv("IRIS_AUDIO", raising=False)
    monkeypatch.setenv("IRIS_PLAYBACK_TARGET", "iris_mic")
    monkeypatch.setenv("IRIS_CAPTURE_TARGET", "src")
    ep = default_endpoint()
    assert isinstance(ep, VirtualDeviceAudio)
    assert ep.playback_target == "iris_mic"
    assert ep.capture_target == "src"


# --- TincanSCOAudio (real phone call over HFP/SCO) ----------------------------

def test_tincan_sco_playback_targets_the_sco_sink():
    sco = TincanSCOAudio(
        "bluez_output.AA.headset-head-unit", "bluez_input.AA.headset-head-unit"
    )
    assert sco.name == "tincan-sco"
    # Iris's voice plays into the SCO uplink sink (the far party hears it).
    assert sco._player_cmd("/tmp/a.wav") == [
        "paplay", "--device=bluez_output.AA.headset-head-unit", "/tmp/a.wav"
    ]


def test_tincan_sco_far_source_is_the_downlink():
    sco = TincanSCOAudio("sink", "bluez_input.AA.headset-head-unit")
    assert sco.far_source == "bluez_input.AA.headset-head-unit"


def test_tincan_sco_ptt_capture_uses_default_mic():
    # Push-to-talk is the operator addressing Iris -> default mic, NOT the SCO source.
    sco = TincanSCOAudio("sink", "src")
    with patch("iris.audio.endpoint.shutil.which", side_effect=lambda b: b == "pw-record"):
        rec = sco._recorder_cmd("/tmp/a.wav")
    assert rec[0] == "pw-record"
    assert not any(a.startswith("--device=") for a in rec)


def test_pick_sco_prefers_headset_profile_over_a2dp():
    names = [
        "bluez_output.AA_BB.a2dp-sink",
        "bluez_output.AA_BB.headset-head-unit",
        "alsa_output.pci",
    ]
    assert _pick_sco(names, "bluez_output") == "bluez_output.AA_BB.headset-head-unit"


def test_pick_sco_ignores_monitor_and_falls_through_to_source():
    names = [
        "bluez_output.AA_BB.headset-head-unit.monitor",
        "bluez_input.AA_BB.headset-head-unit",
    ]
    assert _pick_sco(names, "bluez_input") == "bluez_input.AA_BB.headset-head-unit"
    # the only bluez_output here is a .monitor -> never picked
    assert _pick_sco(names, "bluez_output") is None


def test_pick_sco_returns_none_without_bluez():
    assert _pick_sco(["alsa_output.pci", "alsa_input.usb"], "bluez_output") is None


def test_pactl_short_parses_node_names():
    fake = MagicMock()
    fake.stdout = (
        "53\tbluez_output.AA.headset-head-unit\tmodule\ts16le\tRUNNING\n"
        "54\talsa_output.pci\tmodule\ts16le\tIDLE\n"
    )
    with patch("iris.audio.endpoint.subprocess.run", return_value=fake):
        names = _pactl_short("sinks")
    assert names == ["bluez_output.AA.headset-head-unit", "alsa_output.pci"]


def test_pactl_short_empty_when_pactl_missing():
    with patch("iris.audio.endpoint.subprocess.run", side_effect=FileNotFoundError):
        assert _pactl_short("sinks") == []


def test_default_endpoint_sco_with_env_override(monkeypatch):
    monkeypatch.setenv("IRIS_AUDIO", "tincan-sco")
    monkeypatch.setenv("IRIS_SCO_SINK", "bluez_output.AA.headset-head-unit")
    monkeypatch.setenv("IRIS_SCO_SOURCE", "bluez_input.AA.headset-head-unit")
    ep = default_endpoint()
    assert isinstance(ep, TincanSCOAudio)
    assert ep.playback_target == "bluez_output.AA.headset-head-unit"
    assert ep.far_source == "bluez_input.AA.headset-head-unit"


def test_default_endpoint_sco_discovers_nodes(monkeypatch):
    monkeypatch.setenv("IRIS_AUDIO", "tincan-sco")
    monkeypatch.delenv("IRIS_SCO_SINK", raising=False)
    monkeypatch.delenv("IRIS_SCO_SOURCE", raising=False)
    with patch(
        "iris.audio.endpoint.discover_sco_nodes",
        return_value=(
            "bluez_output.AA.headset-head-unit",
            "bluez_input.AA.headset-head-unit",
        ),
    ):
        ep = default_endpoint()
    assert isinstance(ep, TincanSCOAudio)
    assert ep.playback_target == "bluez_output.AA.headset-head-unit"
    assert ep.far_source == "bluez_input.AA.headset-head-unit"


def test_default_endpoint_sco_raises_when_no_call(monkeypatch):
    monkeypatch.setenv("IRIS_AUDIO", "tincan-sco")
    monkeypatch.delenv("IRIS_SCO_SINK", raising=False)
    monkeypatch.delenv("IRIS_SCO_SOURCE", raising=False)
    with patch("iris.audio.endpoint.discover_sco_nodes", return_value=(None, None)):
        with pytest.raises(RuntimeError, match="no HFP/SCO sink"):
            default_endpoint()
