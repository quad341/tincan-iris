"""Tests for calendar OAuth token persistence + refresh."""
from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

from iris.calendar import CalendarClient, save_token


def _resp(data):
    r = MagicMock()
    r.__enter__ = lambda s: s
    r.__exit__ = MagicMock(return_value=False)
    r.read.return_value = json.dumps(data).encode()
    return r


def test_save_token_chmod_600(tmp_path):
    p = save_token({"access_token": "AT"}, path=tmp_path / "gcal.json")
    assert json.loads(p.read_text())["access_token"] == "AT"
    assert oct(p.stat().st_mode)[-3:] == "600"


def test_refresh_when_expired_updates_and_persists(tmp_path):
    p = tmp_path / "gcal.json"
    p.write_text(json.dumps({
        "access_token": "OLD", "refresh_token": "RT",
        "client_id": "cid", "client_secret": "csec",
        "expires_at": time.time() - 10,                 # expired
        "token_uri": "https://oauth2.googleapis.com/token",
    }))
    c = CalendarClient(token_path=p)
    with patch("iris.calendar.urllib.request.urlopen",
               return_value=_resp({"access_token": "NEW", "expires_in": 3600})):
        headers = c._headers()
    assert headers["Authorization"] == "Bearer NEW"
    assert json.loads(p.read_text())["access_token"] == "NEW"   # persisted


def test_no_refresh_when_token_valid(tmp_path):
    p = tmp_path / "gcal.json"
    p.write_text(json.dumps({
        "access_token": "AT", "refresh_token": "RT", "client_id": "cid",
        "expires_at": time.time() + 3600,               # still valid
    }))
    c = CalendarClient(token_path=p)
    with patch("iris.calendar.urllib.request.urlopen",
               side_effect=AssertionError("must not refresh a valid token")):
        headers = c._headers()
    assert headers["Authorization"] == "Bearer AT"


def test_no_refresh_for_static_token(tmp_path):
    p = tmp_path / "gcal.json"
    p.write_text(json.dumps({"access_token": "STATIC"}))   # no refresh_token/client_id
    c = CalendarClient(token_path=p)
    with patch("iris.calendar.urllib.request.urlopen",
               side_effect=AssertionError("must not refresh a static token")):
        headers = c._headers()
    assert headers["Authorization"] == "Bearer STATIC"
