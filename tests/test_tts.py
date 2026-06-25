"""Tests for the TTS providers. No model, no audio, no network required —
the subprocess is mocked, so these run anywhere (incl. CI on Python 3.14)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from iris.audio.tts import EspeakTTS, KokoroTTS, default_tts

# --- EspeakTTS -----------------------------------------------------------------

def test_espeak_synth_builds_command_and_returns_wav() -> None:
    with patch("iris.audio.tts.subprocess.run") as run:
        out = EspeakTTS(voice="en", rate_wpm=165).synth("hello")
    assert out.endswith(".wav")
    cmd = run.call_args[0][0]
    assert cmd[0] == "espeak-ng"
    assert "hello" in cmd
    assert "-w" in cmd  # writes a WAV file


# --- KokoroTTS -----------------------------------------------------------------

def _kokoro() -> KokoroTTS:
    return KokoroTTS(
        voice="af_heart", python="/x/py", model="/x/m.onnx", voices="/x/v.bin"
    )


def test_kokoro_synth_is_network_isolated_by_default() -> None:
    with patch("iris.audio.tts.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stderr="")
        out = _kokoro().synth("hi there")
    assert out.endswith(".wav")
    cmd = run.call_args[0][0]
    assert cmd[:3] == ["unshare", "-rn", "/x/py"]  # no-network namespace
    assert "/x/m.onnx" in cmd and "/x/v.bin" in cmd
    assert "--voice" in cmd and "af_heart" in cmd


def test_kokoro_synth_can_disable_isolation() -> None:
    tts = KokoroTTS(python="/x/py", model="/x/m", voices="/x/v", isolate=False)
    with patch("iris.audio.tts.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stderr="")
        tts.synth("hi")
    cmd = run.call_args[0][0]
    assert cmd[0] == "/x/py"  # no unshare prefix


def test_kokoro_synth_raises_on_failure() -> None:
    with patch("iris.audio.tts.subprocess.run") as run:
        run.return_value = MagicMock(returncode=1, stderr="boom")
        with pytest.raises(RuntimeError, match="kokoro synth failed"):
            _kokoro().synth("hi")


def test_kokoro_unavailable_when_paths_missing() -> None:
    assert KokoroTTS(python="/no/py", model="/no/m", voices="/no/v").available() is False


# --- default_tts ---------------------------------------------------------------

def test_default_tts_falls_back_to_kokoro_subprocess_when_server_unavailable() -> None:
    import urllib.error
    with patch("iris.audio.tts.urllib.request.urlopen",
               side_effect=urllib.error.URLError("refused")):
        assert isinstance(default_tts(), KokoroTTS)


def test_default_tts_prefers_server_when_available() -> None:
    from iris.audio.tts import KokoroServerTTS

    with patch.object(KokoroServerTTS, "available", return_value=True):
        assert isinstance(default_tts(), KokoroServerTTS)
