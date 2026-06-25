"""Tests for the STT providers. No model, no audio, no network required — the
subprocess is mocked, so these run anywhere (incl. CI on Python 3.14)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from iris.audio.stt import FasterWhisperSTT, FasterWhisperServerSTT, default_stt


def _stt() -> FasterWhisperSTT:
    return FasterWhisperSTT(python="/x/py", model="/x/model")


def test_transcribe_is_network_isolated_by_default() -> None:
    with patch("iris.audio.stt.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stdout="hello world\n", stderr="")
        out = _stt().transcribe("/tmp/a.wav")
    assert out == "hello world"
    cmd = run.call_args[0][0]
    assert cmd[:3] == ["unshare", "-rn", "/x/py"]  # no-network namespace
    assert "/x/model" in cmd and "/tmp/a.wav" in cmd
    assert "--beam-size" in cmd


def test_transcribe_can_disable_isolation() -> None:
    stt = FasterWhisperSTT(python="/x/py", model="/x/m", isolate=False)
    with patch("iris.audio.stt.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stdout="hi", stderr="")
        stt.transcribe("/tmp/a.wav")
    cmd = run.call_args[0][0]
    assert cmd[0] == "/x/py"  # no unshare prefix


def test_transcribe_raises_on_failure() -> None:
    with patch("iris.audio.stt.subprocess.run") as run:
        run.return_value = MagicMock(returncode=1, stdout="", stderr="boom")
        with pytest.raises(RuntimeError, match="whisper transcribe failed"):
            _stt().transcribe("/tmp/a.wav")


def test_unavailable_when_paths_missing() -> None:
    assert FasterWhisperSTT(python="/no/py", model="/no/m").available() is False


def test_default_stt_falls_back_when_server_absent() -> None:
    with patch("iris.audio.stt.FasterWhisperServerSTT.available", return_value=False):
        assert isinstance(default_stt(), FasterWhisperSTT)


def test_default_stt_prefers_server_when_available() -> None:
    from iris.audio.stt import FasterWhisperServerSTT

    with patch("iris.audio.stt.FasterWhisperServerSTT.available", return_value=True):
        assert isinstance(default_stt(), FasterWhisperServerSTT)
