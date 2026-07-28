"""Tests for LoopbackAudioEndpoint — the no-Bluetooth, no-hardware call seam
(voice-call-architecture.md §7). Pure in-memory + tiny real WAV files, so these
run anywhere (incl. CI)."""
from __future__ import annotations

import wave

import pytest

from iris.audio.endpoint import LoopbackAudioEndpoint, default_endpoint


def _wav(path, *, ms: int = 50, rate: int = 16000) -> str:
    """Write a tiny valid mono s16 WAV so shutil.copyfile has real bytes to move."""
    frames = b"\x00\x00" * int(rate * ms / 1000)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(frames)
    return str(path)


# --- capture (ears): replay far-party fixtures in order ----------------------

def test_capture_replays_fixtures_in_order(tmp_path):
    a, b = _wav(tmp_path / "a.wav"), _wav(tmp_path / "b.wav")
    ep = LoopbackAudioEndpoint([a, b])
    assert ep.capture(2.0) == a
    assert ep.capture(2.0) == b


def test_remaining_tracks_unconsumed_turns(tmp_path):
    a, b = _wav(tmp_path / "a.wav"), _wav(tmp_path / "b.wav")
    ep = LoopbackAudioEndpoint([a, b])
    assert ep.remaining == 2
    ep.capture(1.0)
    assert ep.remaining == 1
    ep.capture(1.0)
    assert ep.remaining == 0


def test_queue_appends_turns(tmp_path):
    a, b = _wav(tmp_path / "a.wav"), _wav(tmp_path / "b.wav")
    ep = LoopbackAudioEndpoint()
    ep.queue(a)
    ep.queue(b)
    assert ep.remaining == 2
    assert ep.capture(1.0) == a
    assert ep.capture(1.0) == b


def test_capture_raises_when_exhausted(tmp_path):
    ep = LoopbackAudioEndpoint([_wav(tmp_path / "a.wav")])
    ep.capture(1.0)
    with pytest.raises(IndexError, match="no more far-party fixtures"):
        ep.capture(1.0)


def test_capture_returns_silence_when_exhausted_if_provided(tmp_path):
    sil = _wav(tmp_path / "silence.wav")
    ep = LoopbackAudioEndpoint([_wav(tmp_path / "a.wav")], silence_wav=sil)
    ep.capture(1.0)
    assert ep.capture(1.0) == sil  # no raise — silence instead
    assert ep.capture(1.0) == sil  # and again


# --- playback (mouth): record what Iris put on the uplink --------------------

def test_playback_logs_uplink_in_order(tmp_path):
    x, y = _wav(tmp_path / "x.wav"), _wav(tmp_path / "y.wav")
    ep = LoopbackAudioEndpoint()
    ep.playback(x)
    ep.playback(y)
    assert ep.played == [x, y]


def test_playback_copies_to_uplink_dir(tmp_path):
    x = _wav(tmp_path / "x.wav")
    out = tmp_path / "uplink"  # does not exist yet — endpoint must create it
    ep = LoopbackAudioEndpoint(uplink_dir=str(out))
    ep.playback(x)
    assert len(ep.uplink_files) == 1
    copied = ep.uplink_files[0]
    assert copied.endswith("uplink-001.wav")
    # real bytes were moved, identical to the source
    assert open(copied, "rb").read() == open(x, "rb").read()


def test_no_uplink_dir_means_no_copies(tmp_path):
    ep = LoopbackAudioEndpoint()
    ep.playback(_wav(tmp_path / "x.wav"))
    assert ep.uplink_files == []
    assert len(ep.played) == 1


# --- handle API: drop-in for the Conductor (start_capture/start_playback) -----

def test_start_capture_handle_returns_fixture(tmp_path):
    a = _wav(tmp_path / "a.wav")
    ep = LoopbackAudioEndpoint([a])
    rec = ep.start_capture()
    assert rec.wav_path == a
    assert rec.stop() == a


def test_start_playback_handle_records_and_waits(tmp_path):
    x = _wav(tmp_path / "x.wav")
    ep = LoopbackAudioEndpoint()
    play = ep.start_playback(x)
    assert ep.played == [x]          # logged the instant it started
    assert play.wait() is None       # no real audio to block on
    assert play.interrupted is False


def test_start_playback_stop_marks_barge_in(tmp_path):
    ep = LoopbackAudioEndpoint()
    play = ep.start_playback(_wav(tmp_path / "x.wav"))
    play.stop()
    assert play.interrupted is True  # barge-in is observable for tests


# --- protocol conformance + a full scripted turn-loop round-trip --------------

def test_satisfies_audioendpoint_surface():
    ep = LoopbackAudioEndpoint()
    assert ep.name == "loopback"
    assert ep.far_source is None
    assert ep.far_backend == "pulse"
    assert callable(ep.capture) and callable(ep.playback)


def test_round_trip_as_flow_callables(tmp_path):
    """A scripted flow takes play_fn=ep.playback + capture_fn=ep.capture. Drive a
    minimal listen/speak loop through those exact callables and assert the uplink."""
    far1, far2 = _wav(tmp_path / "far1.wav"), _wav(tmp_path / "far2.wav")
    iris1, iris2 = _wav(tmp_path / "iris1.wav"), _wav(tmp_path / "iris2.wav")
    ep = LoopbackAudioEndpoint([far1, far2])
    play_fn, capture_fn = ep.playback, ep.capture

    # turn 1: hear the far party, then speak
    assert capture_fn(3.0) == far1
    play_fn(iris1)
    # turn 2
    assert capture_fn(3.0) == far2
    play_fn(iris2)

    assert ep.played == [iris1, iris2]
    assert ep.remaining == 0


# --- default_endpoint() wiring (IRIS_AUDIO=loopback) --------------------------

def test_default_endpoint_loopback_parses_fixtures(monkeypatch, tmp_path):
    a, b = _wav(tmp_path / "a.wav"), _wav(tmp_path / "b.wav")
    monkeypatch.setenv("IRIS_AUDIO", "loopback")
    monkeypatch.setenv("IRIS_LOOPBACK_FIXTURES", f"{a}, {b}")  # spaces tolerated
    monkeypatch.setenv("IRIS_LOOPBACK_UPLINK_DIR", str(tmp_path / "up"))
    ep = default_endpoint()
    assert isinstance(ep, LoopbackAudioEndpoint)
    assert ep.remaining == 2
    assert ep.capture(1.0) == a
    assert ep.capture(1.0) == b


def test_default_endpoint_loopback_allows_empty_fixtures(monkeypatch):
    monkeypatch.setenv("IRIS_AUDIO", "loopback")
    monkeypatch.delenv("IRIS_LOOPBACK_FIXTURES", raising=False)
    monkeypatch.delenv("IRIS_LOOPBACK_UPLINK_DIR", raising=False)
    ep = default_endpoint()
    assert isinstance(ep, LoopbackAudioEndpoint)
    assert ep.remaining == 0
