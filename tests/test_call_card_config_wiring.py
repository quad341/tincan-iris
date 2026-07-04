"""Regression: a real config.toml value must reach CallCardHost / PostCallEnricher.

Covers ti-ajkht: iris/daemon/__main__.py used to construct CallCardHost with
cfg=None, so CallCardHost._disclosure_script and PostCallEnricher._api_key's
cfg-based lookups were permanently unreachable in the real daemon. These tests
build cfg the same way __main__.py now does — via iris.config.load() reading an
actual file on disk — rather than a directly-constructed Config(...), since the
bug was specifically that no real *loaded* config ever reached these classes.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from iris import config as iris_config
from iris.capture.enricher import _api_key
from iris.daemon.call_card_host import _DEFAULT_DISCLOSURE, CallCardHost


def _host(cfg: object) -> CallCardHost:
    return CallCardHost(store=MagicMock(), processor=MagicMock(), api=MagicMock(), cfg=cfg)


def test_disclosure_script_falls_back_when_cfg_is_none():
    assert _host(None)._disclosure_script == _DEFAULT_DISCLOSURE


def test_disclosure_script_falls_back_with_default_config():
    assert _host(iris_config.DEFAULT)._disclosure_script == _DEFAULT_DISCLOSURE


def test_disclosure_script_reads_a_real_config_toml_file(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[call_card]\ndisclosure_script = "Heads up — an AI note-taker is listening."\n')
    cfg = iris_config.load(p)  # loaded from disk, not Config(call_card_disclosure_script=...)

    assert _host(cfg)._disclosure_script == "Heads up — an AI note-taker is listening."


def test_disclosure_script_still_falls_back_when_toml_omits_the_key(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[call_card]\n# disclosure_script intentionally omitted\n')
    cfg = iris_config.load(p)

    assert _host(cfg)._disclosure_script == _DEFAULT_DISCLOSURE


def test_api_key_lookup_unaffected_by_a_real_loaded_config(monkeypatch, tmp_path):
    """cfg=None -> cfg=<real Config> must not change _api_key's env-var fallback.

    Config carries no anthropic_api_key field (that's a secret; it stays
    env/secrets.toml-only per iris/settings.py's convention), so a real Config
    still falls through to the same env-var lookup a bare None did.
    """
    monkeypatch.delenv("IRIS_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cfg = iris_config.load(tmp_path / "absent.toml")

    assert _api_key(None) == _api_key(cfg) == ""

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-env")
    assert _api_key(None) == _api_key(cfg) == "sk-from-env"
