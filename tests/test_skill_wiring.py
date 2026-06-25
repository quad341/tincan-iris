"""Tests for skill_wiring.optional_skills — the offline lanes the Brain registers.

Local lanes (notes, roster, web search) are always present; email registers only
when configured. Stores are injected (tmp paths) so these don't touch real data.
"""
from __future__ import annotations

import pytest

from iris import settings
from iris.notes import NotesStore
from iris.roster import RosterStore
from iris.skill_wiring import optional_skills

_EMAIL_ENV = (
    "IRIS_EMAIL_IMAP_HOST", "IRIS_EMAIL_USER", "IRIS_EMAIL_PASSWORD",
    "IRIS_CONFIG", "IRIS_SECRETS", "IRIS_HOME",
)


@pytest.fixture
def stores(tmp_path):
    return {
        "notes_store": NotesStore(str(tmp_path / "notes.db")),
        "roster": RosterStore(str(tmp_path / "roster.db")),
    }


@pytest.fixture(autouse=True)
def _no_email(monkeypatch):
    for v in _EMAIL_ENV:
        monkeypatch.delenv(v, raising=False)
    settings.reload()
    yield
    settings.reload()


def test_local_lanes_always_present(stores):
    names = {s.name for s in optional_skills(**stores)}
    assert "web_search" in names
    assert "capture_note" in names              # notes
    assert {"list_notes", "mark_done"} <= names
    assert "roster_add_contact" in names         # roster


def test_delegate_lane_always_present(stores):
    # Operator-only iris→mayor delegation is always registered (gc handles the send).
    names = {s.name for s in optional_skills(**stores)}
    assert {"delegate_to_mayor", "delegate_confirm", "delegate_cancel"} <= names


def test_email_absent_when_unconfigured(stores):
    names = {s.name for s in optional_skills(**stores)}
    assert "read_email" not in names


def test_email_present_when_configured(stores, monkeypatch):
    monkeypatch.setenv("IRIS_EMAIL_IMAP_HOST", "imap.gmail.com")
    monkeypatch.setenv("IRIS_EMAIL_USER", "me@x.com")
    monkeypatch.setenv("IRIS_EMAIL_PASSWORD", "pw")
    names = {s.name for s in optional_skills(**stores)}
    assert {"read_email", "triage_email", "send_email"} <= names


def test_calendar_gate_absent_without_token():
    from unittest.mock import MagicMock
    from iris.calendar import configured_calendar_skills
    c = MagicMock()
    c.has_token.return_value = False
    assert configured_calendar_skills(client=c) == []


def test_calendar_gate_present_with_token():
    from unittest.mock import MagicMock
    from iris.calendar import configured_calendar_skills
    c = MagicMock()
    c.has_token.return_value = True
    assert len(configured_calendar_skills(client=c)) == 3
