"""Finding the next departure on a calendar, and what it needs to plan for.

This is the piece that turns the kit from something you run into something
that runs. Everything here is a pure function over plain event dictionaries,
so the detection rules can be tested without a Google account. The scheduling
itself is deliberately not here: cron, launchd and Task Scheduler already
exist on the machines people have, and a daemon of our own would be a worse
version of all three.

Three things it has to work out, and each has a way of going wrong quietly.

Which events are flights. Calendars are full of three letter strings that are
not airport codes, and "SAN planning meeting" must not be read as a departure
from San Diego. So a code alone is never enough; something has to also look
like a flight.

Which airport you leave from, and in what zone. The event's own timeZone field
cannot be trusted: travel agency forwards regularly carry junk, and one on
this author's calendar was labelled Africa/Abidjan while holding a correct
instant. The absolute instant is reliable, the label is not, so the zone comes
from the airport rather than from the event.

Whether a plan already exists. A daily job that forgets what it did yesterday
produces a duplicate reminder every morning until the flight.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

# Two letters then one to four digits: AA 871, DL1234, WN22. The space is
# optional because calendars are inconsistent about it.
FLIGHT_NUMBER_RE = re.compile(r"\b[A-Z]{2}\s?\d{1,4}\b")

# A three letter code in parentheses, which is how nearly every itinerary
# writes it: "San Diego (SAN) - Charlotte (CLT)".
PARENTHESISED_CODE_RE = re.compile(r"\(([A-Z]{3})\)")

BARE_CODE_RE = re.compile(r"\b([A-Z]{3})\b")

# Words that mean an event is where you are sleeping, not where you are going.
LODGING_WORDS = (
    "stay at", "hotel", "inn", "suites", "resort", "lodge", "motel",
    "marriott", "hilton", "hyatt", "sheraton", "westin", "doubletree",
    "residence", "embassy", "holiday", "courtyard", "airbnb", "hampton",
)

# Written into the description of every plan this creates, so a later run can
# recognise its own work.
MARKER = "tdk-plan-for:"


@dataclass
class Flight:
    departure: datetime          # timezone aware, in the airport's zone
    airport: str                 # IATA code of where you leave from
    event_id: str
    summary: str

    def describe(self) -> str:
        return (
            f"{self.summary} - departs {self.departure.strftime('%a %d %b %H:%M')} "
            f"{self.departure.tzname()} from {self.airport}"
        )


def _text_of(event: dict) -> str:
    return f"{event.get('summary') or ''} {event.get('location') or ''}"


def looks_like_a_flight(event: dict, extra_patterns=None) -> bool:
    """Is this event an actual flight?

    Requires something flight shaped beyond a three letter code, because
    "SAN planning meeting" and "CLT quarterly review" are ordinary calendar
    entries and must not be read as departures.
    """
    text = _text_of(event)
    if FLIGHT_NUMBER_RE.search(text):
        return True
    if PARENTHESISED_CODE_RE.search(text):
        return True
    lowered = text.lower()
    return any(p.lower() in lowered for p in (extra_patterns or []))


def _first_code(event: dict) -> str | None:
    """The first airport code in the text, configured or not.

    Itineraries read origin first, so the first code is where you leave from.
    Parenthesised codes are preferred because they are unambiguous.
    """
    text = _text_of(event)
    codes = PARENTHESISED_CODE_RE.findall(text) or BARE_CODE_RE.findall(text)
    return codes[0] if codes else None


def departure_airport(event: dict, known_codes) -> str | None:
    """Which airport you leave from, or None if it is not one we can plan for.

    Deliberately does not search past the first code. An earlier version
    returned the first *configured* code, which on a Boston to Charlotte
    flight with no BOS profile returned CLT, the destination. That produces a
    plan for the wrong airport that looks entirely reasonable, which is worse
    than producing nothing.
    """
    code = _first_code(event)
    if code is None:
        return None
    return code if code in {c.upper() for c in known_codes} else None


def unconfigured_departure(event: dict, known_codes) -> str | None:
    """The departure code when it exists but has no airport profile.

    Lets a caller say "add BOS to airports.yaml" instead of silently ignoring
    a flight the user can see on their own calendar.
    """
    code = _first_code(event)
    if code and code not in {c.upper() for c in known_codes}:
        return code
    return None


def find_flights(events, known_codes, home_airport=None, extra_patterns=None):
    """All flights in the given events, earliest first.

    A flight leaving from home_airport is skipped. This kit plans the leg
    where you hand a rental car back, and on the way out you are parking your
    own car at your own airport, which is a different problem with different
    numbers.
    """
    from zoneinfo import ZoneInfo

    found = []
    for event in events:
        iso = (event.get("start") or {}).get("dateTime")
        if not iso or not looks_like_a_flight(event, extra_patterns):
            continue
        code = departure_airport(event, known_codes)
        if not code:
            continue
        if home_airport and code == home_airport.upper():
            continue
        zone_name = (known_codes.get(code).timezone
                     if hasattr(known_codes, "get") and known_codes.get(code)
                     else None)
        when = datetime.fromisoformat(iso)
        if zone_name:
            # The instant is trustworthy; the event's own zone label is not.
            when = when.astimezone(ZoneInfo(zone_name))
        found.append(
            Flight(when, code, event.get("id", ""), event.get("summary") or "flight")
        )
    return sorted(found, key=lambda f: f.departure)


def find_lodging(events, before: datetime, extra_patterns=None) -> str | None:
    """Where you are staying, as an address.

    Takes the latest lodging event that starts before the departure, since a
    trip with two hotels ends at the second one. Returns None rather than
    guessing, because a wrong origin produces a plan that looks right.
    """
    best = None
    for event in events:
        location = (event.get("location") or "").strip()
        if not location:
            continue
        text = _text_of(event).lower()
        words = list(LODGING_WORDS) + [p.lower() for p in (extra_patterns or [])]
        if not any(w in text for w in words):
            continue
        start = (event.get("start") or {})
        iso = start.get("dateTime") or start.get("date")
        if not iso:
            continue
        try:
            when = datetime.fromisoformat(iso)
        except ValueError:
            continue
        if when.tzinfo is not None:
            when = when.astimezone(before.tzinfo)
        else:
            when = when.replace(tzinfo=before.tzinfo)
        if when <= before and (best is None or when > best[0]):
            best = (when, location)
    return best[1] if best else None


def plan_marker(flight: Flight) -> str:
    return f"{MARKER} {flight.event_id}"


def already_planned(events, flight: Flight) -> bool:
    """Has a previous run already written a plan for this flight?

    Keyed on the flight's event id rather than on a date, so moving the
    reminder or rescheduling the day does not produce a second copy.
    """
    needle = plan_marker(flight)
    return any(needle in (e.get("description") or "") for e in events)


def next_actionable(flight: Flight, now: datetime, lead_hours: int) -> bool:
    """Is it time to write this plan yet?

    Writing weeks ahead is worse than useless: the calendar it was computed
    from will have changed by the morning it matters.
    """
    return now <= flight.departure <= now + timedelta(hours=lead_hours)
