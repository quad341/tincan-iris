"""Tests for IMAPEmailProvider pure helper functions (ti-402a F-COV-01).

_strip_html, _decode_header, _extract_body, _parse_envelope are data-processing
functions with no I/O — tested with in-memory fixtures only.
"""
from __future__ import annotations

import base64
import email as _stdlib_email
import email.message
from unittest.mock import patch

from iris.email_provider import (
    IMAPEmailProvider,
    _decode_header,
    _strip_html,
)


def _provider():
    return IMAPEmailProvider(
        imap_host="localhost", smtp_host="localhost",
        user="user@example.com", password="secret",
    )


def _make_raw(
    subject: str = "Hello",
    from_addr: str = "Alice <alice@example.com>",
    date: str = "Mon, 1 Jan 2024 10:00:00 +0000",
) -> bytes:
    msg = email.message.EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["Date"] = date
    return msg.as_bytes()


# ---------------------------------------------------------------------------
# _strip_html
# ---------------------------------------------------------------------------

def test_strip_html_removes_simple_tags():
    assert _strip_html("<b>Hello</b>") == "Hello"


def test_strip_html_removes_tag_with_attributes():
    result = _strip_html('<a href="http://example.com">Click</a>')
    assert result == "Click"


def test_strip_html_nested_elements():
    result = _strip_html("<p><strong>Bold</strong> text</p>")
    assert "Bold" in result
    assert "text" in result
    assert "<" not in result


def test_strip_html_plain_text_unchanged():
    assert _strip_html("Hello world") == "Hello world"


def test_strip_html_empty_string():
    assert _strip_html("") == ""


def test_strip_html_entities_converted():
    result = _strip_html("&amp;")
    assert "&" in result  # html.parser converts &amp; → &


# ---------------------------------------------------------------------------
# _decode_header
# ---------------------------------------------------------------------------

def test_decode_header_plain_ascii():
    assert _decode_header("Hello World") == "Hello World"


def test_decode_header_rfc2047_utf8_base64():
    encoded = base64.b64encode("テスト".encode("utf-8")).decode("ascii")
    raw = f"=?utf-8?b?{encoded}?="
    assert "テスト" in _decode_header(raw)


def test_decode_header_rfc2047_latin1():
    encoded = base64.b64encode("café".encode("latin-1")).decode("ascii")
    raw = f"=?iso-8859-1?b?{encoded}?="
    result = _decode_header(raw)
    assert "caf" in result  # at minimum the ASCII portion survives


def test_decode_header_empty_string():
    assert _decode_header("") == ""


def test_decode_header_none_safe():
    assert _decode_header(None) == ""  # type: ignore[arg-type]


def test_decode_header_unknown_charset_does_not_raise():
    encoded = base64.b64encode(b"hello").decode("ascii")
    raw = f"=?x-totally-fake-charset?b?{encoded}?="
    result = _decode_header(raw)
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# _extract_body
# ---------------------------------------------------------------------------

def test_extract_body_single_part_plain():
    msg = _stdlib_email.message_from_string(
        "Content-Type: text/plain; charset=utf-8\r\n\r\nHello world"
    )
    assert _provider()._extract_body(msg) == "Hello world"


def test_extract_body_single_part_html_stripped():
    msg = _stdlib_email.message_from_string(
        "Content-Type: text/html; charset=utf-8\r\n\r\n<b>Hello</b>"
    )
    result = _provider()._extract_body(msg)
    assert "Hello" in result
    assert "<b>" not in result


def test_extract_body_multipart_prefers_plain_over_html():
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    msg = MIMEMultipart("alternative")
    msg.attach(MIMEText("Plain text", "plain", "utf-8"))
    msg.attach(MIMEText("<b>HTML text</b>", "html", "utf-8"))
    assert _provider()._extract_body(msg) == "Plain text"


def test_extract_body_multipart_html_fallback_when_no_plain():
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    msg = MIMEMultipart("alternative")
    msg.attach(MIMEText("<p>Only HTML</p>", "html", "utf-8"))
    result = _provider()._extract_body(msg)
    assert "Only HTML" in result


def test_extract_body_skips_attachments():
    from email.mime.base import MIMEBase
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    msg = MIMEMultipart("mixed")
    msg.attach(MIMEText("Body text", "plain", "utf-8"))
    attach = MIMEBase("application", "pdf")
    attach.add_header("Content-Disposition", "attachment", filename="file.pdf")
    attach.set_payload(b"binary")
    msg.attach(attach)
    assert _provider()._extract_body(msg) == "Body text"


def test_extract_body_empty_payload_returns_empty():
    msg = _stdlib_email.message_from_string(
        "Content-Type: text/plain; charset=utf-8\r\n\r\n"
    )
    assert _provider()._extract_body(msg) == ""


# ---------------------------------------------------------------------------
# _parse_envelope
# ---------------------------------------------------------------------------

def test_parse_envelope_returns_email_message_type():
    from iris.email_provider import EmailMessage

    result = _provider()._parse_envelope("42", _make_raw())
    assert isinstance(result, EmailMessage)


def test_parse_envelope_subject_decoded():
    result = _provider()._parse_envelope("42", _make_raw(subject="Meeting Notes"))
    assert result.subject == "Meeting Notes"


def test_parse_envelope_sender_name_and_email_extracted():
    result = _provider()._parse_envelope("42", _make_raw(from_addr="Alice <alice@example.com>"))
    assert result.sender_name == "Alice"
    assert result.sender_email == "alice@example.com"


def test_parse_envelope_no_display_name_falls_back_to_email():
    result = _provider()._parse_envelope("42", _make_raw(from_addr="alice@example.com"))
    assert result.sender_name == "alice@example.com"


def test_parse_envelope_uid_preserved():
    result = _provider()._parse_envelope("99", _make_raw())
    assert result.id == "99"


def test_parse_envelope_returns_none_on_exception():
    with patch("iris.email_provider._email_stdlib.message_from_bytes",
               side_effect=ValueError("corrupted")):
        result = _provider()._parse_envelope("1", b"anything")
    assert result is None
