#!/usr/bin/env python3
"""Build a departure plan for a flight: where you start, where to fuel, when to leave.

Fully manual, no network at all:

  python3 plan_departure.py --airport SAN --depart 2026-10-17T07:00 \
    --from "1515 Hotel Cir S, San Diego, CA 92108" --drive 11 \
    --fuel "3860 Old Town Ave, San Diego, CA 92110" --drive-to-fuel 4

Everything worked out for you (OpenStreetMap services, still no API key):

  python3 plan_departure.py --airport SAN --depart 2026-10-17T07:00 \
    --from "1515 Hotel Cir S, San Diego, CA 92108" \
    --drive auto --find-fuel --calendar-origin
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta

from departure_kit.links import Place, google_maps_route, waze_legs
from departure_kit.profile import ConfigError, get_airport, load_airports, load_profile
from departure_kit.timeline import build_plan



def latlon(text):
    if not text:
        return (None, None)
    try:
        lat, lon = text.split(",")
        return (float(lat), float(lon))
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"{text!r} should look like 32.758335,-117.176866"
        )


def parse_args(argv):
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--airport", required=True, help="IATA code you depart from")
    p.add_argument("--depart", required=True,
                   help="Scheduled departure, local to the airport, YYYY-MM-DDTHH:MM")
    p.add_argument("--from", dest="origin", required=True,
                   help="Where you are staying. May be replaced by --calendar-origin.")
    p.add_argument("--from-latlon", type=latlon, default=(None, None))
    p.add_argument("--origin-place-id", default=None)
    p.add_argument("--drive", required=True,
                   help="Minutes from your origin to the rental return, or 'auto' "
                        "to look it up from OpenStreetMap.")
    p.add_argument("--drive-to-fuel", type=int, default=None,
                   help="Minutes of that drive before the fuel stop. Computed with 'auto'.")
    p.add_argument("--fuel", help="Fuel stop address you already know.")
    p.add_argument("--fuel-latlon", type=latlon, default=(None, None))
    p.add_argument("--fuel-place-id", default=None)
    p.add_argument("--find-fuel", action="store_true",
                   help="Pick a fuel stop from OpenStreetMap. No key, no account.")
    p.add_argument("--calendar-origin", action="store_true",
                   help="Work out from your calendar whether you leave from the hotel "
                        "or your last appointment. Needs Google access.")
    p.add_argument("--origin-from", choices=("hotel", "appointment"), default=None,
                   help="Override what --calendar-origin decided.")
    p.add_argument("--dynamic-origin", action="store_true",
                   help="Leave the origin out of the Maps link so it starts from "
                        "wherever your phone is when you open it. Useful for a link "
                        "generated hours ahead. Does not change the leave time.")
    p.add_argument("--add-to-calendar", action="store_true",
                   help="Create the reminder event (needs Google credentials)")
    return p.parse_args(argv)


def resolve_point(address, given_latlon, need_coords):
    """Return coordinates for an address, geocoding only if we actually need them."""
    if given_latlon != (None, None) or not need_coords:
        return given_latlon
    from departure_kit.geo import GeocodeFailed, geocode

    try:
        return geocode(address)
    except (GeocodeFailed, OSError) as exc:
        raise SystemExit(f"Could not place {address!r} on the map: {exc}")


def main(argv=None):
    args = parse_args(argv)

    try:
        profile = load_profile()
        airport = get_airport(args.airport, load_airports())
    except ConfigError as exc:
        print(f"Config problem: {exc}", file=sys.stderr)
        return 2

    try:
        naive = datetime.fromisoformat(args.depart)
    except ValueError:
        print(f"Could not read --depart {args.depart!r}. Use 2026-10-17T07:00",
              file=sys.stderr)
        return 2
    if naive.tzinfo is not None:
        print("Give --depart as local airport time with no offset.", file=sys.stderr)
        return 2
    departure = naive.replace(tzinfo=airport.zone())

    auto_drive = str(args.drive).lower() == "auto"
    if not auto_drive:
        try:
            fixed_drive = int(args.drive)
        except ValueError:
            print("--drive takes a number of minutes or the word 'auto'.",
                  file=sys.stderr)
            return 2

    need_coords = args.find_fuel or auto_drive
    hotel_address = args.origin

    # There is a genuine circularity here. Drive time depends on where you
    # start; where you start depends on when you must leave; when you must
    # leave depends on drive time. Two deterministic passes settle it. An
    # earlier version looped until it converged and could oscillate, which
    # turned out to be hiding something more useful than a convergence
    # failure: the case where leaving from the appointment would mean
    # departing before it ends. That is a schedule conflict, not ambiguity,
    # and it deserves to be said out loud rather than smoothed over.
    origin_address = hotel_address
    origin_latlon = args.from_latlon
    origin_place_id = args.origin_place_id
    origin_label = "hotel"
    decision = None
    conflict = None

    def compute(address, latlon_hint):
        point = resolve_point(address, latlon_hint, need_coords)
        if auto_drive:
            from departure_kit.route import RoutingFailed, drive_minutes
            try:
                mins, _ = drive_minutes([point, airport.return_latlon])
            except RoutingFailed as exc:
                raise SystemExit(f"Routing unavailable: {exc}")
        else:
            mins = fixed_drive
        return point, mins

    origin_latlon, drive = compute(origin_address, origin_latlon)
    plan = build_plan(
        departure=departure, airport=airport, profile=profile, drive_minutes=drive,
        fuel_stop=bool(args.fuel or args.find_fuel),
        drive_to_fuel_minutes=args.drive_to_fuel, origin_label=origin_label,
    )

    if args.calendar_origin:
        from departure_kit.gcal import list_events, service
        from departure_kit.origin import infer_origin

        events = list_events(service(), departure - timedelta(hours=30), departure)
        decision = infer_origin(
            events, departure, plan.total_minutes, hotel_address,
            skip_patterns=profile.skip_patterns, force=args.origin_from,
        )

        if decision.source == "appointment":
            appt_latlon, appt_drive = compute(decision.address, (None, None))
            appt_plan = build_plan(
                departure=departure, airport=airport, profile=profile,
                drive_minutes=appt_drive,
                fuel_stop=bool(args.fuel or args.find_fuel),
                drive_to_fuel_minutes=args.drive_to_fuel,
                origin_label="the last appointment",
            )
            if decision.event_end and appt_plan.leave_at < decision.event_end:
                short = int((decision.event_end - appt_plan.leave_at).total_seconds() // 60)
                conflict = (
                    f"Leaving from {decision.event_summary} does not work. That drive "
                    f"is {appt_drive} minutes, so you would have to leave at "
                    f"{appt_plan.leave_at.strftime('%H:%M')}, which is {short} minutes "
                    f"before the appointment ends at "
                    f"{decision.event_end.strftime('%H:%M')}.\n"
                    "  Either leave that appointment early, or move the flight. The "
                    "plan below assumes you go from the hotel, which is not what will "
                    "actually happen if you stay to the end."
                )
            else:
                origin_address = decision.address
                origin_latlon = appt_latlon
                origin_place_id = None
                origin_label = "the last appointment"
                drive, plan = appt_drive, appt_plan

    if decision:
        if conflict:
            print("SCHEDULE CONFLICT")
            print(f"  {conflict}\n")
        else:
            print(decision.describe())
            print()
        plan.steps[0].label = (
            "Leave the last appointment" if origin_label != "hotel"
            else "Leave the hotel"
        )

    # Fuel comes after the origin is settled, because the search draws a
    # corridor from wherever you actually start. Searching first would quietly
    # search from the hotel on a day you left from a lunch.
    chosen_fuel = chosen_fallback = None
    if args.find_fuel:
        from departure_kit.fuel import fetch_stations, pick
        try:
            found = fetch_stations(origin_latlon, airport.return_latlon)
        except Exception as exc:
            print(f"Could not reach OpenStreetMap ({exc}).\n"
                  "Pass --fuel with an address you know instead.", file=sys.stderr)
            return 3
        best, fallback = pick(found, origin_latlon, airport.return_latlon,
                              departure.replace(tzinfo=None),
                              avoid=airport.avoid_fuel)
        if not best:
            print(f"No suitable stop among {len(found)} stations on that route. "
                  "Use --fuel, or review the airport's avoid_fuel list.",
                  file=sys.stderr)
            return 3
        chosen_fuel, chosen_fallback = best, fallback
        args.fuel = best.station.street or best.station.label
        args.fuel_latlon = (best.station.lat, best.station.lon)

        if auto_drive:
            from departure_kit.route import RoutingFailed, drive_minutes
            try:
                total, legs = drive_minutes(
                    [origin_latlon, args.fuel_latlon, airport.return_latlon]
                )
            except RoutingFailed:
                total, legs = drive, []
            plan = build_plan(
                departure=departure, airport=airport, profile=profile,
                drive_minutes=total, fuel_stop=True,
                drive_to_fuel_minutes=legs[0] if legs else None,
                origin_label=origin_label,
            )
            if decision:
                plan.steps[0].label = (
                    "Leave the hotel" if decision.source == "hotel"
                    else "Leave the last appointment"
                )

    print(plan.as_text())
    if auto_drive:
        from departure_kit.route import ATTRIBUTION
        print(f"\n{ATTRIBUTION}")

    if chosen_fuel:
        st = chosen_fuel.station
        print(f"\nFuel stop: {st.label}, {st.street}")
        print(f"  {chosen_fuel.why}")
        if chosen_fallback:
            fb = chosen_fallback.station
            print(f"  If it is dark or the pumps are down: {fb.label}, {fb.street}")
        else:
            print("  No second option on a different brand within the corridor.")

    if airport.notes:
        print(f"\n{airport.code} note: {' '.join(airport.notes.split())}")

    origin = Place("Start", origin_address, *origin_latlon, origin_place_id)
    dest = Place("Rental return", airport.return_address,
                 airport.return_latlon[0], airport.return_latlon[1],
                 airport.return_place_id)
    stops = []
    if args.fuel:
        stops.append(Place("Fuel", args.fuel, *args.fuel_latlon, args.fuel_place_id))

    link_origin = None if args.dynamic_origin else origin
    print("\nGoogle Maps, whole route:")
    print("  " + google_maps_route(link_origin, dest, stops))
    if args.dynamic_origin:
        print("  (starts from wherever you are when you open it; the leave time "
              f"above still assumes {origin_label})")
    try:
        print("\nWaze, one link per leg:")
        for label, url in waze_legs(origin, dest, stops):
            print(f"  {label}: {url}")
    except ValueError as exc:
        print(f"  (skipped: {exc})")

    if args.add_to_calendar:
        from departure_kit.gcal import create_event, service

        body = plan.as_text() + "\n\n" + google_maps_route(link_origin, dest, stops)
        created = create_event(
            service(),
            summary=f"Leave for {airport.code} (fuel stop, then rental return)",
            start=plan.leave_at.replace(tzinfo=None),
            end=(plan.leave_at + timedelta(minutes=25)).replace(tzinfo=None),
            zone=airport.timezone, description=body, location=origin_address,
        )
        print(f"\nCreated: {created.get('htmlLink')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
