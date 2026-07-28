"""Tests for the latency-masking helpers. No network / cloud required."""
from __future__ import annotations

import time

from iris.masking import run_with_filler, run_with_masking

# --- run_with_filler (one-shot) ------------------------------------------------

def test_fast_work_does_not_fire_filler() -> None:
    fired: list[int] = []
    out = run_with_filler(lambda: "done", threshold_s=0.5, on_filler=lambda: fired.append(1))
    assert out == "done"
    assert fired == []


def test_slow_work_fires_filler_once() -> None:
    fired: list[int] = []

    def slow() -> str:
        time.sleep(0.25)
        return "slow-done"

    out = run_with_filler(slow, threshold_s=0.1, on_filler=lambda: fired.append(1))
    assert out == "slow-done"
    assert fired == [1]


def test_filler_exception_propagates() -> None:
    def boom() -> str:
        raise ValueError("nope")

    try:
        run_with_filler(boom, threshold_s=0.1)
    except ValueError as exc:
        assert str(exc) == "nope"
    else:  # pragma: no cover
        raise AssertionError("expected ValueError to propagate")


# --- run_with_masking (repeat fillers + deadline fallback) ---------------------

def test_masking_fast_returns_result_no_filler() -> None:
    fired: list[int] = []
    out = run_with_masking(
        lambda: "quick", first_filler_s=0.5, repeat_filler_s=0.2,
        deadline_s=2.0, on_filler=lambda i: fired.append(i), fallback="FB",
    )
    assert out == "quick"
    assert fired == []


def test_masking_repeats_fillers_then_returns() -> None:
    fired: list[int] = []

    def slow() -> str:
        time.sleep(0.5)
        return "real"

    out = run_with_masking(
        slow, first_filler_s=0.1, repeat_filler_s=0.1,
        deadline_s=2.0, on_filler=lambda i: fired.append(i), fallback="FB",
    )
    assert out == "real"
    assert fired and fired == list(range(len(fired)))  # fired 0, 1, 2, ...


def test_masking_deadline_returns_fallback() -> None:
    fired: list[int] = []

    def too_slow() -> str:
        time.sleep(5.0)
        return "never seen"

    t0 = time.perf_counter()
    out = run_with_masking(
        too_slow, first_filler_s=0.1, repeat_filler_s=0.1,
        deadline_s=0.4, on_filler=lambda i: fired.append(i), fallback="FALLBACK",
    )
    assert out == "FALLBACK"
    assert time.perf_counter() - t0 < 1.0  # bailed at the deadline, not 5 s
    assert len(fired) >= 1
