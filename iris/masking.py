"""Latency masking — keep slow lanes from feeling slow, never hang, always stoppable.

Two helpers:
- ``run_with_filler`` — fire a one-shot filler if work passes a threshold.
- ``run_with_masking`` — the real deal: fire a filler, **repeat** it while the
  work lags, **abandon** it at a hard deadline (return ``fallback``), and let the
  user **interrupt** at any time (Ctrl-C / a set ``stop_event`` -> return
  ``interrupted``). The interrupt is a guaranteed-local stop: SIGINT can't be
  swallowed by a hung model or a dead network, so the pause sounds can always be
  cut.

The filler is a printed line in the REPL; an audible clip in voice mode.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def run_with_filler(
    work: Callable[[], T],
    threshold_s: float,
    on_filler: Callable[[], None] | None = None,
) -> T:
    """Run ``work()``; if still running after ``threshold_s``, fire ``on_filler``
    once (concurrently), then block for the result. Exceptions propagate."""
    box: dict[str, object] = {}

    def _run() -> None:
        try:
            box["value"] = work()
        except BaseException as exc:  # re-raised on the caller thread
            box["error"] = exc

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(threshold_s)
    if thread.is_alive():
        if on_filler is not None:
            on_filler()
        thread.join()
    if "error" in box:
        raise box["error"]  # type: ignore[misc]
    return box["value"]  # type: ignore[return-value]


def run_with_masking(
    work: Callable[[], T],
    *,
    first_filler_s: float,
    repeat_filler_s: float,
    deadline_s: float,
    on_filler: Callable[[int], None] | None = None,
    fallback: T | None = None,
    interrupted: T | None = None,
    stop_event: threading.Event | None = None,
) -> T | None:
    """Run ``work()`` on a background thread with latency masking:

    - fire ``on_filler(i)`` at ``first_filler_s``, then every ``repeat_filler_s``
      (i = 0, 1, 2, ...) so a long wait keeps getting "umm…" / "let me think";
    - if the user interrupts (Ctrl-C, or a set ``stop_event``), abandon the work
      and return ``interrupted`` — a guaranteed-local stop that doesn't depend on
      the model or network;
    - if ``work`` exceeds ``deadline_s``, abandon it and return ``fallback``;
    - otherwise return ``work()``'s result. Exceptions propagate (pre-deadline).
    """
    box: dict[str, object] = {}
    done = threading.Event()

    def _run() -> None:
        try:
            box["value"] = work()
        except BaseException as exc:  # re-raised on the caller thread
            box["error"] = exc
        finally:
            done.set()

    threading.Thread(target=_run, daemon=True).start()
    start = time.perf_counter()

    try:
        if not done.wait(first_filler_s):  # crossed the first threshold, still working
            i = 0
            while True:
                if stop_event is not None and stop_event.is_set():
                    return interrupted
                if on_filler is not None:
                    on_filler(i)
                i += 1
                remaining = deadline_s - (time.perf_counter() - start)
                if remaining <= 0:
                    return fallback  # deadline blown — abandon, fall back
                if done.wait(min(repeat_filler_s, remaining)):
                    break  # work finished within the deadline
    except KeyboardInterrupt:
        return interrupted  # the can't-fail local stop

    if "error" in box:
        raise box["error"]  # type: ignore[misc]
    return box["value"]  # type: ignore[return-value]
