"""Tests for iris.disclosure — disclosure WAV generation and caching."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock


from iris.disclosure import (
    _disclosure_script,
    _cached_name,
    _write_sidecar,
    ensure_disclosure_wav,
)


# --- script template ---

def test_script_personal():
    s = _disclosure_script("Jim")
    assert "Jim" in s
    assert "Iris" in s
    assert "AI" in s


def test_script_generic():
    s = _disclosure_script("")
    assert "Jim" not in s
    assert "Iris" in s
    assert "AI" in s


def test_script_strips_whitespace():
    assert _disclosure_script("  Jim  ") == _disclosure_script("Jim")


# --- sidecar read/write ---

def test_sidecar_roundtrip(tmp_path):
    wav = tmp_path / "disclosure.wav"
    wav.write_bytes(b"")
    _write_sidecar(wav, "Alice")
    assert _cached_name(wav) == "Alice"


def test_sidecar_missing_returns_empty(tmp_path):
    wav = tmp_path / "disclosure.wav"
    assert _cached_name(wav) == ""


# --- ensure_disclosure_wav ---

def _make_tts(tmp_path, name="synth.wav"):
    tts = MagicMock()
    wav = tmp_path / name
    wav.write_bytes(b"RIFF")
    tts.synth.return_value = str(wav)
    return tts, wav


def test_renders_on_first_call(tmp_path):
    tts, _ = _make_tts(tmp_path, "synth.wav")
    out = tmp_path / "disclosure.wav"
    result = ensure_disclosure_wav("Jim", wav_path=out, tts=tts)
    assert result == out
    assert out.exists()
    tts.synth.assert_called_once()


def test_skips_render_when_up_to_date(tmp_path):
    tts, _ = _make_tts(tmp_path, "synth.wav")
    out = tmp_path / "disclosure.wav"
    # First render
    ensure_disclosure_wav("Jim", wav_path=out, tts=tts)
    # Second call — tts already consumed the synth file; make a new one
    tts2, _ = _make_tts(tmp_path, "synth2.wav")
    tts2.synth.return_value = str(tmp_path / "synth2.wav")
    ensure_disclosure_wav("Jim", wav_path=out, tts=tts2)
    tts2.synth.assert_not_called()


def test_rerenders_on_name_change(tmp_path):
    out = tmp_path / "disclosure.wav"
    tts1, _ = _make_tts(tmp_path, "synth1.wav")
    ensure_disclosure_wav("Jim", wav_path=out, tts=tts1)
    tts2, _ = _make_tts(tmp_path, "synth2.wav")
    ensure_disclosure_wav("Alice", wav_path=out, tts=tts2)
    tts2.synth.assert_called_once()
    # Sidecar must now record the new name
    assert _cached_name(out) == "Alice"


def test_rerenders_when_wav_missing(tmp_path):
    out = tmp_path / "disclosure.wav"
    tts1, _ = _make_tts(tmp_path, "synth1.wav")
    ensure_disclosure_wav("Jim", wav_path=out, tts=tts1)
    out.unlink()  # delete the WAV
    tts2, _ = _make_tts(tmp_path, "synth2.wav")
    ensure_disclosure_wav("Jim", wav_path=out, tts=tts2)
    tts2.synth.assert_called_once()


def test_creates_parent_directory(tmp_path):
    out = tmp_path / "sub" / "disclosure.wav"
    tts, _ = _make_tts(tmp_path, "synth.wav")
    ensure_disclosure_wav("Jim", wav_path=out, tts=tts)
    assert out.exists()


def test_returns_path_object(tmp_path):
    out = tmp_path / "disclosure.wav"
    tts, _ = _make_tts(tmp_path, "synth.wav")
    result = ensure_disclosure_wav("Jim", wav_path=out, tts=tts)
    assert isinstance(result, Path)


def test_generic_script_when_no_operator_name(tmp_path):
    out = tmp_path / "disclosure.wav"
    tts, _ = _make_tts(tmp_path, "synth.wav")
    ensure_disclosure_wav("", wav_path=out, tts=tts)
    script_passed = tts.synth.call_args[0][0]
    assert "Jim" not in script_passed
    assert "Iris" in script_passed


def test_personal_script_contains_operator_name(tmp_path):
    out = tmp_path / "disclosure.wav"
    tts, _ = _make_tts(tmp_path, "synth.wav")
    ensure_disclosure_wav("Alice", wav_path=out, tts=tts)
    script_passed = tts.synth.call_args[0][0]
    assert "Alice" in script_passed
