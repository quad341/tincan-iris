"""In-memory message store for voice messages captured by TakeMessageFlow.

Messages arrive via the take_message_done event and are held here until
the operator marks them read or calls back.  Backed by an in-memory list
(survives the session; resets on restart — v1 does not persist messages).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class VoiceMessage:
    id: int
    caller_name: str      # stated by caller ("Bob Smith" or "the caller")
    caller_number: str    # E.164 from the roster lookup (may be "")
    contact_name: str     # roster display_name (may be "" for unknowns)
    transcript: str       # verbatim ASR text
    timestamp: float      # time.time() at receipt
    read: bool = False


class MessageStore:
    """Thread-safe in-memory store for VoiceMessage objects."""

    def __init__(self) -> None:
        self._messages: list[VoiceMessage] = []
        self._next_id: int = 1

    def add(
        self,
        caller_name: str,
        transcript: str,
        *,
        caller_number: str = "",
        contact_name: str = "",
        timestamp: float | None = None,
    ) -> VoiceMessage:
        msg = VoiceMessage(
            id=self._next_id,
            caller_name=caller_name,
            caller_number=caller_number,
            contact_name=contact_name,
            transcript=transcript,
            timestamp=timestamp if timestamp is not None else time.time(),
        )
        self._messages.append(msg)
        self._next_id += 1
        return msg

    def unread(self) -> list[VoiceMessage]:
        return [m for m in self._messages if not m.read]

    def all(self) -> list[VoiceMessage]:
        return list(self._messages)

    def mark_read(self, message_id: int) -> bool:
        for m in self._messages:
            if m.id == message_id:
                m.read = True
                return True
        return False

    def delete(self, message_id: int) -> bool:
        for i, m in enumerate(self._messages):
            if m.id == message_id:
                del self._messages[i]
                return True
        return False

    def clear(self) -> None:
        self._messages.clear()
        self._next_id = 1
