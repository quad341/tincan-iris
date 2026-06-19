"""Google Calendar skill — free/busy check, create event, move event.

Design: act-without-disclose (PM decision). Spoken replies never include event
titles, attendees, or exact timestamps; those appear only in console annotations.

OAuth: offline flow persisting to ``~/.config/iris/gcal_token.json``.
If the token is absent, a startup notice is printed once (not spoken) and
calendar skills raise ``PermissionError`` until ``iris auth gcal`` is run.

Three skills are exposed:
  CalendarFreeBusySkill   — check availability for a time range
  CalendarCreateSkill     — create a new event
  CalendarMoveSkill       — move an existing event by title fragment

Each ``run()`` returns ``(reply: str, annotation: str)``.
``reply`` is safe for TTS; ``annotation`` is console-only and may include
event details, OAuth guidance, and act-without-disclose markers.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .skills import SkillParam

_TOKEN_PATH = Path.home() / ".config/iris/gcal_token.json"
_TOKEN_URI = "https://oauth2.googleapis.com/token"
_GCAL_BASE = "https://www.googleapis.com/calendar/v3"
_CALENDAR_ID = "primary"


def save_token(token: dict, path: Path | None = None) -> Path:
    """Persist an OAuth token dict for the calendar client (chmod 600).

    Used by ``iris-auth gcal`` after the consent flow. The dict should carry
    ``access_token`` and, for unattended refresh, ``refresh_token`` +
    ``client_id`` + ``client_secret`` (+ ``expires_at`` epoch seconds).
    """
    p = path or _TOKEN_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(token))
    p.chmod(0o600)
    return p


def _gcal_http_hint(exc: urllib.error.HTTPError) -> str:
    """Turn a Google Calendar HTTP error into a human hint + fix.

    For "API not enabled" (``SERVICE_DISABLED`` / ``accessNotConfigured``) Google
    returns a project-pinned activation URL in ``error.details[].metadata`` —
    surface it verbatim so the API gets enabled on the *right* project. Falls
    back to the API's own message, else the status code.
    """
    try:
        data = json.loads(exc.read().decode())
    except Exception:  # noqa: BLE001 — non-JSON / unreadable body
        return f"Google Calendar API error (HTTP {getattr(exc, 'code', '?')})."
    err = data.get("error", {}) if isinstance(data, dict) else {}
    for detail in err.get("details", []):
        url = (detail.get("metadata") or {}).get("activationUrl")
        if url:
            return (
                "the Google Calendar API isn't enabled on this project yet — "
                "enable it (double-check the project selector matches!):\n"
                f"      {url}\n"
                "      then wait ~1–2 min and retry; no need to re-run gcal."
            )
    msg = err.get("message")
    return msg or f"Google Calendar API error (HTTP {getattr(exc, 'code', '?')})."


# ---------------------------------------------------------------------------
# CalendarClient — real REST client (mocked in tests via MagicMock(spec=...))

class CalendarClient:
    """Thin wrapper over the Google Calendar v3 REST API.

    Token management: loads ``~/.config/iris/gcal_token.json`` on init.
    Call ``CalendarClient.auth_flow(client_id, client_secret)`` once to run
    the OAuth consent flow (``iris auth gcal`` CLI command).
    """

    def __init__(self, token_path: Path | None = None) -> None:
        self._token_path = token_path or _TOKEN_PATH
        self._token: dict | None = self._load_token()

    # --- token management ---

    def _load_token(self) -> dict | None:
        if not self._token_path.exists():
            return None
        try:
            return json.loads(self._token_path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    def _save_token(self, token: dict) -> None:
        self._token_path.parent.mkdir(parents=True, exist_ok=True)
        self._token_path.write_text(json.dumps(token))
        self._token = token

    def has_token(self) -> bool:
        return self._token is not None

    def verify_reachable(self) -> tuple[bool, str]:
        """Best-effort setup check: is the Calendar API enabled and the token usable?

        Makes one tiny ``freeBusy`` call. Returns ``(ok, hint)``; on failure
        ``hint`` is a console-safe explanation + fix. For the common
        "API not enabled" case it carries Google's own project-pinned activation
        URL, so the operator enables it on the *right* project. Never raises — a
        setup probe must not crash setup.
        """
        if not self._token:
            return False, "no calendar token saved — run: iris auth gcal"
        now = datetime.now(timezone.utc)
        body = {
            "timeMin": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "timeMax": (now + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "items": [{"id": _CALENDAR_ID}],
        }
        try:
            req = urllib.request.Request(
                _GCAL_BASE + "/freeBusy", json.dumps(body).encode(),
                headers=self._headers(), method="POST",
            )
            with urllib.request.urlopen(req, timeout=10):
                return True, ""
        except urllib.error.HTTPError as exc:
            return False, _gcal_http_hint(exc)
        except Exception as exc:  # noqa: BLE001 — best-effort probe, never crash setup
            return False, f"couldn't reach Google Calendar ({exc})"

    def _headers(self) -> dict[str, str]:
        if not self._token:
            raise PermissionError("Google Calendar not authorised — run: iris auth gcal")
        self._maybe_refresh()
        return {
            "Authorization": f"Bearer {self._token['access_token']}",
            "Content-Type": "application/json",
        }

    def _maybe_refresh(self) -> None:
        """Refresh the access token when it's near expiry, if we can.

        No-op for a static token (no refresh_token / client creds) — it's used
        as-is. A 60s skew avoids racing the expiry boundary.
        """
        tok = self._token
        if not tok or not tok.get("refresh_token") or not tok.get("client_id"):
            return
        if time.time() < float(tok.get("expires_at", 0)) - 60:
            return
        data = urllib.parse.urlencode({
            "grant_type": "refresh_token",
            "refresh_token": tok["refresh_token"],
            "client_id": tok["client_id"],
            "client_secret": tok.get("client_secret", ""),
        }).encode()
        req = urllib.request.Request(tok.get("token_uri", _TOKEN_URI), data, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            new = json.loads(resp.read())
        tok["access_token"] = new["access_token"]
        tok["expires_at"] = time.time() + new.get("expires_in", 3600)
        self._save_token(tok)

    def _get(self, path: str, params: dict | None = None) -> dict:
        url = _GCAL_BASE + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise PermissionError(f"OAuth error {exc.code}") from exc
            raise

    def _post(self, path: str, body: dict) -> dict:
        url = _GCAL_BASE + path
        data = json.dumps(body).encode()
        req = urllib.request.Request(url, data, headers=self._headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise PermissionError(f"OAuth error {exc.code}") from exc
            raise

    def _patch(self, path: str, body: dict) -> dict:
        url = _GCAL_BASE + path
        data = json.dumps(body).encode()
        req = urllib.request.Request(url, data, headers=self._headers(), method="PATCH")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise PermissionError(f"OAuth error {exc.code}") from exc
            raise

    # --- public API ---

    def free_busy(self, *, start: str, end: str) -> dict:
        """Return ``{"busy": [...]}`` for the primary calendar in the given range."""
        body = {
            "timeMin": start if start.endswith("Z") else start + "Z",
            "timeMax": end if end.endswith("Z") else end + "Z",
            "items": [{"id": _CALENDAR_ID}],
        }
        resp = self._post("/freeBusy", body)
        calendars = resp.get("calendars", {})
        primary = calendars.get(_CALENDAR_ID, {})
        return {"busy": primary.get("busy", [])}

    def list_events(self, *, title_fragment: str = "", **_kwargs: object) -> list[dict]:
        """Return events whose summary contains ``title_fragment`` (case-insensitive)."""
        params = {
            "calendarId": _CALENDAR_ID,
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": "50",
        }
        if title_fragment:
            params["q"] = title_fragment
        resp = self._get(f"/calendars/{_CALENDAR_ID}/events", params)
        events = []
        for item in resp.get("items", []):
            events.append({
                "id": item.get("id", ""),
                "title": item.get("summary", ""),
                "start": item.get("start", {}).get("dateTime", ""),
                "end": item.get("end", {}).get("dateTime", ""),
                "attendees": [a.get("email", "") for a in item.get("attendees", [])],
            })
        return events

    def create_event(
        self,
        *,
        title: str,
        start: str,
        attendees: list[str] | None = None,
        duration_hours: int = 1,
        **_kwargs: object,
    ) -> dict:
        """Create an event and return the created event dict.

        If any attendee email is malformed, returns the event dict with an
        ``"attendee_error"`` key containing the bad address.
        """
        start_dt = datetime.fromisoformat(start)
        end_dt = start_dt + timedelta(hours=duration_hours)
        body: dict = {
            "summary": title,
            "start": {"dateTime": start_dt.isoformat()},
            "end": {"dateTime": end_dt.isoformat()},
        }
        valid_attendees = []
        bad_attendee = None
        for addr in (attendees or []):
            if "@" in addr and addr.count("@") == 1:
                valid_attendees.append({"email": addr})
            else:
                bad_attendee = addr
        if valid_attendees:
            body["attendees"] = valid_attendees
        resp = self._post(f"/calendars/{_CALENDAR_ID}/events", body)
        result = {
            "id": resp.get("id", ""),
            "title": resp.get("summary", title),
            "start": start,
            "end": end_dt.isoformat(),
        }
        if bad_attendee:
            result["attendee_error"] = bad_attendee
        return result

    def move_event(self, *, event_id: str, new_start: str, **_kwargs: object) -> dict:
        """Reschedule an event to ``new_start`` (preserves duration)."""
        # Fetch existing event to get duration
        existing = self._get(f"/calendars/{_CALENDAR_ID}/events/{event_id}")
        old_start = datetime.fromisoformat(existing["start"]["dateTime"])
        old_end = datetime.fromisoformat(existing["end"]["dateTime"])
        duration = old_end - old_start
        new_start_dt = datetime.fromisoformat(new_start)
        new_end_dt = new_start_dt + duration
        body = {
            "start": {"dateTime": new_start_dt.isoformat()},
            "end": {"dateTime": new_end_dt.isoformat()},
        }
        resp = self._patch(f"/calendars/{_CALENDAR_ID}/events/{event_id}", body)
        return {
            "id": resp.get("id", event_id),
            "title": resp.get("summary", ""),
            "start": new_start_dt.isoformat(),
            "end": new_end_dt.isoformat(),
        }


# ---------------------------------------------------------------------------
# Skills

def _iso_to_natural(iso: str) -> str:
    """Convert ISO datetime to natural-language spoken form: '2:00 PM'."""
    try:
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%-I:%M %p")   # e.g. "2:00 PM"
    except ValueError:
        return iso


_OAUTH_REPLY = "The calendar may need to be set up — I can't reach it right now."
_OAUTH_ANN = "[calendar: OAuth error — run iris auth gcal]"


class CalendarFreeBusySkill:
    """Check whether the operator's primary calendar is free for a time slot."""

    name = "calendar_free_busy"
    description = (
        "Check if the operator's calendar is free for a given time range. "
        "Never reveals event details in the spoken reply (act-without-disclose)."
    )
    params: list[SkillParam] = [
        SkillParam(name="start", type="string",
                   description="ISO 8601 start datetime, e.g. 2026-06-19T14:00:00"),
        SkillParam(name="end", type="string",
                   description="ISO 8601 end datetime, e.g. 2026-06-19T15:00:00"),
    ]

    def __init__(self, client: CalendarClient) -> None:
        self._client = client

    def run(self, *, start: str, end: str, **_kwargs: object) -> tuple[str, str]:
        try:
            result = self._client.free_busy(start=start, end=end)
        except PermissionError:
            return _OAUTH_REPLY, _OAUTH_ANN

        busy = result.get("busy", [])
        ann = f"[calendar: free/busy — {start}–{end}]"
        if not busy:
            return "That time looks free.", ann
        return (
            "That time looks a bit tight on the calendar — "
            "there might be something already on there.",
            "[calendar: act-without-disclose — busy slot found, details hidden]",
        )


class CalendarCreateSkill:
    """Create a new calendar event for the operator."""

    name = "calendar_create"
    description = (
        "Create a new event on the operator's calendar. "
        "Returns a brief spoken confirmation with natural-language time."
    )
    params: list[SkillParam] = [
        SkillParam(name="title", type="string",
                   description="Event title."),
        SkillParam(name="start", type="string",
                   description="ISO 8601 start datetime."),
        SkillParam(name="attendees", type="string", required=False, default="",
                   description="Comma-separated attendee email addresses."),
    ]

    def __init__(self, client: CalendarClient) -> None:
        self._client = client

    def run(
        self,
        *,
        title: str,
        start: str,
        attendees: list[str] | None = None,
        **_kwargs: object,
    ) -> tuple[str, str]:
        try:
            result = self._client.create_event(title=title, start=start, attendees=attendees)
        except PermissionError:
            return _OAUTH_REPLY, _OAUTH_ANN

        time_str = _iso_to_natural(start)
        attendee_error: str | None = None
        if isinstance(result, dict):
            attendee_error = result.get("attendee_error")

        ann = f"[calendar: created — {title} at {start}]"

        if attendees and not attendee_error:
            reply = (
                f"Done — put it on the calendar for {time_str}, "
                f"1-hour slot. I've invited them."
            )
        elif attendees and attendee_error:
            reply = (
                f"Done — on the calendar for {time_str}, 1-hour slot, "
                f"but I couldn't add the attendee."
            )
        else:
            reply = f"Done — put it on the calendar for {time_str}, 1-hour slot."

        return reply, ann


class CalendarMoveSkill:
    """Move an existing calendar event to a new start time."""

    name = "calendar_move"
    description = (
        "Reschedule an existing event by title fragment. "
        "If multiple events match, asks for disambiguation."
    )
    params: list[SkillParam] = [
        SkillParam(name="title_fragment", type="string",
                   description="Part of the event title to search for."),
        SkillParam(name="new_start", type="string",
                   description="ISO 8601 new start datetime."),
    ]

    def __init__(self, client: CalendarClient) -> None:
        self._client = client

    def run(
        self,
        *,
        title_fragment: str,
        new_start: str,
        **_kwargs: object,
    ) -> tuple[str, str]:
        try:
            events = self._client.list_events(title_fragment=title_fragment) or []
        except PermissionError:
            return _OAUTH_REPLY, _OAUTH_ANN

        if not events:
            return "I couldn't find an event matching that.", ""

        if len(events) > 1:
            items = "; ".join(
                f"{i + 1}. {e['title']}" for i, e in enumerate(events[:5])
            )
            ann = f"[calendar: disambiguation — {items}]"
            return f"I found {len(events)} matches — which one did you mean?", ann

        event = events[0]
        try:
            self._client.move_event(event_id=event["id"], new_start=new_start)
        except PermissionError:
            return _OAUTH_REPLY, _OAUTH_ANN

        ann = f"[calendar: moved — {event['title']} to {new_start}]"
        return "Done — moved it.", ann


# ---------------------------------------------------------------------------
# Factory

def calendar_skills(client: CalendarClient | None = None) -> list:
    """Return the three calendar skills sharing one ``CalendarClient``."""
    c = client or CalendarClient()
    return [
        CalendarFreeBusySkill(c),
        CalendarCreateSkill(c),
        CalendarMoveSkill(c),
    ]


def configured_calendar_skills(client: CalendarClient | None = None) -> list:
    """Return calendar skills when a Google token exists, else ``[]``.

    The brain registers these only once the OAuth token is present (see
    ``iris auth gcal``), so qwen offers calendar actions exactly when they can
    work — mirroring the email lane's config-gated registration.
    """
    c = client or CalendarClient()
    if not c.has_token():
        return []
    return calendar_skills(c)
