"""Tests for CallCardHost._disclosure_script (ti-ajkht config wiring).

CallCardHost previously always fell back to _DEFAULT_DISCLOSURE because cfg was
always None at daemon startup (ti-ajkht). These tests cover the property's
branches directly against a constructed CallCardHost -- no CaptureSession
mocking needed since _disclosure_script never touches capture state.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from iris.daemon.call_card_host import _DEFAULT_DISCLOSURE, CallCardHost


def _make_host(cfg):
    return CallCardHost(store=MagicMock(), processor=MagicMock(), api=MagicMock(), cfg=cfg)


def test_disclosure_script_reflects_nonempty_cfg_value():
    cfg = MagicMock(call_card_disclosure_script="Please note this call is recorded.")
    host = _make_host(cfg)
    assert host._disclosure_script == "Please note this call is recorded."


def test_disclosure_script_falls_back_to_default_when_cfg_value_empty():
    cfg = MagicMock(call_card_disclosure_script="")
    host = _make_host(cfg)
    assert host._disclosure_script == _DEFAULT_DISCLOSURE


def test_disclosure_script_falls_back_to_default_when_cfg_lacks_attribute():
    host = _make_host(object())  # no call_card_disclosure_script attribute at all
    assert host._disclosure_script == _DEFAULT_DISCLOSURE


def test_disclosure_script_falls_back_to_default_when_cfg_is_none():
    host = _make_host(None)
    assert host._disclosure_script == _DEFAULT_DISCLOSURE
