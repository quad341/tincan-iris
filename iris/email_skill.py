"""Email voice-command skills — ti-q8kh.2.

All email-sending operations use a two-phase confirmation protocol:

  Phase 1 — SendEmailSkill.run() stages a pending send and returns a spoken
             confirmation prompt.
  Phase 2 — ConfirmEmailSkill executes.  CancelEmailSkill clears it.

SECURITY: email bodies must NEVER appear in a cloud model prompt.
  These skills format spoken output locally; the brain routes to local TTS only.

All skills are FULL-trust — never registered in demo mode.

Factory function:
    for skill in email_skills(provider):
        brain.skills.register(skill)
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from .email_provider import EmailMessage, EmailProvider
from .skills import SkillParam

# ---------------------------------------------------------------------------
# Spoken formatting helpers
# ---------------------------------------------------------------------------

_ORDINALS = ["One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten"]
_SUBJECT_MAX = 60


def _format_email_address(addr: str) -> str:
    """alice@example.com → 'alice at example dot com'."""
    if "@" not in addr:
        return addr
    user, domain = addr.split("@", 1)
    domain_spoken = domain.replace(".", " dot ")
    return f"{user} at {domain_spoken}"


def _format_subject(subject: str) -> str:
    """Truncate long subjects to 60 chars + ellipsis."""
    if len(subject) <= _SUBJECT_MAX:
        return subject
    return subject[:_SUBJECT_MAX].rstrip() + "…"


def _format_sender(name: str, email_addr: str) -> str:
    """Return sender name if available, else spoken email address."""
    if name and name != email_addr:
        return name
    return _format_email_address(email_addr)


def _strip_html_artifacts(text: str) -> str:
    """Remove stray < > tags that survived the adapter's HTML stripper."""
    return re.sub(r"<[^>]*>", "", text)


def _truncate_body(text: str, max_words: int = 200) -> str:
    """Trim body to max_words words."""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + "…"


def _humanize_date(date_str: str) -> str:
    """Best-effort humanization of RFC 2822 date. Falls back to raw string."""
    try:
        import email.utils
        import time
        ts = email.utils.parsedate(date_str)
        if ts is None:
            return date_str
        t = time.mktime(ts)
        import datetime
        dt = datetime.datetime.fromtimestamp(t)
        hour = dt.hour
        if 5 <= hour < 12:
            part = "morning"
        elif 12 <= hour < 17:
            part = "afternoon"
        elif 17 <= hour < 21:
            part = "evening"
        else:
            part = "night"
        day = dt.strftime("%A")
        return f"{day} {part}"
    except Exception:  # noqa: BLE001
        return date_str


def _spoken_list(messages: list[EmailMessage]) -> str:
    """Format a list of unread messages as a spoken numbered response."""
    if not messages:
        return "No unread emails."
    count = len(messages)
    lines = [f"You have {count} unread {'email' if count == 1 else 'emails'}."]
    for i, msg in enumerate(messages):
        ordinal = _ORDINALS[i] if i < len(_ORDINALS) else str(i + 1)
        sender = _format_sender(msg.sender_name, msg.sender_email)
        subject = _format_subject(msg.subject)
        lines.append(f'{ordinal}: from {sender}, subject: "{subject}".')
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------

class _EmailPendingState:
    """Staged send waiting for confirmation."""

    def __init__(self) -> None:
        self._pending: tuple[str, Callable[[], bool]] | None = None

    def stage(self, prompt: str, execute: Callable[[], bool]) -> str:
        self._pending = (prompt, execute)
        return prompt

    def confirm(self) -> str:
        if self._pending is None:
            return "Nothing to confirm."
        _, fn = self._pending
        self._pending = None
        return "Message sent." if fn() else "I couldn't send that. Please check your email settings."

    def cancel(self) -> str:
        self._pending = None
        return "Cancelled."


@dataclass
class _TriageState:
    """Tracks the current email for follow-up triage commands."""
    current_id: str = ""
    current_subject: str = ""
    inbox_ids: list[str] = field(default_factory=list)
    inbox_pos: int = 0


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------

class ReadEmailSkill:
    name = "read_email"
    description = (
        "List unread emails (action='list_unread') or read a specific email body "
        "aloud (action='read_message', message_id required). "
        "NEVER use for sending — use send_email for that."
    )
    params: list[SkillParam] = [
        SkillParam(
            name="action",
            type="string",
            description="'list_unread' or 'read_message'.",
            enum=["list_unread", "read_message"],
        ),
        SkillParam(
            name="message_id",
            type="string",
            description="IMAP UID of the message to read (required for read_message).",
            required=False,
            default="",
        ),
    ]

    def __init__(self, provider: EmailProvider, triage: _TriageState) -> None:
        self._provider = provider
        self._triage = triage

    def run(self, *, action: str = "list_unread", message_id: str = "", **_: object) -> str:
        if action == "list_unread":
            messages = self._provider.list_unread(limit=5)
            if messages is None:
                return "I couldn't reach your email right now."
            self._triage.inbox_ids = [m.id for m in messages]
            self._triage.inbox_pos = 0
            return _spoken_list(messages)

        if action == "read_message":
            uid = message_id or (self._triage.inbox_ids[0] if self._triage.inbox_ids else "")
            if not uid:
                return "Which email would you like me to read? Say 'read email one' or 'read email two'."
            msg = self._provider.get_message(uid)
            if msg is None:
                return "I couldn't retrieve that email right now."
            self._triage.current_id = uid
            self._triage.current_subject = msg.subject
            sender = _format_sender(msg.sender_name, msg.sender_email)
            date_str = _humanize_date(msg.date)
            body = _truncate_body(_strip_html_artifacts(msg.body_text))
            return (
                f'Email from {sender}, subject: "{_format_subject(msg.subject)}", '
                f"received {date_str}.\nBody: {body}\n"
                "Would you like to reply, archive it, or mark it as read?"
            )

        return f"Unknown action: {action}."


class SendEmailSkill:
    name = "send_email"
    description = (
        "Stage an outbound email for operator confirmation. Returns a spoken preview. "
        "Requires ConfirmEmailSkill to actually send."
    )
    params: list[SkillParam] = [
        SkillParam(name="to", type="string", description="Recipient address or name."),
        SkillParam(name="subject", type="string", description="Email subject line."),
        SkillParam(
            name="body",
            type="string",
            description="Email body text, as dictated by the operator.",
        ),
    ]

    def __init__(self, provider: EmailProvider, pending: _EmailPendingState) -> None:
        self._provider = provider
        self._pending = pending

    def run(self, *, to: str = "", subject: str = "", body: str = "", **_: object) -> str:
        if not to or not subject or not body:
            return "I need a recipient, subject, and body to send an email."
        to_spoken = _format_email_address(to) if "@" in to else to
        body_preview = " ".join(body.split()[:30])
        if len(body.split()) > 30:
            body_preview += "…"
        prompt = (
            f'Sending to {to_spoken}, subject: "{_format_subject(subject)}", '
            f'body: "{body_preview}". Is that right?'
        )
        return self._pending.stage(prompt, lambda: self._provider.send(to, subject, body))


class ConfirmEmailSkill:
    name = "confirm_email"
    description = "Confirm and execute the staged outbound email."
    params: list[SkillParam] = []

    def __init__(self, pending: _EmailPendingState) -> None:
        self._pending = pending

    def run(self, **_: object) -> str:
        return self._pending.confirm()


class CancelEmailSkill:
    name = "cancel_email"
    description = "Cancel the staged outbound email without sending."
    params: list[SkillParam] = []

    def __init__(self, pending: _EmailPendingState) -> None:
        self._pending = pending

    def run(self, **_: object) -> str:
        return self._pending.cancel()


class TriageEmailSkill:
    name = "triage_email"
    description = (
        "Mark an email as read, archive it, or flag it for follow-up. "
        "Uses current_id from the last read_message if message_id is omitted."
    )
    params: list[SkillParam] = [
        SkillParam(
            name="action",
            type="string",
            description="'mark_read', 'archive', or 'flag' (flag is a no-op placeholder in v1).",
            enum=["mark_read", "archive", "flag"],
        ),
        SkillParam(
            name="message_id",
            type="string",
            description="IMAP UID. Defaults to the last read email.",
            required=False,
            default="",
        ),
    ]

    def __init__(self, provider: EmailProvider, triage: _TriageState) -> None:
        self._provider = provider
        self._triage = triage

    def run(self, *, action: str = "mark_read", message_id: str = "", **_: object) -> str:
        uid = message_id or self._triage.current_id
        if not uid:
            return "Which email are you referring to? Please read or list emails first."
        if action == "mark_read":
            ok = self._provider.mark_read(uid)
            return "Marked as read." if ok else "I couldn't mark that as read right now."
        if action == "archive":
            ok = self._provider.archive(uid)
            if ok:
                self._triage.current_id = ""
                return "Archived."
            return "I couldn't archive that right now."
        if action == "flag":
            return "Flagging emails is not available yet."
        return f"Unknown action: {action}."


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def email_skills(provider: EmailProvider) -> list[object]:
    """Return all email skill instances sharing state.  Register in brain.skills."""
    pending = _EmailPendingState()
    triage = _TriageState()
    return [
        ReadEmailSkill(provider, triage),
        SendEmailSkill(provider, pending),
        ConfirmEmailSkill(pending),
        CancelEmailSkill(pending),
        TriageEmailSkill(provider, triage),
    ]
