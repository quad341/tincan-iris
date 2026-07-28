"""messages_skill — Iris-facing SMS read/triage/draft skills.

Two skills backed by a TincanMessages client:

  ReadMessagesSkill  — list conversations (with unread count) or read messages
                       in a specific conversation.
  SendMessageSkill   — resolve a name to an E.164 number via GetContacts, then
                       call SendMessageToRecipients.  EXPLICIT COMMAND ONLY:
                       the brain must pass an already-operator-confirmed body.

Both are FULL-trust only — the existing ``allow_skills=not demo_mode`` gate in
Brain.respond() ensures DEMO far parties never reach them.

Usage (inject via brain's skill registry):
    msgs = TincanMessages(emit=queue.append)
    msgs.start()
    for s in messages_skills(msgs):
        brain.skills.register(s)
"""
from __future__ import annotations

from typing import ClassVar

from .skills import SkillParam
from .tincan_messages import TincanMessages


class ReadMessagesSkill:
    name = "read_messages"
    description = (
        "List SMS conversations and their unread counts, or read the messages "
        "in a specific conversation."
    )
    params: ClassVar[list[SkillParam]] = [
        SkillParam(
            name="action",
            type="string",
            description="'list_conversations' or 'get_messages'.",
            enum=["list_conversations", "get_messages"],
        ),
        SkillParam(
            name="conversation_id",
            type="string",
            description="Conversation ID (required for get_messages).",
            required=False,
            default="",
        ),
    ]

    def __init__(self, messages: TincanMessages) -> None:
        self._messages = messages

    def run(
        self,
        *,
        action: str = "list_conversations",
        conversation_id: str = "",
        **_kwargs: object,
    ) -> str:
        if action == "get_messages":
            if not conversation_id:
                return "I need a conversation ID to read messages."
            msgs = self._messages.get_messages(conversation_id)
            if not msgs:
                return "No messages found in that conversation."
            lines = []
            for m in msgs:
                sender = m.get("sender_name") or m.get("sender") or "?"
                body = m.get("body") or m.get("text") or ""
                lines.append(f"{sender}: {body}")
            return "\n".join(lines)

        convos = self._messages.list_conversations()
        if not convos:
            return "No conversations found."
        lines = []
        for c in convos:
            cid = c.get("id") or c.get("conversation_id") or "?"
            name = c.get("display_name") or c.get("name") or c.get("number") or cid
            unread = int(c.get("unread_count", 0))
            unread_str = f" ({unread} unread)" if unread else ""
            lines.append(f"{name}{unread_str} — id:{cid}")
        return "\n".join(lines)


class SendMessageSkill:
    name = "send_message"
    description = (
        "Send an SMS to a contact by name or E.164 number. "
        "Only call this with a body the operator has explicitly confirmed."
    )
    params: ClassVar[list[SkillParam]] = [
        SkillParam(
            name="to",
            type="string",
            description="Contact name or E.164 number (e.g. +15555550100).",
        ),
        SkillParam(
            name="body",
            type="string",
            description="Message body, operator-confirmed before this skill is called.",
        ),
        SkillParam(
            name="conversation_id",
            type="string",
            description=(
                "If set, reply to this existing conversation instead of "
                "resolving 'to' to a new recipient."
            ),
            required=False,
            default="",
        ),
    ]

    def __init__(self, messages: TincanMessages) -> None:
        self._messages = messages

    def _resolve_number(self, name_or_number: str) -> str | None:
        """Return an E.164 number for name_or_number, or None if not found.

        If the value already looks like a number (+digits or digits-only), return
        it directly.  Otherwise search get_contacts() for a display-name match.
        """
        v = name_or_number.strip()
        if v.lstrip("+").isdigit():
            return v
        contacts = self._messages.get_contacts()
        v_lower = v.lower()
        for c in contacts:
            display = (c.get("display_name") or c.get("name") or "").lower()
            if display == v_lower or v_lower in display:
                return c.get("number") or c.get("phone_number") or c.get("e164")
        return None

    def run(
        self,
        *,
        to: str = "",
        body: str = "",
        conversation_id: str = "",
        **_kwargs: object,
    ) -> str:
        if not body:
            return "I need a message body to send."

        if conversation_id:
            ok = self._messages.send_message(conversation_id, body)
            return "Message sent." if ok else "Could not send the message."

        if not to:
            return "I need a recipient name or number."

        number = self._resolve_number(to)
        if number is None:
            return f"I couldn't find a number for '{to}'."

        ok = self._messages.send_message_to_recipients([number], body)
        return "Message sent." if ok else "Could not send the message."


def messages_skills(messages: TincanMessages) -> list:
    """Return the list of message skills backed by ``messages``."""
    return [ReadMessagesSkill(messages), SendMessageSkill(messages)]
