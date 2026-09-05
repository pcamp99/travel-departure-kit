"""A deliberately thin Google Calendar wrapper.

Thin on purpose. Every decision worth testing lives in tzfix.py and
timeline.py as pure functions over plain dictionaries, so the parts that can
be wrong can be tested without a network or a Google account. This module is
the boring shell around them.
"""

from __future__ import annotations

import os
from datetime import datetime

SCOPES = ["https://www.googleapis.com/auth/calendar"]

CREDENTIALS_FILE = os.environ.get("DEPARTURE_KIT_CREDENTIALS", "credentials.json")
TOKEN_FILE = os.environ.get("DEPARTURE_KIT_TOKEN", "token.json")


def _lazy_imports():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "Google libraries missing. Run:\n"
            "  pip install -r requirements.txt"
        ) from exc
    return Request, Credentials, InstalledAppFlow, build


def service():
    """Return an authorised Calendar service, running the consent flow once.

    The first run opens a browser. After that token.json is reused, and it is
    gitignored because it is a live credential for your calendar.
    """
    Request, Credentials, InstalledAppFlow, build = _lazy_imports()

    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDENTIALS_FILE):
                raise SystemExit(
                    f"No {CREDENTIALS_FILE}. Download the OAuth client secret from "
                    "Google Cloud Console and save it there. The runbook covers this."
                )
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w", encoding="utf-8") as fh:
            fh.write(creds.to_json())
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def list_events(svc, time_min: datetime, time_max: datetime, calendar_id="primary"):
    """Fetch timed events in a window, following pagination."""
    events, page_token = [], None
    while True:
        resp = (
            svc.events()
            .list(
                calendarId=calendar_id,
                timeMin=time_min.isoformat(),
                timeMax=time_max.isoformat(),
                singleEvents=True,
                orderBy="startTime",
                maxResults=250,
                pageToken=page_token,
            )
            .execute()
        )
        events.extend(resp.get("items", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            return events


def set_event_zone(svc, event_id, start_iso, end_iso, zone, calendar_id="primary"):
    """Rewrite an event's start and end in a different zone.

    sendUpdates is 'none' so correcting your own record does not fire an email
    at a customer's office about a meeting that, from their side, never moved.
    """
    body = {
        "start": {"dateTime": start_iso, "timeZone": zone},
        "end": {"dateTime": end_iso, "timeZone": zone},
    }
    return (
        svc.events()
        .patch(calendarId=calendar_id, eventId=event_id, body=body, sendUpdates="none")
        .execute()
    )


def create_event(
    svc, summary, start, end, zone, description="", location="",
    reminders_minutes=(30, 0), calendar_id="primary",
):
    body = {
        "summary": summary,
        "description": description,
        "location": location,
        "start": {"dateTime": start.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": zone},
        "end": {"dateTime": end.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": zone},
        "transparency": "transparent",
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "popup", "minutes": m} for m in reminders_minutes
            ],
        },
    }
    return svc.events().insert(calendarId=calendar_id, body=body).execute()
