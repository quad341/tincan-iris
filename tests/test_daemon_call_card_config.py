"""Tests for iris.daemon.__main__'s Call Card config wiring (ti-ajkht/ti-sqv1v).

_load_call_card_config() sources the same env > config.toml > default precedence
as iris.settings (see tests/test_settings.py); the first three tests exercise
that directly.

The last test proves main() itself forwards _load_call_call_config()'s result
into CallCardHost(cfg=...) instead of the old cfg=None. CallCardHost is patched
at its import source (iris.daemon.call_card_host.CallCardHost -- the module
main()'s lazy `from .call_card_host import CallCardHost` resolves against) to
raise immediately with the received cfg. That happens well before main() reaches
any of its real I/O (PID file, socket, D-Bus, signal handlers, the blocking
stop_event.wait()) -- all of that lives later in main()'s linear body, so this
never runs it.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from iris import settings
from iris.daemon.__main__ import _load_call_card_config

_ENV_VARS = ("IRIS_HOME", "IRIS_CONFIG", "IRIS_CALL_CARD_DISCLOSURE_SCRIPT", "IRIS_DB")


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    settings.reload()
    yield
    settings.reload()


def _write_config(tmp_path, body, monkeypatch):
    p = tmp_path / "config.toml"
    p.write_text(body)
    monkeypatch.setenv("IRIS_CONFIG", str(p))
    settings.reload()
    return p


# ---------------------------------------------------------------------------
# _load_call_card_config()
# ---------------------------------------------------------------------------

def test_load_call_card_config_reads_config_toml(tmp_path, monkeypatch):
    _write_config(tmp_path, '[call_card]\ndisclosure_script = "custom disclosure"\n', monkeypatch)
    cfg = _load_call_card_config()
    assert cfg.call_card_disclosure_script == "custom disclosure"


def test_load_call_card_config_defaults_to_empty_when_key_omitted():
    cfg = _load_call_card_config()
    assert cfg.call_card_disclosure_script == ""


def test_load_call_card_config_env_overrides_config_toml(tmp_path, monkeypatch):
    _write_config(tmp_path, '[call_card]\ndisclosure_script = "from config.toml"\n', monkeypatch)
    monkeypatch.setenv("IRIS_CALL_CARD_DISCLOSURE_SCRIPT", "from env")
    cfg = _load_call_card_config()
    assert cfg.call_card_disclosure_script == "from env"


# ---------------------------------------------------------------------------
# main() forwards _load_call_card_config()'s result to CallCardHost
# ---------------------------------------------------------------------------

class _Captured(Exception):
    def __init__(self, cfg):
        self.cfg = cfg


def test_main_passes_loaded_config_to_call_card_host(tmp_path, monkeypatch):
    _write_config(tmp_path, '[call_card]\ndisclosure_script = "wired end-to-end"\n', monkeypatch)
    monkeypatch.setenv("IRIS_DB", str(tmp_path / "test.db"))

    def _raise_with_cfg(*, store, processor, api, cfg, tts=None):
        raise _Captured(cfg)

    from iris.daemon import __main__ as daemon_main

    captured_cfg = None
    with patch("iris.daemon.call_card_host.CallCardHost", side_effect=_raise_with_cfg):
        try:
            daemon_main.main()
        except _Captured as exc:
            captured_cfg = exc.cfg
        else:
            pytest.fail("main() did not construct CallCardHost -- nothing captured")

    assert captured_cfg is not None
    assert captured_cfg.call_card_disclosure_script == "wired end-to-end"


# ---------------------------------------------------------------------------
# main() forwards a real TTS instance to CallCardHost (ti-iv69h)
# ---------------------------------------------------------------------------

class _CapturedTTS(Exception):
    def __init__(self, tts):
        self.tts = tts


def test_main_passes_default_tts_to_call_card_host(tmp_path, monkeypatch):
    monkeypatch.setenv("IRIS_DB", str(tmp_path / "test.db"))

    def _raise_with_tts(*, store, processor, api, cfg, tts=None):
        raise _CapturedTTS(tts)

    from iris.daemon import __main__ as daemon_main

    sentinel_tts = object()
    captured_tts = None
    with patch("iris.daemon.call_card_host.CallCardHost", side_effect=_raise_with_tts), \
         patch("iris.audio.tts.default_tts", return_value=sentinel_tts) as mock_default_tts:
        try:
            daemon_main.main()
        except _CapturedTTS as exc:
            captured_tts = exc.tts
        else:
            pytest.fail("main() did not construct CallCardHost -- nothing captured")

    mock_default_tts.assert_called_once_with()
    assert captured_tts is sentinel_tts
