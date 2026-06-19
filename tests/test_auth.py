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
