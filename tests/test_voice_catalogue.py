"""Tests for iris/audio/voice_catalogue.py — voice_for_lang() lookup and TOML override.

Bead: ti-5crlr (validator phase) — written BEFORE builder implementation (TDD red phase).
Fails until builder implements voice_catalogue.py per ADR ti-joq2.

Coverage map (4 acceptance criteria from ti-joq2.1):
  ①  voice_for_lang('es') returns the ef_dalia VoiceEntry
  ②  voice_for_lang('es-MX') base-tag-strips to 'es' and returns ef_dalia entry
  ③  voice_for_lang('xx-unknown') returns espeak fallback with voice_id=''
  ④  [voice.catalogue] TOML override replaces individual entries
"""
from __future__ import annotations

import pytest

from iris.audio.voice_catalogue import VoiceEntry, voice_for_lang


# ---------------------------------------------------------------------------
# Criteria ① — exact match for 'es' returns ef_dalia
# ---------------------------------------------------------------------------

def test_voice_for_lang_es_returns_ef_dalia():
    entry = voice_for_lang("es", overrides={})
    assert entry == VoiceEntry(kokoro_lang="es", voice_id="ef_dalia", espeak_voice="es")


# ---------------------------------------------------------------------------
# Criteria ② — 'es-MX' base-tag-strips to 'es' and returns ef_dalia entry
# ---------------------------------------------------------------------------

def test_voice_for_lang_es_mx_strips_to_es():
    entry = voice_for_lang("es-MX", overrides={})
    assert entry == VoiceEntry(kokoro_lang="es", voice_id="ef_dalia", espeak_voice="es")


def test_voice_for_lang_es_mx_case_insensitive():
    """Normalization lowercases before matching."""
    entry = voice_for_lang("ES-MX", overrides={})
    assert entry == VoiceEntry(kokoro_lang="es", voice_id="ef_dalia", espeak_voice="es")


# ---------------------------------------------------------------------------
# Criteria ③ — unknown tag returns espeak fallback with voice_id=''
# ---------------------------------------------------------------------------

def test_voice_for_lang_unknown_returns_espeak_fallback():
    entry = voice_for_lang("xx-unknown", overrides={})
    assert entry.voice_id == ""
    assert entry.espeak_voice == "xx"
    assert entry.kokoro_lang == "xx"


def test_voice_for_lang_unknown_is_voiceentry():
    entry = voice_for_lang("xx-unknown", overrides={})
    assert isinstance(entry, VoiceEntry)


# ---------------------------------------------------------------------------
# Criteria ④ — [voice.catalogue] TOML override replaces individual entries
# ---------------------------------------------------------------------------

def test_toml_override_replaces_entry(tmp_path, monkeypatch):
    """TOML override at [voice.catalogue] wins over DEFAULT_CATALOGUE."""
    config = tmp_path / "config.toml"
    config.write_text(
        "[voice.catalogue.es]\n"
        'kokoro_lang = "es"\n'
        'voice_id = "custom_voice"\n'
        'espeak_voice = "es"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    entry = voice_for_lang("es")
    assert entry.voice_id == "custom_voice"


def test_toml_override_does_not_affect_other_entries(tmp_path, monkeypatch):
    """Overriding 'es' leaves 'en' untouched."""
    config = tmp_path / "config.toml"
    config.write_text(
        "[voice.catalogue.es]\n"
        'kokoro_lang = "es"\n'
        'voice_id = "custom_voice"\n'
        'espeak_voice = "es"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    entry = voice_for_lang("en")
    assert entry.voice_id == "af_heart"


def test_toml_override_new_language(tmp_path, monkeypatch):
    """Override can introduce a new language tag not in DEFAULT_CATALOGUE."""
    config = tmp_path / "config.toml"
    config.write_text(
        "[voice.catalogue.tlh]\n"
        'kokoro_lang = "tlh"\n'
        'voice_id = "klingon_voice"\n'
        'espeak_voice = "tlh"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    entry = voice_for_lang("tlh")
    assert entry.voice_id == "klingon_voice"
    assert entry.espeak_voice == "tlh"


def test_no_config_toml_uses_defaults(tmp_path, monkeypatch):
    """Missing config.toml falls back to DEFAULT_CATALOGUE without error."""
    monkeypatch.chdir(tmp_path)
    entry = voice_for_lang("es")
    assert entry.voice_id == "ef_dalia"
