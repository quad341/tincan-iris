"""iris-email-check — verify IMAP/SMTP email lane configuration.

Usage:
    iris-email-check                   # check and print results
    iris-email-check --quiet           # exit 0 if OK, 1 if any check fails

Reads config from environment variables:
    IRIS_EMAIL_IMAP_HOST, IRIS_EMAIL_IMAP_PORT
    IRIS_EMAIL_SMTP_HOST, IRIS_EMAIL_SMTP_PORT
    IRIS_EMAIL_USER, IRIS_EMAIL_PASSWORD

Helpful for operators who want to verify their Gmail App Password setup before
starting the full daemon.  Does NOT require the console or llama-server to be
running.
"""
from __future__ import annotations

import imaplib
import os
import smtplib
import sys

_CONNECT_TIMEOUT = 10

_GMAIL_APP_PASSWORD_URL = "https://support.google.com/accounts/answer/185833"
_GMAIL_HINT = (
    "Hint: Gmail requires an App Password when 2FA is enabled.\n"
    f"   See: {_GMAIL_APP_PASSWORD_URL}"
)


def _check_imap(host: str, port: int, user: str, password: str) -> tuple[bool, str]:
    """Return (ok, detail_message)."""
    print(f"→ Connecting to {host}:{port}…  ", end="", flush=True)
    try:
        conn = imaplib.IMAP4_SSL(host, port, timeout=_CONNECT_TIMEOUT)
    except Exception as exc:  # noqa: BLE001
        print("FAILED")
        return False, f"   IMAP connection error: {exc}"
    print("OK")

    print(f"→ Authentication: {user}…  ", end="", flush=True)
    try:
        conn.login(user, password)
    except imaplib.IMAP4.error as exc:
        print("FAILED")
        hint = _GMAIL_HINT if "gmail" in host.lower() else ""
        msg = f"   IMAP error: {exc}"
        if hint:
            msg += f"\n   {hint}"
        conn.logout()
        return False, msg
    print("OK")

    try:
        typ, data = conn.select("INBOX", readonly=True)
        if typ == "OK" and data and data[0]:
            typ2, search_data = conn.uid("SEARCH", None, "UNSEEN")
            if typ2 == "OK" and search_data and search_data[0]:
                count = len(search_data[0].split()) if search_data[0] else 0
                print(f"→ INBOX: {count} unread {'message' if count == 1 else 'messages'}")
            else:
                print("→ INBOX: accessible")
    except Exception:  # noqa: BLE001
        pass
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass

    return True, ""


def _check_smtp(host: str, port: int) -> tuple[bool, str]:
    """Return (ok, detail_message). Does NOT attempt to send a test message."""
    print(f"→ SMTP: {host}:{port}…  ", end="", flush=True)
    try:
        with smtplib.SMTP(host, port, timeout=_CONNECT_TIMEOUT) as smtp:
            smtp.ehlo()
            # Check that STARTTLS is advertised (don't actually upgrade to avoid
            # needing credentials for the SMTP check).
            if smtp.has_extn("STARTTLS"):
                print("OK (STARTTLS supported — send test skipped)")
            else:
                print("OK (warning: STARTTLS not advertised)")
        return True, ""
    except Exception as exc:  # noqa: BLE001
        print("FAILED")
        return False, f"   SMTP error: {exc}"


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(
        prog="iris-email-check",
        description="Verify IMAP/SMTP email lane configuration.",
    )
    parser.add_argument("--quiet", action="store_true", help="Exit 0 if OK, 1 if any check fails; no output.")
    args = parser.parse_args()

    imap_host = os.environ.get("IRIS_EMAIL_IMAP_HOST", "").strip()
    imap_port = int(os.environ.get("IRIS_EMAIL_IMAP_PORT", "993"))
    smtp_host = os.environ.get("IRIS_EMAIL_SMTP_HOST", "").strip()
    smtp_port = int(os.environ.get("IRIS_EMAIL_SMTP_PORT", "587"))
    user = os.environ.get("IRIS_EMAIL_USER", "").strip()
    password = os.environ.get("IRIS_EMAIL_PASSWORD", "").strip()

    if not imap_host:
        if not args.quiet:
            print("Email lane is disabled (IRIS_EMAIL_IMAP_HOST not set).")
            print("Set IRIS_EMAIL_IMAP_HOST, IRIS_EMAIL_USER, and IRIS_EMAIL_PASSWORD to enable.")
        return 1

    if not user or not password:
        if not args.quiet:
            print("IRIS_EMAIL_USER or IRIS_EMAIL_PASSWORD is not set.")
        return 1

    if args.quiet:
        # Quick silent check
        try:
            conn = imaplib.IMAP4_SSL(imap_host, imap_port, timeout=_CONNECT_TIMEOUT)
            conn.login(user, password)
            conn.logout()
            return 0
        except Exception:  # noqa: BLE001
            return 1

    errors: list[str] = []
    ok_imap, err_imap = _check_imap(imap_host, imap_port, user, password)
    if not ok_imap:
        errors.append(err_imap)

    if smtp_host:
        ok_smtp, err_smtp = _check_smtp(smtp_host, smtp_port)
        if not ok_smtp:
            errors.append(err_smtp)
    else:
        print("→ SMTP: not configured (IRIS_EMAIL_SMTP_HOST not set — send disabled)")

    print()
    if errors:
        for e in errors:
            print(e)
        print("Email lane: NOT READY")
        return 1

    print("Email lane: READY")
    return 0


if __name__ == "__main__":
    sys.exit(main())
