"""Tests for the latency-masking helper. No network / cloud required."""
from __future__ import annotations

import time

from iris.masking import run_with_filler


def test_fast_work_does_not_fire_filler() -> None:
    fired: list[int] = []
    out = run_with_filler(lambda: "done", threshold_s=0.5, on_filler=lambda: fired.append(1))
    assert out == "done"
    assert fired == []  # finished before the threshold -> no filler


def test_slow_work_fires_filler_once() -> None:
    fired: list[int] = []

    def slow() -> str:
        time.sleep(0.25)
        return "slow-done"

    out = run_with_filler(slow, threshold_s=0.1, on_filler=lambda: fired.append(1))
    assert out == "slow-done"
    assert fired == [1]  # crossed the threshold -> filler fired exactly once


def test_exception_propagates() -> None:
    def boom() -> str:
        raise ValueError("nope")

    try:
        run_with_filler(boom, threshold_s=0.1)
    except ValueError as exc:
        assert str(exc) == "nope"
    else:  # pragma: no cover
        raise AssertionError("expected ValueError to propagate")


def test_no_filler_callback_is_safe() -> None:
    out = run_with_filler(lambda: 42, threshold_s=0.0)  # None callback, immediate threshold
    assert out == 42
