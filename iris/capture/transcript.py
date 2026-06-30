"""Thread-safe in-memory transcript store — ti-rnlqo.5.1."""
from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass
class TranscriptTurn:
    turn_id: int
    text: str
    speaker: str    # 'operator' | 'far'
    offset_s: float


class TranscriptStore:
    """In-memory transcript for one call; lifetime = CaptureSession.

    Thread-safe: all methods acquire _lock. Caller receives a copy from
    get_turns() so the internal list cannot be mutated externally.
    """

    def __init__(self) -> None:
        self._turns: list[TranscriptTurn] = []
        self._lock = threading.RLock()
        self._next_id: int = 1

    def append(self, text: str, speaker: str, offset_s: float) -> int:
        """Append an utterance and return the assigned turn_id."""
        with self._lock:
            turn_id = self._next_id
            self._next_id += 1
            self._turns.append(TranscriptTurn(turn_id=turn_id, text=text, speaker=speaker, offset_s=offset_s))
            return turn_id

    def get_turns(self) -> list[TranscriptTurn]:
        """Return a shallow copy of all turns (safe to iterate without holding lock)."""
        with self._lock:
            return list(self._turns)

    def is_empty(self) -> bool:
        """True iff no turns have been appended."""
        with self._lock:
            return not self._turns
