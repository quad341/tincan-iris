"""iris-auth — guided connector setup.

Subcommands:
  gmail   set up the email lane (IMAP/SMTP via a Gmail App Password)
  gcal    set up Google Calendar (OAuth installed-app / loopback flow)

One command instead of hand-editing TOML / wrangling OAuth. ``gmail`` prompts for
the App Password (hidden), verifies the login, and writes config + a chmod-600
secret. ``gcal`` runs Google's consent flow in your browser, catches the
loopback redirect, exchanges the code, and saves a refreshable token (it needs a
Google Cloud OAuth 'Desktop app' client — pass its credentials.json). An
``IRIS_*`` env var still overrides anything written here.
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

    print("You'll need a Gmail App Password (not your normal password; 2-Step Verification must be on):")
    print("  Create one:  https://myaccount.google.com/apppasswords")
    print("  Help:        https://support.google.com/mail/answer/185833")
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


# ---------------------------------------------------------------------------
# gcal — Google Calendar OAuth (installed-app / loopback flow)
# ---------------------------------------------------------------------------

_GCAL_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
_GCAL_TOKEN = "https://oauth2.googleapis.com/token"
_GCAL_SCOPE = "https://www.googleapis.com/auth/calendar"


def _load_gcal_client(credentials_path: str | None) -> tuple[str, str]:
    """Return (client_id, client_secret) from a Google credentials.json, or prompt.

    Accepts the standard download shapes (``{"installed": {...}}`` /
    ``{"web": {...}}``) or a flat ``{"client_id", "client_secret"}``.
    """
    if credentials_path:
        import json
        data = json.loads(Path(credentials_path).expanduser().read_text())
        node = data.get("installed") or data.get("web") or data
        return node["client_id"], node["client_secret"]
    cid = input("Google OAuth client_id: ").strip()
    csec = getpass.getpass("Google OAuth client_secret (input hidden): ").strip()
    return cid, csec


def _build_gcal_auth_url(client_id: str, redirect_uri: str, state: str) -> str:
    import urllib.parse
    return _GCAL_AUTH + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": _GCAL_SCOPE,
        "access_type": "offline",   # ask for a refresh token
        "prompt": "consent",        # force it even on re-auth
        "state": state,
    })


def _exchange_gcal_code(code: str, client_id: str, client_secret: str, redirect_uri: str) -> dict:
    import json
    import urllib.parse
    import urllib.request
    body = urllib.parse.urlencode({
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }).encode()
    req = urllib.request.Request(_GCAL_TOKEN, body, method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def _gcal(args: argparse.Namespace) -> int:
    import http.server
    import secrets as _secrets
    import time
    import urllib.parse
    import webbrowser

    try:
        client_id, client_secret = _load_gcal_client(args.credentials)
    except (OSError, KeyError, ValueError) as exc:
        print(f"iris-auth: couldn't read the OAuth client — {exc}", file=sys.stderr)
        print(
            "  Create an OAuth 'Desktop app' client in Google Cloud Console (enable the\n"
            "  Google Calendar API), then pass its credentials.json:\n"
            "      iris-auth gcal ~/Downloads/credentials.json\n"
            "  …or run `iris-auth gcal` and paste the client_id / client_secret.",
            file=sys.stderr,
        )
        return 1
    if not client_id or not client_secret:
        print("iris-auth: no client_id / client_secret given.", file=sys.stderr)
        return 1

    holder: dict[str, str | None] = {}

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 — http.server API
            params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            holder["code"] = (params.get("code") or [None])[0]
            holder["state"] = (params.get("state") or [None])[0]
            holder["error"] = (params.get("error") or [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h2>Iris: calendar authorized.</h2><p>You can close this tab.</p>")

        def log_message(self, *_a):  # silence the default request logging
            pass

    httpd = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    redirect_uri = f"http://127.0.0.1:{httpd.server_address[1]}/"
    state = _secrets.token_urlsafe(16)
    url = _build_gcal_auth_url(client_id, redirect_uri, state)

    print("Opening your browser to authorize Google Calendar…")
    print(f"  If it doesn't open, visit:\n  {url}")
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001 — headless box; the printed URL is the fallback
        pass
    httpd.handle_request()   # blocks until the redirect arrives
    httpd.server_close()

    if holder.get("error") or not holder.get("code"):
        print(f"✗ Authorization failed: {holder.get('error') or 'no code returned'}", file=sys.stderr)
        return 1
    if holder.get("state") != state:
        print("✗ State mismatch — aborting (possible CSRF).", file=sys.stderr)
        return 1

    print("Exchanging the authorization code…", flush=True)
    try:
        tok = _exchange_gcal_code(holder["code"], client_id, client_secret, redirect_uri)
    except Exception as exc:  # noqa: BLE001
        print(f"✗ Token exchange failed: {exc}", file=sys.stderr)
        return 1
    if "access_token" not in tok:
        print(f"✗ Token exchange returned no access_token: {tok}", file=sys.stderr)
        return 1

    from .calendar import _TOKEN_URI, save_token
    token = {
        "access_token": tok["access_token"],
        "refresh_token": tok.get("refresh_token", ""),
        "expires_at": time.time() + tok.get("expires_in", 3600),
        "client_id": client_id,
        "client_secret": client_secret,
        "token_uri": _TOKEN_URI,
    }
    path = save_token(token)
    if not token["refresh_token"]:
        print("  note: no refresh_token returned — revoke iris's access in your Google account, then re-run.")
    print(f"✓ Calendar authorized. token: {path} (chmod 600)")
    print('  Try it — ask Iris: "am I free at 3pm?"')
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

    c = sub.add_parser(
        "gcal", help="set up Google Calendar (OAuth — needs a Google Cloud OAuth client)"
    )
    c.add_argument(
        "credentials", nargs="?",
        help="path to the OAuth client credentials.json (else prompt for id/secret)",
    )
    c.set_defaults(func=_gcal)

    ns = parser.parse_args(argv if argv is not None else sys.argv[1:])
    return ns.func(ns)


if __name__ == "__main__":
    raise SystemExit(main())
