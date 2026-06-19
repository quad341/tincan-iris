"""Tests for iris.settings — env > config.toml > default resolution.

The config file read is cached, so each test resets via settings.reload() (the
autouse fixture) and writes its own config under tmp_path pointed at by
IRIS_CONFIG.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from iris import settings

_ENV_VARS = (
    "IRIS_HOME", "IRIS_CONFIG", "XDG_DATA_HOME",
    "IRIS_AUDIO", "IRIS_AEC", "IRIS_KOKORO_VOICE", "IRIS_WHISPER_MODEL_SIZE",
)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    settings.reload()
    yield
    settings.reload()


def _write_config(tmp_path, body: str, monkeypatch) -> Path:
    p = tmp_path / "config.toml"
    p.write_text(body)
    monkeypatch.setenv("IRIS_CONFIG", str(p))
    settings.reload()
    return p


# --- iris_home / config_path -------------------------------------------------

def test_iris_home_default():
    assert settings.iris_home() == Path.home() / ".local" / "share" / "iris"


def test_iris_home_override(monkeypatch):
    monkeypatch.setenv("IRIS_HOME", "/srv/iris")
    assert settings.iris_home() == Path("/srv/iris")


def test_iris_home_xdg(monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", "/xdg")
    assert settings.iris_home() == Path("/xdg/iris")


def test_config_path_defaults_under_home(monkeypatch):
    monkeypatch.setenv("IRIS_HOME", "/srv/iris")
    assert settings.config_path() == Path("/srv/iris/config.toml")


def test_config_path_iris_config_override(monkeypatch):
    monkeypatch.setenv("IRIS_CONFIG", "/etc/iris.toml")
    assert settings.config_path() == Path("/etc/iris.toml")


# --- get precedence ----------------------------------------------------------

def test_get_default_when_nothing_set():
    assert settings.get("IRIS_AUDIO", "default") == "default"
    assert settings.get("IRIS_AUDIO") is None


def test_get_reads_config_file(tmp_path, monkeypatch):
    _write_config(tmp_path, '[audio]\nmode = "tincan-sco"\n', monkeypatch)
    assert settings.get("IRIS_AUDIO") == "tincan-sco"


def test_env_overrides_config_nonempty(tmp_path, monkeypatch):
    _write_config(tmp_path, '[audio]\nmode = "tincan-sco"\n', monkeypatch)
    monkeypatch.setenv("IRIS_AUDIO", "sco")
    assert settings.get("IRIS_AUDIO") == "sco"


def test_explicit_empty_env_overrides_config(tmp_path, monkeypatch):
    _write_config(tmp_path, '[audio]\nmode = "tincan-sco"\n', monkeypatch)
    monkeypatch.setenv("IRIS_AUDIO", "")   # set-but-empty is still an explicit override
    assert settings.get("IRIS_AUDIO") == ""


# --- bool coercion -----------------------------------------------------------

def test_bool_from_config_true(tmp_path, monkeypatch):
    _write_config(tmp_path, "[audio]\naec = true\n", monkeypatch)
    assert settings.get_bool("IRIS_AEC") is True


def test_bool_from_config_false(tmp_path, monkeypatch):
    _write_config(tmp_path, "[audio]\naec = false\n", monkeypatch)
    assert settings.get_bool("IRIS_AEC") is False


def test_bool_default_when_unset():
    assert settings.get_bool("IRIS_AEC") is False
    assert settings.get_bool("IRIS_AEC", default=True) is True


# --- mapping + robustness ----------------------------------------------------

def test_voice_and_size_keys(tmp_path, monkeypatch):
    _write_config(
        tmp_path,
        '[voice]\nkokoro_voice = "bf_emma"\n[assets]\nwhisper_model_size = "medium.en"\n',
        monkeypatch,
    )
    assert settings.get("IRIS_KOKORO_VOICE") == "bf_emma"
    assert settings.get("IRIS_WHISPER_MODEL_SIZE") == "medium.en"


def test_unmapped_key_ignored(tmp_path, monkeypatch):
    _write_config(tmp_path, '[nope]\nfoo = "bar"\n', monkeypatch)
    assert settings.get("IRIS_NOPE") is None


def test_missing_file_is_silent(tmp_path, monkeypatch):
    monkeypatch.setenv("IRIS_CONFIG", str(tmp_path / "absent.toml"))
    settings.reload()
    assert settings.get("IRIS_AUDIO", "d") == "d"


def test_malformed_file_is_silent(tmp_path, monkeypatch):
    p = tmp_path / "config.toml"
    p.write_text("this is not valid toml = = =")
    monkeypatch.setenv("IRIS_CONFIG", str(p))
    settings.reload()
    assert settings.get("IRIS_AUDIO", "d") == "d"
