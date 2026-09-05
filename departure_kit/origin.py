"""Deciding where you actually leave from.

The naive rule is a clock threshold: early flight means hotel, afternoon
flight means last appointment. That rule is wrong in both directions. A 9 am
flight with a 6 am breakfast meeting starts at the meeting. A 4 pm flight
whose last call ended at 9 am starts at the hotel, because you went back.

The rule that holds is positional. Work out when you have to leave, then look
at what you were doing immediately before that moment. If something ended just
before, you leave from there. If the last thing ended hours earlier, you went
back to the hotel like a normal person.

The middle of that range is genuinely ambiguous and depends on something no
calendar records: whether you checked out in the morning with the bag in the
car. So the ambiguous case is never resolved silently. It picks the safer
option, says it picked, and names the other one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

# If the last appointment ends within this many minutes of your leave time,
# you drove straight there. Wider than it sounds because a lunch that ends at
# 1:00 and a 2:15 departure is still obviously a direct run.
DIRECT_WINDOW_MINUTES = 90

# Do not go looking days back for an origin.
MAX_LOOKBACK_HOURS = 24


@dataclass
class OriginDecision:
    address: str
    source: str            # "appointment" | "hotel"
    confident: bool
    reason: str
    alternative: str = ""
    event_summary: str = ""
    event_end: datetime | None = None

    def describe(self) -> str:
        head = f"Leaving from: {self.address} ({self.source})"
        if self.confident:
            return f"{head}\n  {self.reason}"
        return (
            f"{head}\n  {self.reason}\n"
            f"  Ambiguous. Override with --origin-from "
            f"{'hotel' if self.source == 'appointment' else 'appointment'}."
        )


def _usable(event: dict, skip_patterns) -> bool:
    start = event.get("start") or {}
    if not start.get("dateTime"):
        return False  # all day, you were not somewhere specific
    if not (event.get("location") or "").strip():
        return False  # cannot drive from an address that is not there
    haystack = f"{event.get('summary') or ''} {event.get('description') or ''}".lower()
    return not any(p in haystack for p in (skip_patterns or []))


def infer_origin(
    events,
    departure: datetime,
    plan_minutes: int,
    hotel_address: str,
    skip_patterns=None,
    direct_window_minutes: int = DIRECT_WINDOW_MINUTES,
    force: str | None = None,
) -> OriginDecision:
    """Pick the origin for a departure plan.

    force may be "hotel" or "appointment" to override the inference.
    """
    leave_by = departure - timedelta(minutes=plan_minutes)
    earliest = leave_by - timedelta(hours=MAX_LOOKBACK_HOURS)

    candidates = []
    for ev in events:
        if not _usable(ev, skip_patterns):
            continue
        end_iso = (ev.get("end") or {}).get("dateTime")
        if not end_iso:
            continue
        end = datetime.fromisoformat(end_iso)
        if end.tzinfo is None:
            continue
        end = end.astimezone(departure.tzinfo)
        if earliest <= end <= leave_by:
            candidates.append((end, ev))

    if force == "hotel":
        return OriginDecision(
            hotel_address, "hotel", True, "Forced with --origin-from hotel."
        )

    if not candidates:
        if force == "appointment":
            return OriginDecision(
                hotel_address, "hotel", True,
                "Asked for the last appointment, but nothing on the calendar ends "
                "before you have to leave. Falling back to the hotel.",
            )
        return OriginDecision(
            hotel_address, "hotel", True,
            "Nothing on the calendar ends before you have to leave.",
        )

    end, ev = max(candidates, key=lambda pair: pair[0])
    gap = int((leave_by - end).total_seconds() // 60)
    location = ev["location"].strip()
    summary = ev.get("summary") or "(untitled)"

    if force == "appointment":
        return OriginDecision(
            location, "appointment", True,
            f"Forced with --origin-from appointment: {summary}.",
            event_summary=summary,
            event_end=end,
        )

    if gap <= direct_window_minutes:
        return OriginDecision(
            location, "appointment", True,
            f"{summary} ends {gap} minutes before you have to leave, so you go "
            "straight from there.",
            alternative=hotel_address,
            event_summary=summary,
            event_end=end,
        )

    hours = gap / 60
    return OriginDecision(
        hotel_address, "hotel", False,
        f"Last appointment ({summary}) ended {hours:.1f} hours before you have to "
        "leave, which is usually long enough that you went back for your bag.",
        alternative=location,
        event_summary=summary,
        event_end=end,
    )


def conflicts(leave_at: datetime, decision: OriginDecision) -> int:
    """Minutes by which leaving from the appointment is impossible, or 0.

    Extracted so the case that matters most can be tested. An earlier version
    of the caller iterated until the origin converged, and this situation made
    it oscillate: from the hotel the appointment looks reachable, from the
    appointment it does not. That is not a convergence failure, it is a
    schedule that does not work, and the traveller needs to hear it.
    """
    if decision.source != "appointment" or decision.event_end is None:
        return 0
    if leave_at >= decision.event_end:
        return 0
    return int((decision.event_end - leave_at).total_seconds() // 60)
