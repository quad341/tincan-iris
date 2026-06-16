"""Tests for LocalAudio. Subprocess + sleep are mocked — no real audio devices,
so these run anywhere (incl. CI)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from iris.audio.endpoint import (
    LocalAudio,
    TincanSCOAudio,
    VirtualDeviceAudio,
    _pick_bluez,
    _pw_link_nodes,
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

def test_tincan_sco_playback_uses_pw_cat_target():
    # SCO nodes are native PipeWire nodes (invisible to pulse) -> pw-cat --target.
    sco = TincanSCOAudio("bluez_output.AA_BB.1", "bluez_input.AA_BB.0")
    assert sco.name == "tincan-sco"
    assert sco._player_cmd("/tmp/a.wav") == [
        "pw-cat", "-p", "--target", "bluez_output.AA_BB.1", "/tmp/a.wav"
    ]


def test_tincan_sco_far_source_and_backend():
    sco = TincanSCOAudio("bluez_output.AA_BB.1", "bluez_input.AA_BB.0")
    assert sco.far_source == "bluez_input.AA_BB.0"
    assert sco.far_backend == "pw"  # far ear captured via pw-record, not pulse


def test_tincan_sco_monitor_plays_to_uplink_and_local_speakers():
    # Operator must hear Iris too (supervised model): play to uplink AND default sink.
    sco = TincanSCOAudio("bluez_output.AA_BB.1", "bluez_input.AA_BB.0")  # monitor=True default
    assert sco._monitor_cmd("/tmp/a.wav") == ["pw-cat", "-p", "/tmp/a.wav"]  # default sink
    fake = MagicMock()
    with patch("iris.audio.endpoint.subprocess.Popen", return_value=fake) as popen:
        pb = sco.start_playback("/tmp/a.wav")
    assert popen.call_count == 2  # uplink (mom) + local monitor (operator)
    pb.stop()
    assert fake.send_signal.call_count == 2  # barge-in cuts both


def test_tincan_sco_monitor_disabled_plays_only_uplink():
    sco = TincanSCOAudio("bluez_output.AA_BB.1", "bluez_input.AA_BB.0", monitor=False)
    with patch("iris.audio.endpoint.subprocess.Popen", return_value=MagicMock()) as popen:
        sco.start_playback("/tmp/a.wav")
    assert popen.call_count == 1  # uplink only


def test_tincan_sco_ptt_capture_uses_default_mic():
    # Push-to-talk is the operator addressing Iris -> default mic, NOT the SCO source.
    sco = TincanSCOAudio("bluez_output.AA_BB.1", "bluez_input.AA_BB.0")
    with patch("iris.audio.endpoint.shutil.which", side_effect=lambda b: b == "pw-record"):
        rec = sco._recorder_cmd("/tmp/a.wav")
    assert rec[0] == "pw-record"
    assert not any(a.startswith("--device=") or a == "--target" for a in rec)


def test_pick_bluez_first_matching_prefix():
    names = ["alsa_output.pci", "bluez_output.AA_BB.1", "bluez_output.CC.2"]
    assert _pick_bluez(names, "bluez_output") == "bluez_output.AA_BB.1"


def test_pick_bluez_none_without_match():
    assert _pick_bluez(["alsa_output.pci", "alsa_input.usb"], "bluez_input") is None


def test_pw_link_nodes_parses_distinct_node_names():
    fake = MagicMock()
    fake.stdout = (
        "bluez_input.AA_BB.0:output_FL\n"
        "bluez_input.AA_BB.0:output_FR\n"
        "alsa_output.pci:playback_FL\n"
    )
    with patch("iris.audio.endpoint.subprocess.run", return_value=fake):
        names = _pw_link_nodes("out")
    assert names == ["bluez_input.AA_BB.0", "alsa_output.pci"]  # de-duped per node


def test_pw_link_nodes_empty_when_pw_link_missing():
    with patch("iris.audio.endpoint.subprocess.run", side_effect=FileNotFoundError):
        assert _pw_link_nodes("in") == []


def test_default_endpoint_sco_with_env_override(monkeypatch):
    monkeypatch.setenv("IRIS_AUDIO", "tincan-sco")
    monkeypatch.setenv("IRIS_SCO_SINK", "bluez_output.AA_BB.1")
    monkeypatch.setenv("IRIS_SCO_SOURCE", "bluez_input.AA_BB.0")
    ep = default_endpoint()
    assert isinstance(ep, TincanSCOAudio)
    assert ep.playback_target == "bluez_output.AA_BB.1"
    assert ep.far_source == "bluez_input.AA_BB.0"


def test_default_endpoint_sco_discovers_nodes(monkeypatch):
    monkeypatch.setenv("IRIS_AUDIO", "tincan-sco")
    monkeypatch.delenv("IRIS_SCO_SINK", raising=False)
    monkeypatch.delenv("IRIS_SCO_SOURCE", raising=False)
    with patch(
        "iris.audio.endpoint.discover_sco_nodes",
        return_value=("bluez_output.AA_BB.1", "bluez_input.AA_BB.0"),
    ):
        ep = default_endpoint()
    assert isinstance(ep, TincanSCOAudio)
    assert ep.playback_target == "bluez_output.AA_BB.1"
    assert ep.far_source == "bluez_input.AA_BB.0"


def test_default_endpoint_sco_raises_when_no_call(monkeypatch):
    monkeypatch.setenv("IRIS_AUDIO", "tincan-sco")
    monkeypatch.delenv("IRIS_SCO_SINK", raising=False)
    monkeypatch.delenv("IRIS_SCO_SOURCE", raising=False)
    with patch("iris.audio.endpoint.discover_sco_nodes", return_value=(None, None)):
        with pytest.raises(RuntimeError, match="no HFP/SCO sink"):
            default_endpoint()


# --- IRIS_VA_AEC branching (ti-lfp) ------------------------------------------

def test_default_endpoint_va_aec_sets_iris_va_aec_src(monkeypatch):
    monkeypatch.delenv("IRIS_AUDIO", raising=False)
    monkeypatch.setenv("IRIS_PLAYBACK_TARGET", "iris_mic")
    monkeypatch.setenv("IRIS_VA_AEC", "1")
    monkeypatch.delenv("IRIS_CAPTURE_TARGET", raising=False)
    ep = default_endpoint()
    assert isinstance(ep, VirtualDeviceAudio)
    assert ep.capture_target == "iris_va_aec_src"


def test_default_endpoint_iris_capture_target_wins_over_va_aec(monkeypatch):
    monkeypatch.delenv("IRIS_AUDIO", raising=False)
    monkeypatch.setenv("IRIS_PLAYBACK_TARGET", "iris_mic")
    monkeypatch.setenv("IRIS_VA_AEC", "1")
    monkeypatch.setenv("IRIS_CAPTURE_TARGET", "my_explicit_src")
    ep = default_endpoint()
    assert isinstance(ep, VirtualDeviceAudio)
    assert ep.capture_target == "my_explicit_src"
