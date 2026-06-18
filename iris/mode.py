"""IrisMode state machine — surface and audio context."""
from __future__ import annotations

from collections.abc import Callable
from enum import Enum


class IrisMode(Enum):
    OUT_OF_CALL = "out_of_call"
    IN_CALL = "in_call"


class ModeManager:
    """Holds current IrisMode and fires registered callbacks on transition."""

    def __init__(self, initial: IrisMode = IrisMode.OUT_OF_CALL) -> None:
        self._mode = initial
        self._callbacks: list[Callable[[IrisMode], None]] = []

    def on_mode_change(self, cb: Callable[[IrisMode], None]) -> None:
        self._callbacks.append(cb)

    @property
    def mode(self) -> IrisMode:
        return self._mode

    def set_mode(self, mode: IrisMode) -> None:
        if mode == self._mode:
            return
        self._mode = mode
        for cb in self._callbacks:
            cb(mode)
