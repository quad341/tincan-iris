"""Tests for the email connector wiring — configured_email_skills + Brain hookup.

The email lane activates only when host + user + password are ALL configured
(password via env or secrets.toml); otherwise the brain simply omits it, so qwen
gets the email skills exactly when the lane is set up.
"""
from __future__ import annotations

import pytest

from iris import settings
from iris.email_skill import configured_email_skills

_EMAIL_ENV = (
    "IRIS_EMAIL_IMAP_HOST", "IRIS_EMAIL_IMAP_PORT", "IRIS_EMAIL_SMTP_HOST",
    "IRIS_EMAIL_SMTP_PORT", "IRIS_EMAIL_USER", "IRIS_EMAIL_PASSWORD",
    "IRIS_CONFIG", "IRIS_SECRETS", "IRIS_HOME",
)

_EMAIL_SKILL_NAMES = {"read_email", "send_email", "confirm_email", "cancel_email", "triage_email"}


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    for v in _EMAIL_ENV:
        monkeypatch.delenv(v, raising=False)
    settings.reload()
    yield
    settings.reload()


def _configure(monkeypatch):
    monkeypatch.setenv("IRIS_EMAIL_IMAP_HOST", "imap.gmail.com")
    monkeypatch.setenv("IRIS_EMAIL_SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setenv("IRIS_EMAIL_USER", "me@gmail.com")
    monkeypatch.setenv("IRIS_EMAIL_PASSWORD", "app-pw")


def test_unconfigured_returns_empty():
    assert configured_email_skills() == []


def test_partial_config_returns_empty(monkeypatch):
    monkeypatch.setenv("IRIS_EMAIL_IMAP_HOST", "imap.gmail.com")
    monkeypatch.setenv("IRIS_EMAIL_USER", "me@gmail.com")  # no password
    assert configured_email_skills() == []


def test_configured_returns_email_skills(monkeypatch):
    _configure(monkeypatch)
    assert {s.name for s in configured_email_skills()} == _EMAIL_SKILL_NAMES


def test_password_via_secrets_file_activates_lane(tmp_path, monkeypatch):
    monkeypatch.setenv("IRIS_EMAIL_IMAP_HOST", "imap.gmail.com")
    monkeypatch.setenv("IRIS_EMAIL_USER", "me@gmail.com")
    sp = tmp_path / "secrets.toml"
    sp.write_text('[email]\npassword = "app-pw"\n')
    sp.chmod(0o600)
    monkeypatch.setenv("IRIS_SECRETS", str(sp))
    settings.reload()
    assert {s.name for s in configured_email_skills()} == _EMAIL_SKILL_NAMES


def test_brain_registers_email_when_configured(monkeypatch):
    _configure(monkeypatch)
    from iris.brain import Brain
    brain = Brain()
    assert _EMAIL_SKILL_NAMES <= set(brain.skills.names())


def test_brain_omits_email_when_unconfigured():
    from iris.brain import Brain
    brain = Brain()
    assert not (_EMAIL_SKILL_NAMES & set(brain.skills.names()))
