"""Tests for MessageStore — the in-memory voice message store (ti-aynh)."""
from __future__ import annotations

from iris.message_store import MessageStore, VoiceMessage


def test_store_starts_empty():
    s = MessageStore()
    assert s.all() == []
    assert s.unread() == []


def test_add_message_returns_voicemessage():
    s = MessageStore()
    msg = s.add("Bob", "Please call me back.", caller_number="+15555550123")
    assert isinstance(msg, VoiceMessage)
    assert msg.caller_name == "Bob"
    assert msg.transcript == "Please call me back."
    assert msg.caller_number == "+15555550123"
    assert msg.read is False


def test_add_increments_ids():
    s = MessageStore()
    m1 = s.add("A", "msg1")
    m2 = s.add("B", "msg2")
    assert m1.id < m2.id


def test_unread_returns_only_unread():
    s = MessageStore()
    m1 = s.add("A", "first")
    m2 = s.add("B", "second")
    s.mark_read(m1.id)
    unread = s.unread()
    assert len(unread) == 1
    assert unread[0].id == m2.id


def test_mark_read_returns_true_on_found():
    s = MessageStore()
    msg = s.add("Alice", "text")
    assert s.mark_read(msg.id) is True
    assert msg.read is True


def test_mark_read_returns_false_when_not_found():
    s = MessageStore()
    assert s.mark_read(9999) is False


def test_delete_removes_message():
    s = MessageStore()
    msg = s.add("Alice", "text")
    assert s.delete(msg.id) is True
    assert s.all() == []


def test_delete_returns_false_when_not_found():
    s = MessageStore()
    assert s.delete(9999) is False


def test_clear_empties_store():
    s = MessageStore()
    s.add("A", "msg1")
    s.add("B", "msg2")
    s.clear()
    assert s.all() == []


def test_optional_contact_name_stored():
    s = MessageStore()
    msg = s.add("Sam", "hello", contact_name="Samuel")
    assert msg.contact_name == "Samuel"


def test_timestamp_stored():
    import time
    s = MessageStore()
    before = time.time()
    msg = s.add("X", "y")
    after = time.time()
    assert before <= msg.timestamp <= after


def test_custom_timestamp():
    s = MessageStore()
    msg = s.add("X", "y", timestamp=1000.0)
    assert msg.timestamp == 1000.0
