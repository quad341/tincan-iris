"""Unit tests for TranscriptStore (ti-rnlqo.5.1)."""
from __future__ import annotations

import threading

from iris.capture.transcript import TranscriptStore
from iris.trust import TrustMode


def test_append_returns_sequential_turn_ids():
    store = TranscriptStore()
    id1 = store.append("hello", "operator", 0.0)
    id2 = store.append("hi there", "far", 1.5)
    assert id1 == 1
    assert id2 == 2


def test_get_turns_returns_copy():
    store = TranscriptStore()
    store.append("text", "operator", 0.0)
    turns = store.get_turns()
    turns.clear()
    assert len(store.get_turns()) == 1


def test_is_empty_before_and_after():
    store = TranscriptStore()
    assert store.is_empty()
    store.append("x", "operator", 0.0)
    assert not store.is_empty()


def test_get_turns_preserves_fields():
    store = TranscriptStore()
    store.append("call ref 123", "far", 2.3)
    turns = store.get_turns()
    assert len(turns) == 1
    t = turns[0]
    assert t.text == "call ref 123"
    assert t.speaker == "far"
    assert t.offset_s == 2.3


def test_thread_safety_no_lost_turns():
    store = TranscriptStore()
    errors: list[Exception] = []

    def append_n(n: int) -> None:
        try:
            for i in range(n):
                store.append(f"t{i}", "operator", float(i))
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=append_n, args=(50,)) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert len(store.get_turns()) == 200


# ---------------------------------------------------------------------------
# far-party trust stamping (ti-pkt2r.2 -- FR6 trust-gate policy)
# ---------------------------------------------------------------------------

def test_default_trust_is_none():
    store = TranscriptStore()
    store.append("hi", "far", 0.0)
    assert store.get_turns()[0].trust is TrustMode.NONE


def test_set_trust_stamps_subsequent_appends():
    store = TranscriptStore()
    store.set_trust(TrustMode.BOTH)
    store.append("granted", "far", 0.0)
    assert store.get_turns()[0].trust is TrustMode.BOTH


def test_set_trust_does_not_restamp_earlier_turns():
    """Trust is stamped once, at capture time -- elevating mid-call must not
    retroactively change turns already appended (ti-pkt2r.2)."""
    store = TranscriptStore()
    store.append("before grant", "far", 0.0)
    store.set_trust(TrustMode.BOTH)
    store.append("after grant", "far", 1.0)

    turns = store.get_turns()
    assert turns[0].trust is TrustMode.NONE
    assert turns[1].trust is TrustMode.BOTH
