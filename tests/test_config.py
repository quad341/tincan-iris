"""Tests for iris.config.load — config.toml's [call_card] section -> Config.

Mirrors tests/test_settings.py's tmp_path/monkeypatch pattern: each test either
passes an explicit path to load() or points IRIS_CONFIG at a tmp_path file, so
a real config.toml on the machine running these tests is never consulted.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from iris import config


_ENV_VARS = ("IRIS_HOME", "IRIS_CONFIG", "XDG_DATA_HOME")


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def _write(tmp_path, body: str):
    p = tmp_path / "config.toml"
    p.write_text(body)
    return p


def test_load_missing_file_returns_default(tmp_path):
    assert config.load(tmp_path / "absent.toml") == config.DEFAULT


def test_load_malformed_file_returns_default(tmp_path):
    p = _write(tmp_path, "this is not valid toml = = =")
    assert config.load(p) == config.DEFAULT


def test_load_no_call_card_section_returns_default(tmp_path):
    p = _write(tmp_path, '[audio]\nmode = "tincan-sco"\n')
    assert config.load(p) == config.DEFAULT


def test_load_reads_disclosure_script(tmp_path):
    p = _write(tmp_path, '[call_card]\ndisclosure_script = "Custom text."\n')
    assert config.load(p).call_card_disclosure_script == "Custom text."


def test_load_call_card_section_without_disclosure_script_key_uses_default(tmp_path):
    p = _write(tmp_path, "[call_card]\n")
    assert config.load(p) == config.DEFAULT


def test_load_unmapped_call_card_key_ignored(tmp_path):
    p = _write(tmp_path, '[call_card]\nfoo = "bar"\n')
    assert config.load(p) == config.DEFAULT


def test_load_only_overrides_call_card_fields(tmp_path):
    p = _write(tmp_path, '[call_card]\ndisclosure_script = "Custom text."\n')
    result = config.load(p)
    assert result == replace(config.DEFAULT, call_card_disclosure_script="Custom text.")
    # spot-check a couple of unrelated fields are untouched, not just equality-by-luck
    assert result.haiku_enabled == config.DEFAULT.haiku_enabled
    assert result.qwen_base_url == config.DEFAULT.qwen_base_url


def test_load_uses_settings_config_path_when_no_path_given(tmp_path, monkeypatch):
    p = _write(tmp_path, '[call_card]\ndisclosure_script = "From env-resolved path."\n')
    monkeypatch.setenv("IRIS_CONFIG", str(p))
    assert config.load().call_card_disclosure_script == "From env-resolved path."


def test_load_defaults_to_empty_disclosure_script(tmp_path):
    assert config.load(tmp_path / "absent.toml").call_card_disclosure_script == ""
