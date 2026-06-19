"""Tests for iris-auth — the guided connector setup CLI (gmail)."""
from __future__ import annotations

import tomllib
from unittest.mock import patch

import pytest

from iris import auth, settings


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    for v in ("IRIS_CONFIG", "IRIS_SECRETS", "IRIS_EMAIL_USER", "IRIS_EMAIL_PASSWORD"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("IRIS_HOME", str(tmp_path))
    settings.reload()
    yield
    settings.reload()


def test_gmail_success_writes_config_and_secret(tmp_path):
    with patch("iris.auth.getpass.getpass", return_value="abcd efgh ijkl mnop"), \
         patch("iris.email_check._check_imap", return_value=(True, "")):
        rc = auth.main(["gmail", "me@gmail.com"])
    assert rc == 0
    cfg = (tmp_path / "config.toml").read_text()
    assert "[email]" in cfg
    assert 'user = "me@gmail.com"' in cfg
    assert "imap.gmail.com" in cfg
    sec = tmp_path / "secrets.toml"
    assert oct(sec.stat().st_mode)[-3:] == "600"
    # spaces stripped from the pasted app password
    assert settings.get_secret("IRIS_EMAIL_PASSWORD") == "abcdefghijklmnop"


def test_gmail_aborts_on_bad_password_no_secret(tmp_path):
    with patch("iris.auth.getpass.getpass", return_value="wrongpw"), \
         patch("iris.email_check._check_imap", return_value=(False, "   auth failed")):
        rc = auth.main(["gmail", "me@gmail.com"])
    assert rc == 1
    assert not (tmp_path / "secrets.toml").exists()


def test_gmail_preserves_existing_email_config(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[email]\nimap_host = "imap.custom.test"\nuser = "x@custom.test"\n')
    with patch("iris.auth.getpass.getpass", return_value="pw"), \
         patch("iris.email_check._check_imap", return_value=(True, "")):
        rc = auth.main(["gmail", "x@custom.test"])
    assert rc == 0
    text = cfg.read_text()
    assert text.count("[email]") == 1        # not duplicated
    assert "imap.custom.test" in text         # left untouched


def test_secret_merge_preserves_other_sections(tmp_path):
    sec = tmp_path / "secrets.toml"
    sec.write_text('[other]\ntoken = "keepme"\n')
    sec.chmod(0o600)
    with patch("iris.auth.getpass.getpass", return_value="pw"), \
         patch("iris.email_check._check_imap", return_value=(True, "")):
        auth.main(["gmail", "me@gmail.com"])
    data = tomllib.loads(sec.read_text())
    assert data["other"]["token"] == "keepme"
    assert data["email"]["password"] == "pw"


def test_gmail_uses_configured_user_when_no_arg(monkeypatch):
    monkeypatch.setenv("IRIS_EMAIL_USER", "configured@gmail.com")
    settings.reload()
    with patch("iris.auth.getpass.getpass", return_value="pw"), \
         patch("iris.email_check._check_imap", return_value=(True, "")):
        rc = auth.main(["gmail"])
    assert rc == 0
    assert settings.get_secret("IRIS_EMAIL_PASSWORD") == "pw"


# ---------------------------------------------------------------------------
# gcal — OAuth helpers (the interactive loopback is verified live, not here)
# ---------------------------------------------------------------------------

def _mock_resp(data):
    from unittest.mock import MagicMock
    import json as _json
    r = MagicMock()
    r.__enter__ = lambda s: s
    r.__exit__ = MagicMock(return_value=False)
    r.read.return_value = _json.dumps(data).encode()
    return r


def test_load_gcal_client_from_installed_credentials(tmp_path):
    import json
    cred = tmp_path / "credentials.json"
    cred.write_text(json.dumps({"installed": {"client_id": "cid.apps", "client_secret": "csec"}}))
    assert auth._load_gcal_client(str(cred)) == ("cid.apps", "csec")


def test_load_gcal_client_from_flat_credentials(tmp_path):
    import json
    cred = tmp_path / "c.json"
    cred.write_text(json.dumps({"client_id": "x", "client_secret": "y"}))
    assert auth._load_gcal_client(str(cred)) == ("x", "y")


def test_build_gcal_auth_url_has_offline_consent_and_scope():
    url = auth._build_gcal_auth_url("cid", "http://127.0.0.1:5555/", "st8")
    assert url.startswith(auth._GCAL_AUTH)
    assert "client_id=cid" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "state=st8" in url
    assert "calendar" in url  # the scope
    assert "127.0.0.1%3A5555" in url or "127.0.0.1:5555" in url


def test_exchange_gcal_code_posts_and_parses():
    with patch("urllib.request.urlopen", return_value=_mock_resp({"access_token": "AT", "refresh_token": "RT", "expires_in": 3600})):
        tok = auth._exchange_gcal_code("code123", "cid", "csec", "http://127.0.0.1:1/")
    assert tok["access_token"] == "AT"
    assert tok["refresh_token"] == "RT"


def test_gcal_howto_on_bad_credentials_path(tmp_path, capsys):
    rc = auth.main(["gcal", str(tmp_path / "nope.json")])
    cap = capsys.readouterr()
    text = cap.out + cap.err
    assert rc == 1
    # teaches how to make a client instead of a circular error
    assert "console.cloud.google.com" in text
    assert "Desktop app" in text
    assert "client_secret" in text


def test_gcal_howto_when_no_credentials(capsys):
    with patch("builtins.input", return_value=""), \
         patch("iris.auth.getpass.getpass", return_value=""):
        rc = auth.main(["gcal"])
    assert rc == 1
    assert "console.cloud.google.com" in capsys.readouterr().out


def test_project_from_client_id_extracts_number():
    assert auth._project_from_client_id(
        "967870440993-abc.apps.googleusercontent.com"
    ) == "967870440993"
    assert auth._project_from_client_id("not-a-number.apps") == ""
    assert auth._project_from_client_id("plainstring") == ""


def test_calendar_api_url_pins_project_when_known():
    assert auth._calendar_api_url("123").endswith(
        "calendar-json.googleapis.com?project=123"
    )
    assert "?project=" not in auth._calendar_api_url("")


def test_gcal_howto_warns_to_check_project_selector(capsys):
    auth._gcal_howto()
    assert "project selector" in capsys.readouterr().out.lower()
