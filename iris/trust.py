"""Call-level trust model — three-step arm/grant flow.

Levels (ascending privilege):
  NONE  — unarmed; far party restricted to Tier0+Tier1; cloud and auth'd skills blocked.
  LOCAL — armed; operator elevated (FULL), far party still DEMO.
  BOTH  — armed + granted; operator and far party both FULL.

Transition:
  arm()    → NONE (armed-flag set; trust level unchanged)
  grant()  → cycles NONE→LOCAL→BOTH→NONE (only when armed)
  disarm() → clears armed flag AND reverts to NONE

Backward-compat aliases (removed when call sites catch up — ti-qt1i.1.5):
  DEMO == NONE  (far-only name; kept so old ``is TrustMode.DEMO`` checks still pass)
  FULL == BOTH  (old "grant" name; kept so old ``is TrustMode.FULL`` checks still pass)
"""
from __future__ import annotations

from enum import Enum


class TrustMode(str, Enum):
    NONE  = "none"   # unarmed — no elevation; cloud and auth'd skills blocked for far party
    LOCAL = "local"  # armed — operator FULL, far party DEMO
    BOTH  = "both"   # armed + granted — operator FULL, far party FULL
    # Backward-compat aliases — DEMO is NONE, FULL is BOTH. Deliberate enum
    # aliasing, not a mistake; removal tracked under ti-qt1i.1.5.
    DEMO  = "none"  # noqa: PIE796
    FULL  = "both"  # noqa: PIE796
