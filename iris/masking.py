"""Latency masking — keep slow lanes from feeling slow.

When a lane might take a while (the cloud tier especially), we don't want dead
air. ``run_with_filler`` runs the work on a thread and, if it hasn't finished by
a threshold, fires a one-shot filler *in parallel* with the work — the
operator's "timer to inject a pause" idea. Today the filler is a printed
``(umm, one sec)`` in the REPL; once TTS lands it becomes an audible clip.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def run_with_filler(
    work: Callable[[], T],
    threshold_s: float,
    on_filler: Callable[[], None] | None = None,
) -> T:
    """Run ``work()``; if it is still running after ``threshold_s``, fire
    ``on_filler`` once (concurrently with ``work``), then block for ``work`` to
    finish and return its result. Exceptions raised by ``work`` propagate to the
    caller; a filler that has already fired is not retracted.
    """
    box: dict[str, object] = {}

    def _run() -> None:
        try:
            box["value"] = work()
        except BaseException as exc:  # noqa: BLE001 — re-raised on the caller thread
            box["error"] = exc

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(threshold_s)
    if thread.is_alive():  # past the threshold and still working -> filler
        if on_filler is not None:
            on_filler()
        thread.join()  # wait for the real result
    if "error" in box:
        raise box["error"]  # type: ignore[misc]
    return box["value"]  # type: ignore[return-value]
