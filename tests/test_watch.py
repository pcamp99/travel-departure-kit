import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from departure_kit.profile import load_airports
from departure_kit.watch import (
    Flight, already_planned, departure_airport, find_flights, find_lodging,
    looks_like_a_flight, next_actionable, plan_marker,
)

AIRPORTS = load_airports()
CODES = set(AIRPORTS)
PT = ZoneInfo("America/Los_Angeles")
ET = ZoneInfo("America/New_York")


def event(summary, location="", start=None, **extra):
    e = {"id": "evt1", "summary": summary, "location": location}
    if start:
        e["start"] = {"dateTime": start.isoformat()}
        e["end"] = {"dateTime": (start + timedelta(hours=2)).isoformat()}
    e.update(extra)
    return e


# --- telling a flight from an ordinary meeting -------------------------------

def test_a_flight_number_is_enough():
    assert looks_like_a_flight(event("AA 1651 SAN to CLT"))
    assert looks_like_a_flight(event("DL2201 to Atlanta"))


def test_parenthesised_codes_are_enough():
    assert looks_like_a_flight(event("Trip home", "San Diego (SAN) - Charlotte (CLT)"))


def test_a_meeting_that_happens_to_contain_a_code_is_not_a_flight():
    # The failure this guards: a bare three letter string is not a departure.
    assert not looks_like_a_flight(event("SAN planning meeting", "Conference room B"))
    assert not looks_like_a_flight(event("CLT quarterly review"))


def test_a_user_pattern_can_add_a_source():
    assert looks_like_a_flight(event("Egencia itinerary"), extra_patterns=["egencia"])


# --- working out where you leave from ----------------------------------------

def test_the_origin_airport_is_the_first_code_not_the_last():
    ev = event("AA 1651", "San Diego (SAN) - Charlotte (CLT)")
    assert departure_airport(ev, CODES) == "SAN"


def test_an_unconfigured_airport_returns_nothing_rather_than_a_guess():
    # Planning needs the rental return profile. No profile, no plan.
    ev = event("AA 100", "Boston (BOS) - Charlotte (CLT)")
    assert departure_airport(ev, CODES) is None


def test_a_bare_code_is_accepted_only_when_it_is_a_configured_airport():
    assert departure_airport(event("AA 871 PHX CLT"), CODES) == "PHX"
    assert departure_airport(event("AA 871 XYZ ABC"), CODES) is None


# --- collecting flights -------------------------------------------------------

def test_flights_come_back_earliest_first():
    events = [
        event("AA 1651", "San Diego (SAN) - Charlotte (CLT)",
              start=datetime(2026, 10, 17, 7, tzinfo=PT), id="b"),
        event("AA 871", "Phoenix (PHX) - Charlotte (CLT)",
              start=datetime(2026, 9, 12, 6, 20, tzinfo=ZoneInfo("America/Phoenix")),
              id="a"),
    ]
    found = find_flights(events, AIRPORTS)
    assert [f.event_id for f in found] == ["a", "b"]


def test_the_outbound_from_your_home_airport_is_skipped():
    # Leaving home you park your own car. Different problem, different numbers.
    events = [
        event("AA 466", "Charlotte (CLT) - San Diego (SAN)",
              start=datetime(2026, 10, 13, 7, 5, tzinfo=ET), id="out"),
        event("AA 1651", "San Diego (SAN) - Charlotte (CLT)",
              start=datetime(2026, 10, 17, 7, tzinfo=PT), id="back"),
    ]
    found = find_flights(events, AIRPORTS, home_airport="CLT")
    assert [f.event_id for f in found] == ["back"]


def test_a_junk_event_time_zone_does_not_corrupt_the_departure():
    # A real calendar carried a Phoenix flight labelled Africa/Abidjan while
    # holding the correct instant. Trust the instant, take the zone from the
    # airport.
    ev = event("AA 871", "Phoenix (PHX) - Charlotte (CLT)",
               start=datetime(2026, 9, 12, 6, 20, tzinfo=ZoneInfo("America/Phoenix")))
    ev["start"]["timeZone"] = "Africa/Abidjan"
    flight = find_flights([ev], AIRPORTS)[0]
    assert flight.departure.strftime("%H:%M") == "06:20"
    assert str(flight.departure.tzinfo) == "America/Phoenix"


def test_an_all_day_event_is_not_a_flight():
    ev = {"id": "x", "summary": "AA 871 PHX", "location": "(PHX)",
          "start": {"date": "2026-09-12"}}
    assert find_flights([ev], AIRPORTS) == []


# --- where you are staying ----------------------------------------------------

def test_a_gmail_stay_at_event_supplies_the_address():
    events = [event("Stay at DoubleTree Hotel Circle",
                    "1515 Hotel Cir S, San Diego, CA 92108",
                    start=datetime(2026, 10, 13, 15, tzinfo=PT))]
    got = find_lodging(events, datetime(2026, 10, 17, 7, tzinfo=PT))
    assert got.startswith("1515 Hotel Cir S")


def test_the_later_hotel_wins_when_a_trip_has_two():
    events = [
        event("Hampton Inn Kearny Mesa", "5434 Kearny Mesa Rd, San Diego, CA",
              start=datetime(2026, 10, 13, 15, tzinfo=PT)),
        event("DoubleTree Hotel Circle", "1515 Hotel Cir S, San Diego, CA 92108",
              start=datetime(2026, 10, 15, 15, tzinfo=PT)),
    ]
    got = find_lodging(events, datetime(2026, 10, 17, 7, tzinfo=PT))
    assert got.startswith("1515 Hotel Cir S")


def test_a_hotel_booked_after_the_flight_is_ignored():
    events = [event("Hilton Charlotte", "222 E Third St, Charlotte, NC",
                    start=datetime(2026, 10, 20, 15, tzinfo=ET))]
    assert find_lodging(events, datetime(2026, 10, 17, 7, tzinfo=PT)) is None


def test_no_lodging_returns_none_rather_than_a_guess():
    events = [event("Cardiology lunch", "754 Medical Center Ct, Chula Vista, CA",
                    start=datetime(2026, 10, 15, 12, tzinfo=PT))]
    assert find_lodging(events, datetime(2026, 10, 17, 7, tzinfo=PT)) is None


def test_an_all_day_hotel_block_still_counts():
    # Gmail writes some stays as all day events.
    ev = {"id": "h", "summary": "Stay at DoubleTree",
          "location": "1515 Hotel Cir S, San Diego, CA 92108",
          "start": {"date": "2026-10-13"}}
    got = find_lodging([ev], datetime(2026, 10, 17, 7, tzinfo=PT))
    assert got.startswith("1515 Hotel Cir S")


# --- not doing it twice --------------------------------------------------------

def test_a_plan_written_yesterday_is_recognised_today():
    # A daily job that forgets itself writes a duplicate every morning.
    flight = Flight(datetime(2026, 10, 17, 7, tzinfo=PT), "SAN", "flight123", "AA 1651")
    existing = [{"description": f"Leave at 04:55\n{plan_marker(flight)}"}]
    assert already_planned(existing, flight)


def test_a_plan_for_a_different_flight_does_not_count():
    flight = Flight(datetime(2026, 10, 17, 7, tzinfo=PT), "SAN", "flight123", "AA 1651")
    other = Flight(datetime(2026, 9, 12, 6, 20, tzinfo=PT), "PHX", "flight999", "AA 871")
    existing = [{"description": plan_marker(other)}]
    assert not already_planned(existing, flight)


# --- plans written by hand, which carry no marker -------------------------------

SAN_FLIGHT = Flight(datetime(2026, 10, 17, 7, tzinfo=PT), "SAN", "flight123", "AA 1651")


def leave_for(code, start, description="Leave at 04:55"):
    return event(f"Leave for {code} (fuel stop, then rental return)",
                 start=start, description=description)


def test_a_marked_plan_is_recognised_by_its_marker():
    marked = leave_for("SAN", datetime(2026, 10, 17, 4, 55, tzinfo=PT),
                       description=f"Leave at 04:55\n\n{plan_marker(SAN_FLIGHT)}")
    assert already_planned([marked], SAN_FLIGHT)


def test_a_hand_made_plan_before_this_flight_is_recognised():
    # Written in Eastern time on purpose: the comparison must be on the
    # instant, read in the airport's zone, not on the event's own label.
    hand_made = leave_for("SAN", datetime(2026, 10, 17, 7, 55, tzinfo=ET))
    assert already_planned([hand_made], SAN_FLIGHT)


def test_a_hand_made_plan_the_day_before_does_not_count():
    yesterday = leave_for("SAN", datetime(2026, 10, 16, 4, 55, tzinfo=PT))
    assert not already_planned([yesterday], SAN_FLIGHT)


def test_a_hand_made_plan_for_another_airport_the_same_morning_does_not_count():
    elsewhere = leave_for("LAX", datetime(2026, 10, 17, 4, 55, tzinfo=PT))
    assert not already_planned([elsewhere], SAN_FLIGHT)


def test_a_marked_plan_for_another_flight_is_not_taken_as_hand_made():
    # Two departures from one airport inside the window: the first flight's
    # plan carries its own marker and must not suppress the second's.
    other = Flight(datetime(2026, 10, 17, 5, tzinfo=PT), "SAN", "flight999", "AA 871")
    theirs = leave_for("SAN", datetime(2026, 10, 17, 2, 55, tzinfo=PT),
                       description=plan_marker(other))
    assert not already_planned([theirs], SAN_FLIGHT)


# --- only when it is time -------------------------------------------------------

def test_a_flight_inside_the_lead_window_is_actionable():
    now = datetime(2026, 10, 16, 18, tzinfo=PT)
    flight = Flight(datetime(2026, 10, 17, 7, tzinfo=PT), "SAN", "f", "AA 1651")
    assert next_actionable(flight, now, lead_hours=24)


def test_a_flight_weeks_away_is_not_planned_yet():
    # Planning early is worse than useless: the calendar it was computed from
    # will have changed by the morning it matters.
    now = datetime(2026, 9, 5, 8, tzinfo=PT)
    flight = Flight(datetime(2026, 10, 17, 7, tzinfo=PT), "SAN", "f", "AA 1651")
    assert not next_actionable(flight, now, lead_hours=24)


def test_a_flight_already_departed_is_not_planned():
    now = datetime(2026, 10, 17, 9, tzinfo=PT)
    flight = Flight(datetime(2026, 10, 17, 7, tzinfo=PT), "SAN", "f", "AA 1651")
    assert not next_actionable(flight, now, lead_hours=24)


def test_an_unknown_origin_is_named_so_it_can_be_added():
    # Silently ignoring a flight the user can see on their own calendar is
    # confusing. Naming the missing airport is actionable.
    from departure_kit.watch import unconfigured_departure
    ev = event("AA 100", "Boston (BOS) - Charlotte (CLT)")
    assert unconfigured_departure(ev, CODES) == "BOS"
    known = event("AA 1651", "San Diego (SAN) - Charlotte (CLT)")
    assert unconfigured_departure(known, CODES) is None


def test_an_ordinary_event_with_a_three_letter_token_is_not_reported_as_a_flight():
    # A real run announced "Flight from SFP found" because the reporting path
    # checked for an airport code without first checking the event was a
    # flight at all. find_flights had that guard; the reporter did not.
    from departure_kit.watch import unconfigured_departure
    ordinary = event("SFP review", "Conference room")
    assert not looks_like_a_flight(ordinary)
    # The code alone still resolves, which is why the flight check has to come
    # first rather than being implied by this function.
    assert unconfigured_departure(ordinary, CODES) == "SFP"


def test_a_genuine_flight_from_an_unconfigured_airport_is_still_reported():
    from departure_kit.watch import unconfigured_departure
    real = event("AA 100", "Boston (BOS) - Charlotte (CLT)")
    assert looks_like_a_flight(real)
    assert unconfigured_departure(real, CODES) == "BOS"
