"""iris-auth — guided connector setup.

Subcommands:
  gmail   set up the email lane (IMAP/SMTP via a Gmail App Password)

One command instead of hand-editing TOML: it prompts for the App Password
(hidden), verifies the login, writes the non-secret bits to config.toml and the
password to a chmod-600 secrets.toml, and tells you it worked. An ``IRIS_*`` env
var still overrides anything written here.

(Calendar OAuth — ``gcal`` — lands next; it needs a Google OAuth client.)
"""
from __future__ import annotations

import argparse
import getpass
import sys
import tomllib
from pathlib import Path

from . import settings

_GMAIL = {
    "imap_host": "imap.gmail.com",
    "imap_port": 993,
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 587,
}


def _toml_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _save_email_secret(password: str) -> Path:
    """Merge the email password into ``$IRIS_HOME/secrets.toml`` (chmod 600).

    Reads any existing secrets, sets ``[email] password``, and rewrites the file.
    Other sections/keys are preserved; comments are not (it's a generated file).
    """
    path = settings.secrets_path()
    data: dict = {}
    if path.exists():
        try:
            data = tomllib.loads(path.read_text())
        except tomllib.TOMLDecodeError:
            data = {}
    data.setdefault("email", {})["password"] = password

    lines = [
        "# Iris secrets — credentials only. chmod 600, never commit (gitignored).\n",
        "# Managed by `iris-auth`; an IRIS_* env var still overrides these.\n",
    ]
    for section, kv in data.items():
        lines.append(f"\n[{section}]\n")
        for key, val in kv.items():
            lines.append(f'{key} = "{_toml_escape(str(val))}"\n')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(lines))
    path.chmod(0o600)
    return path


def _ensure_email_config(email: str) -> Path:
    """Append a Gmail ``[email]`` block to config.toml when one isn't present.

    If ``[email]`` already exists (the operator may have customized it), it's
    left untouched — only the secret is updated elsewhere.
    """
    path = settings.config_path()
    text = path.read_text() if path.exists() else ""
    if "[email]" in text:
        return path
    block = (
        ("\n" if text and not text.endswith("\n") else "")
        + "\n[email]\n"
        f'imap_host = "{_GMAIL["imap_host"]}"\n'
        f'imap_port = {_GMAIL["imap_port"]}\n'
        f'smtp_host = "{_GMAIL["smtp_host"]}"\n'
        f'smtp_port = {_GMAIL["smtp_port"]}\n'
        f'user = "{_toml_escape(email)}"\n'
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + block)
    return path


def _gmail(args: argparse.Namespace) -> int:
    email = (args.email or settings.get("IRIS_EMAIL_USER") or "").strip()
    if not email:
        email = input("Gmail address: ").strip()
    if not email:
        print("iris-auth: no email address given.", file=sys.stderr)
        return 1

    print("You'll need a Gmail App Password (not your normal password):")
    print("  Google Account → Security → 2-Step Verification → App passwords → generate (Mail).")
    password = getpass.getpass(f"App Password for {email} (input hidden): ").replace(" ", "").strip()
    if not password:
        print("iris-auth: no password entered.", file=sys.stderr)
        return 1

    print("Verifying IMAP login…", flush=True)
    from .email_check import _check_imap
    ok, err = _check_imap(_GMAIL["imap_host"], _GMAIL["imap_port"], email, password)
    if not ok:
        print(f"✗ Login failed:\n{err}", file=sys.stderr)
        print(
            "  Use a 16-char App Password (2-Step Verification must be on) — "
            "not your normal password.",
            file=sys.stderr,
        )
        return 1

    cfg = _ensure_email_config(email)
    sec = _save_email_secret(password)
    print(f"✓ Email connected for {email}.")
    print(f"  config: {cfg}")
    print(f"  secret: {sec} (chmod 600)")
    print('  Try it — ask Iris: "any important email?"')
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="iris-auth", description="Guided connector setup for Iris."
    )
    sub = parser.add_subparsers(dest="provider", required=True)
    g = sub.add_parser(
        "gmail", help="set up the email lane (IMAP/SMTP via a Gmail App Password)"
    )
    g.add_argument(
        "email", nargs="?",
        help="Gmail address (default: config [email].user, else prompt)",
    )
    g.set_defaults(func=_gmail)

    ns = parser.parse_args(argv if argv is not None else sys.argv[1:])
    return ns.func(ns)


if __name__ == "__main__":
    raise SystemExit(main())
