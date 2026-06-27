"""Email provider — EmailProvider protocol + IMAPEmailProvider adapter.

stdlib-only (imaplib, smtplib, email).  No third-party dependencies.

Auth (phase 1): app-password via IRIS_EMAIL_USER / IRIS_EMAIL_PASSWORD env vars.
  IRIS_EMAIL_IMAP_HOST  — e.g. imap.gmail.com
  IRIS_EMAIL_IMAP_PORT  — default 993 (SSL)
  IRIS_EMAIL_SMTP_HOST  — e.g. smtp.gmail.com
  IRIS_EMAIL_SMTP_PORT  — default 587 (STARTTLS)
  IRIS_EMAIL_ARCHIVE    — folder name for archive (default 'Archive')

Connections are opened per-call to avoid stale sockets on a long-running daemon.
All failures degrade silently: return empty list / None / False; never raise.

SECURITY: email bodies (body_text) are for local TTS only — they must NEVER
appear in a cloud model prompt.  The skill layer enforces this boundary.
"""
from __future__ import annotations

import email as _email_stdlib
import email.header
import email.message
import email.utils
import html.parser
import imaplib
import logging
import smtplib
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

log = logging.getLogger(__name__)

_DEFAULT_IMAP_PORT = 993
_DEFAULT_SMTP_PORT = 587
_DEFAULT_ARCHIVE_FOLDER = "Archive"
_CONNECT_TIMEOUT = 10  # seconds — enough for slow IMAP handshake


# ---------------------------------------------------------------------------
# HTML → plain-text stripping
# ---------------------------------------------------------------------------

class _HTMLStripper(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(self._parts)


def _strip_html(text: str) -> str:
    stripper = _HTMLStripper()
    stripper.feed(text)
    return stripper.get_text().strip()


# ---------------------------------------------------------------------------
# Header decoding
# ---------------------------------------------------------------------------

def _decode_header(raw: str) -> str:
    """Decode RFC 2047 encoded header (MIME words) to a plain string."""
    parts = email.header.decode_header(raw or "")
    decoded = []
    for chunk, charset in parts:
        if isinstance(chunk, bytes):
            try:
                decoded.append(chunk.decode(charset or "utf-8", errors="replace"))
            except Exception:  # noqa: BLE001
                decoded.append(chunk.decode("utf-8", errors="replace"))
        else:
            decoded.append(chunk)
    return "".join(decoded)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class EmailMessage:
    id: str             # IMAP UID (string for portability)
    subject: str
    sender_name: str
    sender_email: str
    date: str           # RFC 2822 date string
    body_text: str      # plain-text body; HTML stripped at adapter layer
    unread: bool


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class EmailProvider(Protocol):
    def list_unread(self, limit: int = 5) -> list[EmailMessage]: ...
    def get_message(self, message_id: str) -> EmailMessage | None: ...
    def send(self, to: str, subject: str, body: str) -> bool: ...
    def mark_read(self, message_id: str) -> bool: ...
    def archive(self, message_id: str) -> bool: ...


# ---------------------------------------------------------------------------
# IMAPEmailProvider
# ---------------------------------------------------------------------------

class IMAPEmailProvider:
    """IMAP/SMTP adapter backed by Python stdlib.

    Credentials are passed at construction (typically sourced from env vars).
    All methods open a fresh connection, perform the operation, then close.
    """

    def __init__(
        self,
        *,
        imap_host: str,
        imap_port: int = _DEFAULT_IMAP_PORT,
        smtp_host: str,
        smtp_port: int = _DEFAULT_SMTP_PORT,
        user: str,
        password: str,
        archive_folder: str = _DEFAULT_ARCHIVE_FOLDER,
    ) -> None:
        self._imap_host = imap_host
        self._imap_port = imap_port
        self._smtp_host = smtp_host
        self._smtp_port = smtp_port
        self._user = user
        self._password = password
        self._archive_folder = archive_folder

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _imap_connect(self) -> imaplib.IMAP4_SSL | None:
        """Open an authenticated IMAP connection.  Returns None on failure."""
        try:
            conn = imaplib.IMAP4_SSL(
                self._imap_host, self._imap_port,
                timeout=_CONNECT_TIMEOUT,
            )
            conn.login(self._user, self._password)
            return conn
        except Exception:  # noqa: BLE001
            log.exception("IMAP connect failed (%s)", self._imap_host)
            return None

    def _parse_envelope(self, uid: str, envelope_data: bytes) -> EmailMessage | None:
        """Parse an RFC 822 envelope bytes into an EmailMessage.  Returns None on failure."""
        try:
            msg = _email_stdlib.message_from_bytes(envelope_data)
            subject = _decode_header(msg.get("Subject", ""))
            from_raw = msg.get("From", "")
            sender_name, sender_email = email.utils.parseaddr(from_raw)
            if not sender_name:
                sender_name = sender_email
            sender_name = _decode_header(sender_name)
            date = msg.get("Date", "")
            return EmailMessage(
                id=uid,
                subject=subject,
                sender_name=sender_name,
                sender_email=sender_email,
                date=date,
                body_text="",  # populated separately when get_message() is called
                unread=True,
            )
        except Exception:  # noqa: BLE001
            log.exception("Failed to parse envelope for uid=%s", uid)
            return None

    def _extract_body(self, msg: _email_stdlib.message.Message) -> str:
        """Extract best plain-text body from a parsed email.Message."""
        plain_parts: list[str] = []
        html_parts: list[str] = []
        if msg.is_multipart():
            for part in msg.walk():
                ct = part.get_content_type()
                if part.get_content_disposition() == "attachment":
                    continue
                payload = part.get_payload(decode=True)
                if not payload:
                    continue
                charset = part.get_content_charset() or "utf-8"
                text = payload.decode(charset, errors="replace")
                if ct == "text/plain":
                    plain_parts.append(text)
                elif ct == "text/html":
                    html_parts.append(_strip_html(text))
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                text = payload.decode(charset, errors="replace")
                if msg.get_content_type() == "text/html":
                    html_parts.append(_strip_html(text))
                else:
                    plain_parts.append(text)
        body = "\n\n".join(plain_parts) or "\n\n".join(html_parts)
        return body.strip()

    # ------------------------------------------------------------------
    # EmailProvider interface
    # ------------------------------------------------------------------

    def list_unread(self, limit: int = 5) -> list[EmailMessage]:
        """Return up to `limit` unread messages from INBOX (newest first)."""
        conn = self._imap_connect()
        if conn is None:
            return []
        try:
            conn.select("INBOX", readonly=True)
            typ, data = conn.uid("SEARCH", None, "UNSEEN")
            if typ != "OK" or not data or not data[0]:
                return []
            uid_list = data[0].split()
            uids = uid_list[-limit:]  # newest last in IMAP; take the tail
            uids = list(reversed(uids))  # newest first

            messages: list[EmailMessage] = []
            for uid_bytes in uids:
                uid = uid_bytes.decode()
                typ2, msg_data = conn.uid("FETCH", uid, "(RFC822.HEADER)")
                if typ2 != "OK" or not msg_data or not msg_data[0]:
                    continue
                raw_header = msg_data[0][1] if isinstance(msg_data[0], tuple) else None
                if not raw_header:
                    continue
                parsed = self._parse_envelope(uid, raw_header)
                if parsed:
                    messages.append(parsed)
            return messages
        except Exception:  # noqa: BLE001
            log.exception("list_unread failed")
            return []
        finally:
            try:
                conn.logout()
            except Exception:  # noqa: BLE001
                pass

    def get_message(self, message_id: str) -> EmailMessage | None:
        """Fetch full message body by UID.  HTML stripped to plain text."""
        conn = self._imap_connect()
        if conn is None:
            return None
        try:
            conn.select("INBOX", readonly=True)
            typ, msg_data = conn.uid("FETCH", message_id, "(RFC822)")
            if typ != "OK" or not msg_data or not msg_data[0]:
                return None
            raw = msg_data[0][1] if isinstance(msg_data[0], tuple) else None
            if not raw:
                return None
            msg = _email_stdlib.message_from_bytes(raw)
            subject = _decode_header(msg.get("Subject", ""))
            from_raw = msg.get("From", "")
            sender_name, sender_email = email.utils.parseaddr(from_raw)
            if not sender_name:
                sender_name = sender_email
            sender_name = _decode_header(sender_name)
            date = msg.get("Date", "")
            body_text = self._extract_body(msg)
            return EmailMessage(
                id=message_id,
                subject=subject,
                sender_name=sender_name,
                sender_email=sender_email,
                date=date,
                body_text=body_text,
                unread=True,
            )
        except Exception:  # noqa: BLE001
            log.exception("get_message(%s) failed", message_id)
            return None
        finally:
            try:
                conn.logout()
            except Exception:  # noqa: BLE001
                pass

    def send(self, to: str, subject: str, body: str) -> bool:
        """Send an email via SMTP STARTTLS.  Returns True on success."""
        try:
            msg = email.message.EmailMessage()
            msg["From"] = self._user
            msg["To"] = to
            msg["Subject"] = subject
            msg.set_content(body)
            with smtplib.SMTP(self._smtp_host, self._smtp_port,
                              timeout=_CONNECT_TIMEOUT) as smtp:
                smtp.starttls()
                smtp.login(self._user, self._password)
                smtp.send_message(msg)
            return True
        except Exception:  # noqa: BLE001
            log.exception("send to %s failed", to)
            return False

    def mark_read(self, message_id: str) -> bool:
        """Mark a message as Seen.  Returns True on success."""
        conn = self._imap_connect()
        if conn is None:
            return False
        try:
            conn.select("INBOX")
            typ, _ = conn.uid("STORE", message_id, "+FLAGS", r"\Seen")
            return typ == "OK"
        except Exception:  # noqa: BLE001
            log.exception("mark_read(%s) failed", message_id)
            return False
        finally:
            try:
                conn.logout()
            except Exception:  # noqa: BLE001
                pass

    def archive(self, message_id: str) -> bool:
        """Copy to archive folder, flag Deleted, and EXPUNGE.  Returns True on success."""
        conn = self._imap_connect()
        if conn is None:
            return False
        try:
            conn.select("INBOX")
            typ, _ = conn.uid("COPY", message_id, self._archive_folder)
            if typ != "OK":
                return False
            conn.uid("STORE", message_id, "+FLAGS", r"\Deleted")
            conn.expunge()
            return True
        except Exception:  # noqa: BLE001
            log.exception("archive(%s) failed", message_id)
            return False
        finally:
            try:
                conn.logout()
            except Exception:  # noqa: BLE001
                pass
