"""Finding and fixing calendar events stamped with the wrong time zone.

The problem this solves. Google Calendar stores an absolute instant plus a
zone label. When you create an event on a device sitting in one zone for a
place in another, the wall clock time you typed is interpreted in your zone.
The event is then permanently wrong, and it does not correct itself when you
travel: your phone shows a different number, but the underlying instant never
moves. A noon appointment typed in Charlotte for a Phoenix office is 9 am
Phoenix, forever.

Why this is hard to automate safely. An event stamped Eastern with a Phoenix
address has two possible histories. Either someone typed the local time and
the zone was stamped from their device, or a booking system wrote a correct
absolute instant. The stored data is identical in both cases and the correct
action is opposite. Guessing wrong moves a real appointment by hours.

The way out is provenance, not cleverness. If you know that a specific person
always types the appointment's local time, then for events created by that
person there is no ambiguity and the fix is safe to apply automatically.
Everything else is reported and left alone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

# US states that sit entirely within one zone.
STATE_ZONES = {
    "AL": "America/Chicago", "AR": "America/Chicago", "AZ": "America/Phoenix",
    "CA": "America/Los_Angeles", "CO": "America/Denver", "CT": "America/New_York",
    "DC": "America/New_York", "DE": "America/New_York", "GA": "America/New_York",
    "IA": "America/Chicago", "IL": "America/Chicago", "LA": "America/Chicago",
    "MA": "America/New_York", "MD": "America/New_York", "ME": "America/New_York",
    "MN": "America/Chicago", "MO": "America/Chicago", "MS": "America/Chicago",
    "MT": "America/Denver", "NC": "America/New_York", "NH": "America/New_York",
    "NJ": "America/New_York", "NM": "America/Denver", "NV": "America/Los_Angeles",
    "NY": "America/New_York", "OH": "America/New_York", "OK": "America/Chicago",
    "PA": "America/New_York", "RI": "America/New_York", "SC": "America/New_York",
    "UT": "America/Denver", "VA": "America/New_York", "VT": "America/New_York",
    "WA": "America/Los_Angeles", "WI": "America/Chicago", "WV": "America/New_York",
    "WY": "America/Denver",
}

# States crossed by a zone boundary. The state abbreviation alone cannot
# resolve these, so they are reported rather than guessed. Add the cities you
# actually visit to city_overrides in your profile.
SPLIT_STATES = {
    "AK", "FL", "ID", "IN", "KS", "KY", "MI", "ND", "NE", "OR", "SD", "TN", "TX",
}

_STATE_RE = re.compile(r",\s*([A-Z]{2})\b")


class Ambiguous(Exception):
    """The location cannot be resolved to one zone without more information."""


def zone_from_location(location: str, overrides: dict[str, str] | None = None) -> str:
    """Resolve a free text location to an IANA zone.

    Deliberately conservative. This runs unattended against real appointments,
    so refusing is always better than guessing.
    """
    if not location or not location.strip():
        raise Ambiguous("no location on the event")

    text = location.strip()
    lowered = text.lower()

    for key, zone in (overrides or {}).items():
        if key in lowered:
            return zone

    matches = _STATE_RE.findall(text.upper())
    if not matches:
        raise Ambiguous(f"no US state found in {text!r}")

    state = matches[-1]
    if state in SPLIT_STATES:
        raise Ambiguous(
            f"{state} spans more than one time zone; add a city override to your profile"
        )
    if state not in STATE_ZONES:
        raise Ambiguous(f"unknown state {state!r}")
    return STATE_ZONES[state]


def same_offset(zone_a: str, zone_b: str, when: datetime) -> bool:
    """True if two zones show the same clock at this instant.

    America/Phoenix and America/Denver are the same in winter and an hour
    apart in summer, so this has to be evaluated at the event's own date
    rather than in the abstract.
    """
    ref = when.replace(tzinfo=None)
    return ZoneInfo(zone_a).utcoffset(ref) == ZoneInfo(zone_b).utcoffset(ref)


@dataclass
class Finding:
    event_id: str
    summary: str
    location: str
    creator: str
    stored_zone: str
    location_zone: str
    start_wall: datetime
    action: str  # "fix" | "report" | "skip"
    reason: str

    @property
    def corrected_start(self) -> datetime:
        """The same wall clock reading, reinterpreted in the location's zone."""
        return self.start_wall.replace(tzinfo=ZoneInfo(self.location_zone))

    def describe(self) -> str:
        was = self.start_wall.strftime("%Y-%m-%d %H:%M")
        shown = self.corrected_start.astimezone(ZoneInfo(self.stored_zone))
        return (
            f"{self.summary} ({was} {self.stored_zone}) "
            f"-> {self.corrected_start.strftime('%H:%M')} {self.location_zone} "
            f"[{shown.strftime('%H:%M')} in {self.stored_zone}]"
        )


def examine(event: dict, home_zone: str, trusted_creators, skip_patterns, overrides):
    """Classify a single calendar event. Returns a Finding or None.

    event is the Google Calendar API shape, trimmed to what matters:
      {"id", "summary", "location", "creator": {"email"},
       "start": {"dateTime": iso, "timeZone": iana}}
    """
    start = (event.get("start") or {})
    iso = start.get("dateTime")
    if not iso:
        return None  # all day event, no zone to be wrong about

    stored_zone = start.get("timeZone") or home_zone
    location = event.get("location") or ""
    summary = event.get("summary") or "(no title)"
    creator = ((event.get("creator") or {}).get("email") or "").lower()

    haystack = f"{summary} {event.get('description') or ''}".lower()
    for pattern in skip_patterns:
        if pattern in haystack:
            return None

    try:
        location_zone = zone_from_location(location, overrides)
    except Ambiguous as exc:
        if location.strip():
            return Finding(
                event_id=event.get("id", ""),
                summary=summary,
                location=location,
                creator=creator,
                stored_zone=stored_zone,
                location_zone="",
                start_wall=datetime.fromisoformat(iso).replace(tzinfo=None),
                action="report",
                reason=f"cannot resolve location: {exc}",
            )
        return None

    when = datetime.fromisoformat(iso)
    wall = when.astimezone(ZoneInfo(stored_zone)).replace(tzinfo=None)

    if same_offset(stored_zone, location_zone, when):
        return None  # no visible discrepancy on this date

    action = "fix" if creator and creator in trusted_creators else "report"
    reason = (
        "creator is a trusted local time source"
        if action == "fix"
        else "creator not in trusted_local_time_creators, so the intent is ambiguous"
    )

    return Finding(
        event_id=event.get("id", ""),
        summary=summary,
        location=location,
        creator=creator,
        stored_zone=stored_zone,
        location_zone=location_zone,
        start_wall=wall,
        action=action,
        reason=reason,
    )


def scan(events, home_zone, trusted_creators, skip_patterns, overrides):
    findings = []
    for event in events:
        found = examine(event, home_zone, trusted_creators, skip_patterns, overrides)
        if found:
            findings.append(found)
    return findings
