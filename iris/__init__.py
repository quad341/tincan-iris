"""Iris — a local-first voice-agent brain that rides tincan.

This package is the *brain* tier: a tiered router that keeps the common path
local and fast, escalating to a cloud frontier model only for open-ended
language. See ``docs/adr/0001`` for the routing + latency rationale and
``docs/LATENCY.md`` for the measured budget.
"""

__version__ = "0.0.1"
