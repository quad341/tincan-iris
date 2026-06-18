"""Far-end identity state machine — in-process, never persisted.

Three states:
  UNIDENTIFIED — default for VoIP; phone calls without a known contact.
  IDENTIFIED   — operator has bound this call to a roster contact.
  PRIVATE      — operator engaged the privacy kill-switch ([u]); terminal.

Transitions (immutable — each method returns a new FarEndIdentity):
  Unidentified.bind(n, name)  → Identified(contact_id=n)
  Unidentified.make_private() → Private(contact_id=SENTINEL_ID)
  Identified.bind(n, name)    → Identified(contact_id=n)  [re-bind allowed]
  Identified.make_private()   → Private(contact_id=SENTINEL_ID)
  Private.*                   → Private  [terminal: all transitions are no-ops]

SENTINEL_ID (0) is the reserved contact_id for Private calls. SQLite
AUTOINCREMENT on the contacts table starts at 1, so 0 is permanently free.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

SENTINEL_ID = 0


class FarEndState(Enum):
    UNIDENTIFIED = "unidentified"
    IDENTIFIED = "identified"
    PRIVATE = "private"


@dataclass(frozen=True)
class FarEndIdentity:
    state: FarEndState = FarEndState.UNIDENTIFIED
    contact_id: int | None = None
    display_name: str = ""

    def bind(self, contact_id: int, display_name: str) -> "FarEndIdentity":
        """Return Identified identity. No-op if already Private."""
        if self.state is FarEndState.PRIVATE:
            return self
        return FarEndIdentity(FarEndState.IDENTIFIED, contact_id, display_name)

    def make_private(self) -> "FarEndIdentity":
        """Return Private identity. Always succeeds; replaces any prior state."""
        return FarEndIdentity(FarEndState.PRIVATE, SENTINEL_ID, "(private)")

    @property
    def archival_contact_id(self) -> str | None:
        """Return contact_id str for MemoryManager, or None to skip archival.

        Identified → str(contact_id) so MemoryManager archives to that contact.
        Unidentified and Private → None (no disk write at call-end).
        """
        if self.state is FarEndState.IDENTIFIED and self.contact_id is not None:
            return str(self.contact_id)
        return None
