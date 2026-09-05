#!/usr/bin/env python3
"""Check the calendar for an upcoming departure and write the plan for it.

This is what a scheduler runs. It is safe to run repeatedly: it will not write
a second plan for a flight it has already handled.

  python3 watch_calendar.py                  # look 24 hours ahead, report only
  python3 watch_calendar.py --apply          # actually write the plan
  python3 watch_calendar.py --lead-hours 36 --apply

Scheduling belongs to your operating system, not to this program. See
SCHEDULING.md for Task Scheduler, launchd and cron.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timedelta, timezone

from departure_kit.profile import ConfigError, load_airports, load_profile
from departure_kit.watch import (
    already_planned, find_flights, find_lodging, next_actionable, plan_marker,
    unconfigured_departure,
)


def main(argv=None):
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--lead-hours", type=int, default=24,
                   help="How far ahead to look. Default 24.")
    p.add_argument("--apply", action="store_true",
                   help="Write the plan. Without this it only reports.")
    p.add_argument("--calendar", default="primary")
    p.add_argument("--home-airport", default=None,
                   help="Skip flights leaving from here. Defaults to the profile.")
    args = p.parse_args(argv)

    try:
        profile = load_profile()
        airports = load_airports()
    except ConfigError as exc:
        print(f"Config problem: {exc}", file=sys.stderr)
        return 2

    watch_cfg = getattr(profile, "watch", None) or {}
    home_airport = args.home_airport or watch_cfg.get("home_airport")
    flight_patterns = watch_cfg.get("flight_event_matches") or []
    lodging_patterns = watch_cfg.get("lodging_event_matches") or []

    from departure_kit.gcal import list_events, service

    svc = service()
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(hours=args.lead_hours)
    # A little history so an existing plan written yesterday is visible.
    events = list_events(svc, now - timedelta(hours=48), horizon, args.calendar)

    flights = find_flights(events, airports, home_airport, flight_patterns)
    actionable = [f for f in flights if next_actionable(f, now, args.lead_hours)]

    # Say something useful about flights we found but cannot plan for, rather
    # than staying silent about an event the user can see themselves.
    for event in events:
        missing = unconfigured_departure(event, set(airports))
        if missing and (event.get("start") or {}).get("dateTime"):
            print(f"Flight from {missing} found, but there is no profile for that "
                  f"airport. Add {missing} to config/airports.yaml to plan it.")
            break

    if not actionable:
        print(f"No departure in the next {args.lead_hours} hours.")
        return 0

    flight = actionable[0]
    print(flight.describe())

    if already_planned(events, flight):
        print("  Already planned. Nothing to do.")
        return 0

    lodging = find_lodging(events, flight.departure, lodging_patterns)
    if not lodging:
        print("  No hotel found on the calendar before that flight, so there is "
              "nothing to route from.")
        print("  Add the hotel to your calendar with its address in the location "
              "field, or run plan_departure.py directly with --from.")
        return 1

    print(f"  Leaving from: {lodging}")

    if not args.apply:
        print("\nDry run. Re run with --apply to write the plan.")
        return 0

    cmd = [
        sys.executable, "plan_departure.py",
        "--airport", flight.airport,
        "--depart", flight.departure.strftime("%Y-%m-%dT%H:%M"),
        "--from", lodging,
        "--drive", "auto",
        "--find-fuel",
        "--calendar-origin",
        "--add-to-calendar",
        "--tag", plan_marker(flight),
    ]
    print("\n" + " ".join(cmd) + "\n")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print("Planning failed. The flight is still unplanned, so the next run "
              "will try again.", file=sys.stderr)
        return result.returncode

    print(f"\nPlan written. Marker for future runs: {plan_marker(flight)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
