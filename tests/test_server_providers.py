"""Tests for FasterWhisperServerSTT + KokoroServerTTS server-mode providers (ti-qxel.2).

These tests FAIL until the builder implements the server-mode provider classes
(FasterWhisperServerSTT, STTError in iris/audio/stt.py and
KokoroServerTTS, TTSError in iris/audio/tts.py).
All HTTP calls are mocked via urllib — no real server is started.
"""
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# urllib mock helpers
# ---------------------------------------------------------------------------

def _mock_urlopen(status: int, body: bytes):
    resp = MagicMock()
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    resp.read.return_value = body
    resp.status = status
    return resp


# ---------------------------------------------------------------------------
# FasterWhisperServerSTT.available()
# ---------------------------------------------------------------------------

def test_available_returns_true_when_health_200_ready():
    from iris.audio.stt import FasterWhisperServerSTT
    body = json.dumps({"ready": True, "status": "ok"}).encode()
    with patch("iris.audio.stt.urllib.request.urlopen",
               return_value=_mock_urlopen(200, body)):
        assert FasterWhisperServerSTT().available() is True


def test_available_returns_false_when_health_503():
    from iris.audio.stt import FasterWhisperServerSTT
    import urllib.error
    with patch("iris.audio.stt.urllib.request.urlopen",
               side_effect=urllib.error.HTTPError(
                   url="", code=503, msg="Service Unavailable", hdrs=None, fp=None)):
        assert FasterWhisperServerSTT().available() is False


def test_available_returns_false_on_connection_refused():
    from iris.audio.stt import FasterWhisperServerSTT
    import urllib.error
    with patch("iris.audio.stt.urllib.request.urlopen",
               side_effect=urllib.error.URLError("Connection refused")):
        assert FasterWhisperServerSTT().available() is False


def test_available_returns_false_on_timeout():
    from iris.audio.stt import FasterWhisperServerSTT
    import socket
    with patch("iris.audio.stt.urllib.request.urlopen",
               side_effect=socket.timeout("timed out")):
        assert FasterWhisperServerSTT().available() is False


def test_available_returns_false_on_json_error():
    from iris.audio.stt import FasterWhisperServerSTT
    with patch("iris.audio.stt.urllib.request.urlopen",
               return_value=_mock_urlopen(200, b"not json")):
        assert FasterWhisperServerSTT().available() is False


# ---------------------------------------------------------------------------
# FasterWhisperServerSTT.transcribe()
# ---------------------------------------------------------------------------

def test_transcribe_returns_text_on_success(tmp_path):
    from iris.audio.stt import FasterWhisperServerSTT
    wav = tmp_path / "test.wav"
    wav.write_bytes(b"RIFF" + b"\x00" * 40)
    body = json.dumps({"text": "hello world"}).encode()
    with patch("iris.audio.stt.urllib.request.urlopen",
               return_value=_mock_urlopen(200, body)):
        result = FasterWhisperServerSTT().transcribe(str(wav))
    assert result == "hello world"


def test_transcribe_raises_stt_error_on_server_500(tmp_path):
    from iris.audio.stt import FasterWhisperServerSTT, STTError
    import urllib.error
    wav = tmp_path / "test.wav"
    wav.write_bytes(b"RIFF" + b"\x00" * 40)
    with patch("iris.audio.stt.urllib.request.urlopen",
               side_effect=urllib.error.HTTPError(
                   url="", code=500, msg="Internal Server Error", hdrs=None, fp=None)):
        with pytest.raises(STTError):
            FasterWhisperServerSTT().transcribe(str(wav))


# ---------------------------------------------------------------------------
# KokoroServerTTS.available()
# ---------------------------------------------------------------------------

def test_tts_available_returns_true_when_ready():
    from iris.audio.tts import KokoroServerTTS
    body = json.dumps({"ready": True, "status": "ok"}).encode()
    with patch("iris.audio.tts.urllib.request.urlopen",
               return_value=_mock_urlopen(200, body)):
        assert KokoroServerTTS().available() is True


def test_tts_available_returns_false_on_connection_refused():
    from iris.audio.tts import KokoroServerTTS
    import urllib.error
    with patch("iris.audio.tts.urllib.request.urlopen",
               side_effect=urllib.error.URLError("Connection refused")):
        assert KokoroServerTTS().available() is False


def test_tts_available_returns_false_on_timeout():
    from iris.audio.tts import KokoroServerTTS
    import socket
    with patch("iris.audio.tts.urllib.request.urlopen",
               side_effect=socket.timeout("timed out")):
        assert KokoroServerTTS().available() is False


# ---------------------------------------------------------------------------
# KokoroServerTTS.synth()
# ---------------------------------------------------------------------------

def test_synth_returns_temp_file_path_with_wav_bytes():
    from iris.audio.tts import KokoroServerTTS
    fake_wav = b"RIFF" + b"\x00" * 40
    with patch("iris.audio.tts.urllib.request.urlopen",
               return_value=_mock_urlopen(200, fake_wav)):
        path = KokoroServerTTS().synth("hello", voice="af_sky", speed=1.0)
    assert path.endswith(".wav")
    assert os.path.exists(path)
    with open(path, "rb") as f:
        assert f.read() == fake_wav
    os.unlink(path)


def test_synth_raises_tts_error_on_server_error():
    from iris.audio.tts import KokoroServerTTS, TTSError
    import urllib.error
    with patch("iris.audio.tts.urllib.request.urlopen",
               side_effect=urllib.error.HTTPError(
                   url="", code=500, msg="Internal Server Error", hdrs=None, fp=None)):
        with pytest.raises(TTSError):
            KokoroServerTTS().synth("hello")


# ---------------------------------------------------------------------------
# Fallback to subprocess when server unavailable
# ---------------------------------------------------------------------------

def test_default_stt_falls_back_to_subprocess_when_server_unavailable():
    from iris.audio.stt import FasterWhisperSTT, default_stt
    import urllib.error
    with patch("iris.audio.stt.urllib.request.urlopen",
               side_effect=urllib.error.URLError("refused")):
        stt = default_stt()
    assert isinstance(stt, FasterWhisperSTT)


def test_default_tts_falls_back_to_subprocess_when_server_unavailable():
    from iris.audio.tts import KokoroTTS, default_tts
    import urllib.error
    with patch("iris.audio.tts.urllib.request.urlopen",
               side_effect=urllib.error.URLError("refused")):
        tts = default_tts()
    assert isinstance(tts, KokoroTTS)


# ---------------------------------------------------------------------------
# Env var overrides
# ---------------------------------------------------------------------------

def test_iris_stt_server_url_env_override(monkeypatch):
    from iris.audio.stt import FasterWhisperServerSTT
    monkeypatch.setenv("IRIS_STT_SERVER_URL", "http://192.168.1.100:8082")
    stt = FasterWhisperServerSTT()
    assert "192.168.1.100" in stt._server_url


def test_iris_tts_server_url_env_override(monkeypatch):
    from iris.audio.tts import KokoroServerTTS
    monkeypatch.setenv("IRIS_TTS_SERVER_URL", "http://192.168.1.100:8083")
    tts = KokoroServerTTS()
    assert "192.168.1.100" in tts._server_url
