"""Latency harness — instrument every turn from day one.

Iris lives or dies on responsiveness, so the brain records a timeline of stage
timestamps on every turn rather than bolting measurement on later. See
``docs/LATENCY.md`` for the measured per-lane budget this is meant to defend.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Timeline:
    """Records wall-clock marks (seconds since start) across a single turn."""

    _t0: float = field(default_factory=time.perf_counter)
    marks: list[tuple[str, float]] = field(default_factory=list)

    def mark(self, stage: str) -> None:
        """Record the elapsed time at the end of ``stage``."""
        self.marks.append((stage, time.perf_counter() - self._t0))

    @property
    def total_ms(self) -> float:
        return self.marks[-1][1] * 1000 if self.marks else 0.0

    def summary(self) -> str:
        """One-line per-stage breakdown, e.g. ``[412ms total] tier0=+0ms tier1=+412ms``."""
        if not self.marks:
            return "(no marks)"
        parts, prev = [], 0.0
        for stage, t in self.marks:
            parts.append(f"{stage}=+{(t - prev) * 1000:.0f}ms")
            prev = t
        return f"[{self.total_ms:.0f}ms total] " + " ".join(parts)
