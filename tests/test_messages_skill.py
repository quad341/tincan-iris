"""Tests for messages skill (ReadMessagesSkill + SendMessageSkill).

All tests use a mock TincanMessages so no D-Bus is needed."""
from __future__ import annotations

from unittest.mock import MagicMock

from iris.messages_skill import ReadMessagesSkill, SendMessageSkill, messages_skills
from iris.tincan_messages import TincanMessages


def _mock_messages(**kwargs):
    """Return a MagicMock spec'd to TincanMessages."""
    m = MagicMock(spec=TincanMessages)
    for attr, val in kwargs.items():
        getattr(m, attr).return_value = val
    return m


# --- ReadMessagesSkill: list_conversations ---

def test_read_messages_skill_lists_conversations():
    convos = [
        {"id": "c1", "display_name": "Alice", "unread_count": 3},
        {"id": "c2", "display_name": "Bob", "unread_count": 0},
    ]
    m = _mock_messages(list_conversations=convos)
    skill = ReadMessagesSkill(m)
    result = skill.run(action="list_conversations")
    assert "Alice" in result
    assert "3 unread" in result
    assert "Bob" in result
    assert "c1" in result


def test_read_messages_skill_no_unread_omits_count():
    convos = [{"id": "c1", "display_name": "Bob", "unread_count": 0}]
    m = _mock_messages(list_conversations=convos)
    skill = ReadMessagesSkill(m)
    result = skill.run(action="list_conversations")
    assert "unread" not in result


def test_read_messages_skill_empty_conversations():
    m = _mock_messages(list_conversations=[])
    skill = ReadMessagesSkill(m)
    result = skill.run(action="list_conversations")
    assert "No conversations" in result


# --- ReadMessagesSkill: get_messages ---

def test_read_messages_skill_get_messages():
    msgs = [
        {"sender_name": "Alice", "body": "Hey there"},
        {"sender_name": "Me", "body": "Hi Alice"},
    ]
    m = _mock_messages(get_messages=msgs)
    skill = ReadMessagesSkill(m)
    result = skill.run(action="get_messages", conversation_id="c1")
    assert "Alice: Hey there" in result
    assert "Me: Hi Alice" in result


def test_read_messages_skill_get_messages_no_id():
    m = _mock_messages()
    skill = ReadMessagesSkill(m)
    result = skill.run(action="get_messages", conversation_id="")
    assert "I need a conversation ID" in result
    m.get_messages.assert_not_called()


def test_read_messages_skill_get_messages_empty():
    m = _mock_messages(get_messages=[])
    skill = ReadMessagesSkill(m)
    result = skill.run(action="get_messages", conversation_id="c1")
    assert "No messages" in result


def test_read_messages_skill_falls_back_to_sender_key():
    msgs = [{"sender": "+15555550100", "body": "Hello"}]
    m = _mock_messages(get_messages=msgs)
    skill = ReadMessagesSkill(m)
    result = skill.run(action="get_messages", conversation_id="c1")
    assert "+15555550100" in result
    assert "Hello" in result


# --- SendMessageSkill: number directly ---

def test_send_message_with_e164_number():
    m = _mock_messages(send_message_to_recipients=True)
    skill = SendMessageSkill(m)
    result = skill.run(to="+15555550100", body="Hi")
    assert result == "Message sent."
    m.send_message_to_recipients.assert_called_once_with(["+15555550100"], "Hi")


def test_send_message_with_digits_only_number():
    m = _mock_messages(send_message_to_recipients=True)
    skill = SendMessageSkill(m)
    result = skill.run(to="5555550100", body="Test")
    assert result == "Message sent."
    m.send_message_to_recipients.assert_called_once_with(["5555550100"], "Test")


# --- SendMessageSkill: name resolution ---

def test_send_message_resolves_name_to_number():
    contacts = [
        {"display_name": "Alice", "number": "+15555550123"},
        {"display_name": "Bob", "number": "+15555550456"},
    ]
    m = _mock_messages(get_contacts=contacts, send_message_to_recipients=True)
    skill = SendMessageSkill(m)
    result = skill.run(to="Alice", body="Hello")
    assert result == "Message sent."
    m.send_message_to_recipients.assert_called_once_with(["+15555550123"], "Hello")


def test_send_message_partial_name_match():
    contacts = [{"display_name": "Alice Smith", "number": "+15555550123"}]
    m = _mock_messages(get_contacts=contacts, send_message_to_recipients=True)
    skill = SendMessageSkill(m)
    result = skill.run(to="Alice", body="Hi")
    assert result == "Message sent."


def test_send_message_name_not_found():
    m = _mock_messages(get_contacts=[])
    skill = SendMessageSkill(m)
    result = skill.run(to="NoOne", body="Hi")
    assert "couldn't find" in result.lower()
    m.send_message_to_recipients.assert_not_called()


# --- SendMessageSkill: conversation_id path ---

def test_send_message_with_conversation_id():
    m = _mock_messages(send_message=True)
    skill = SendMessageSkill(m)
    result = skill.run(to="", body="Reply", conversation_id="conv-5")
    assert result == "Message sent."
    m.send_message.assert_called_once_with("conv-5", "Reply")
    m.send_message_to_recipients.assert_not_called()


# --- SendMessageSkill: error paths ---

def test_send_message_no_body():
    m = _mock_messages()
    skill = SendMessageSkill(m)
    result = skill.run(to="+15555550100", body="")
    assert "need a message body" in result.lower()
    m.send_message_to_recipients.assert_not_called()


def test_send_message_no_to_no_conv_id():
    m = _mock_messages()
    skill = SendMessageSkill(m)
    result = skill.run(to="", body="Hi", conversation_id="")
    assert "need a recipient" in result.lower()


def test_send_message_dbus_failure_returns_error():
    m = _mock_messages(send_message_to_recipients=False)
    skill = SendMessageSkill(m)
    result = skill.run(to="+15555550100", body="Hi")
    assert "Could not send" in result


# --- messages_skills factory ---

def test_messages_skills_factory_returns_both():
    m = MagicMock(spec=TincanMessages)
    skills = messages_skills(m)
    names = {s.name for s in skills}
    assert "read_messages" in names
    assert "send_message" in names
