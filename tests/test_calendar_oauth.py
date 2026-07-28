"""Tests for calendar OAuth token persistence + refresh."""
from __future__ import annotations

import io
import json
import time
import urllib.error
from unittest.mock import MagicMock, patch

from iris.calendar import CalendarClient, _utc_z, save_token


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


# ---------------------------------------------------------------------------
# verify_reachable — setup-time smoke probe (API enabled + token usable)
# ---------------------------------------------------------------------------

_SERVICE_DISABLED = {
    "error": {
        "code": 403,
        "message": "Google Calendar API has not been used in project 967870440993 before or it is disabled.",
        "status": "PERMISSION_DENIED",
        "details": [
            {
                "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                "reason": "SERVICE_DISABLED",
                "metadata": {
                    "activationUrl": "https://console.developers.google.com/apis/api/calendar-json.googleapis.com/overview?project=967870440993"
                },
            }
        ],
    }
}


def _http_error(code, data):
    return urllib.error.HTTPError(
        url="https://www.googleapis.com/calendar/v3/freeBusy",
        code=code, msg="err", hdrs={}, fp=io.BytesIO(json.dumps(data).encode()),
    )


def _valid_token_path(tmp_path):
    p = tmp_path / "gcal.json"
    p.write_text(json.dumps({
        "access_token": "AT", "refresh_token": "RT", "client_id": "cid",
        "expires_at": time.time() + 3600,           # valid -> probe must not refresh
    }))
    return p


def test_verify_reachable_ok_on_200(tmp_path):
    c = CalendarClient(token_path=_valid_token_path(tmp_path))
    with patch("iris.calendar.urllib.request.urlopen",
               return_value=_resp({"calendars": {"primary": {"busy": []}}})):
        ok, hint = c.verify_reachable()
    assert ok and hint == ""


def test_verify_reachable_surfaces_activation_url_when_api_disabled(tmp_path):
    c = CalendarClient(token_path=_valid_token_path(tmp_path))
    with patch("iris.calendar.urllib.request.urlopen",
               side_effect=_http_error(403, _SERVICE_DISABLED)):
        ok, hint = c.verify_reachable()
    assert not ok
    assert "project=967870440993" in hint       # project-pinned enable URL
    assert "enable" in hint.lower()


def test_verify_reachable_no_token(tmp_path):
    c = CalendarClient(token_path=tmp_path / "absent.json")
    ok, hint = c.verify_reachable()
    assert not ok
    assert "iris auth gcal" in hint


# ---------------------------------------------------------------------------
# Timezone correctness (ti-3akk) — a naive ISO datetime is LOCAL, not UTC.
# Regression: free/busy used to blindly append "Z", treating "3pm" as 3pm UTC.
# ---------------------------------------------------------------------------

def test_utc_z_honors_explicit_offset():
    # 3pm at -07:00 is 22:00 UTC — deterministic regardless of the host's tz
    assert _utc_z("2026-06-19T15:00:00-07:00") == "2026-06-19T22:00:00Z"


def test_utc_z_idempotent_on_utc_inputs():
    assert _utc_z("2026-06-19T15:00:00Z") == "2026-06-19T15:00:00Z"
    assert _utc_z("2026-06-19T15:00:00+00:00") == "2026-06-19T15:00:00Z"


def test_utc_z_naive_is_treated_as_local():
    import datetime as _dt
    naive = "2026-06-19T15:00:00"
    expected = (
        _dt.datetime.fromisoformat(naive).astimezone(_dt.UTC)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    assert _utc_z(naive) == expected
    # the old bug blindly appended "Z"; that's only correct on a UTC host
    if _dt.datetime.fromisoformat(naive).astimezone().utcoffset() != _dt.timedelta(0):
        assert _utc_z(naive) != "2026-06-19T15:00:00Z"


def test_free_busy_sends_utc_timemin(tmp_path):
    c = CalendarClient(token_path=_valid_token_path(tmp_path))
    captured = {}
    with patch.object(c, "_post",
                      side_effect=lambda path, body: captured.update(body) or {"calendars": {}}):
        c.free_busy(start="2026-06-19T15:00:00-07:00", end="2026-06-19T16:00:00-07:00")
    assert captured["timeMin"] == "2026-06-19T22:00:00Z"
    assert captured["timeMax"] == "2026-06-19T23:00:00Z"


def test_create_event_sends_timezone_aware_datetime(tmp_path):
    import datetime as _dt
    c = CalendarClient(token_path=_valid_token_path(tmp_path))
    captured = {}
    with patch.object(c, "_post",
                      side_effect=lambda path, body: captured.update(body) or {"id": "e1", "summary": "X"}):
        c.create_event(title="X", start="2026-06-20T12:00:00")          # naive input
    # the API rejects an offset-less dateTime — we must send an aware one
    assert _dt.datetime.fromisoformat(captured["start"]["dateTime"]).tzinfo is not None
    assert _dt.datetime.fromisoformat(captured["end"]["dateTime"]).tzinfo is not None


def test_move_event_keeps_duration_and_is_timezone_aware(tmp_path):
    import datetime as _dt
    c = CalendarClient(token_path=_valid_token_path(tmp_path))
    existing = {
        "start": {"dateTime": "2026-06-20T09:00:00-07:00"},
        "end": {"dateTime": "2026-06-20T09:30:00-07:00"},
    }
    captured = {}
    with patch.object(c, "_get", return_value=existing), \
         patch.object(c, "_patch",
                      side_effect=lambda path, body: captured.update(body) or {"id": "e1", "summary": "X"}):
        c.move_event(event_id="e1", new_start="2026-06-21T14:00:00")    # naive input
    s = _dt.datetime.fromisoformat(captured["start"]["dateTime"])
    e = _dt.datetime.fromisoformat(captured["end"]["dateTime"])
    assert s.tzinfo is not None
    assert (e - s) == _dt.timedelta(minutes=30)                         # duration preserved
