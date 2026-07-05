"""_api_key() — shared LLM api-key resolution for PostCallEnricher and
PostCallRecapGenerator (ti-ah76a / ti-6a1y3).

Promoted verbatim from PostCallEnricher._api_key() to iris/capture/_llm_common.py
so both LLM call-sites share one gating helper -- never had dedicated tests
under either name, so this closes that gap alongside the new recap suite.
"""
from __future__ import annotations

from types import SimpleNamespace

from iris.capture._llm_common import _api_key


def test_api_key_from_cfg_top_level_attr():
    cfg = SimpleNamespace(anthropic_api_key="key-top-level")
    assert _api_key(cfg) == "key-top-level"


def test_api_key_from_cfg_call_card_nested_attr():
    cfg = SimpleNamespace(call_card=SimpleNamespace(anthropic_api_key="key-nested"))
    assert _api_key(cfg) == "key-nested"


def test_api_key_falls_through_to_nested_attr_when_top_level_is_empty():
    cfg = SimpleNamespace(
        anthropic_api_key="", call_card=SimpleNamespace(anthropic_api_key="key-nested"),
    )
    assert _api_key(cfg) == "key-nested"


def test_api_key_falls_back_to_iris_env_var(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("IRIS_ANTHROPIC_API_KEY", "iris-env-key")
    assert _api_key(SimpleNamespace()) == "iris-env-key"


def test_api_key_falls_back_to_anthropic_env_var(monkeypatch):
    monkeypatch.delenv("IRIS_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-env-key")
    assert _api_key(SimpleNamespace()) == "anthropic-env-key"


def test_api_key_iris_env_var_takes_precedence_over_anthropic_env_var(monkeypatch):
    monkeypatch.setenv("IRIS_ANTHROPIC_API_KEY", "iris-env-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-env-key")
    assert _api_key(SimpleNamespace()) == "iris-env-key"


def test_api_key_returns_empty_string_when_nothing_configured(monkeypatch):
    monkeypatch.delenv("IRIS_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert _api_key(SimpleNamespace()) == ""
