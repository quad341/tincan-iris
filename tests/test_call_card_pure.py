"""Pure-function tests for call_card.py helpers (no Textual required)."""
from __future__ import annotations

from iris.console._confidence_bar import render_confidence_bar as _render_confidence_bar


def test_high_confidence_is_green():
    result = _render_confidence_bar(0.90)
    assert "green" in result
    assert "90%" in result


def test_bucket_boundary_85_is_green():
    result = _render_confidence_bar(0.85)
    assert "green" in result


def test_bucket_boundary_84_is_amber():
    result = _render_confidence_bar(0.84)
    assert "#f59e0b" in result


def test_bucket_boundary_60_is_amber():
    result = _render_confidence_bar(0.60)
    assert "#f59e0b" in result


def test_bucket_below_60_is_red():
    result = _render_confidence_bar(0.59)
    assert "red" in result


def test_zero_confidence_all_empty():
    result = _render_confidence_bar(0.0)
    assert "0%" in result
    assert "▓" not in result


def test_full_confidence_all_filled():
    result = _render_confidence_bar(1.0)
    assert "100%" in result
    assert "░" not in result


def test_bar_width_ten_chars():
    for conf in (0.0, 0.5, 1.0):
        result = _render_confidence_bar(conf)
        # Strip markup tags to get raw bar chars
        bar_chars = result.replace("[green]", "").replace("[/green]", "")
        block_count = bar_chars.count("▓") + bar_chars.count("░")
        assert block_count == 10, f"Expected 10 bar chars for {conf}, got {block_count}"
