import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from departure_kit.origin import infer_origin

PT = ZoneInfo("America/Los_Angeles")
HOTEL = "1515 Hotel Cir S, San Diego, CA 92108"
OFFICE = "754 Medical Center Ct, Chula Vista, CA 91911"
SKIP = ["zoom", "teams"]


def ev(summary, start_h, end_h, location=OFFICE, day=17, **extra):
    e = {
        "summary": summary,
        "location": location,
        "start": {"dateTime": datetime(2026, 10, day, start_h, 0, tzinfo=PT).isoformat()},
        "end": {"dateTime": datetime(2026, 10, day, end_h, 0, tzinfo=PT).isoformat()},
    }
    e.update(extra)
    return e


def dep(h, m=0, day=17):
    return datetime(2026, 10, day, h, m, tzinfo=PT)


def test_no_appointments_means_the_hotel():
    d = infer_origin([], dep(7), 125, HOTEL)
    assert d.source == "hotel" and d.confident


def test_lunch_ending_just_before_the_leave_time_wins():
    # Lunch 12 to 13, flight at 16:00, plan 125 min so leave at 13:55.
    events = [ev("Cardiology lunch", 12, 13)]
    d = infer_origin(events, dep(16), 125, HOTEL)
    assert d.source == "appointment"
    assert d.address == OFFICE
    assert d.confident


def test_an_early_flight_still_uses_a_breakfast_meeting():
    # This is the case a "before 9 am means hotel" rule gets wrong.
    events = [ev("Breakfast with the practice", 5, 6)]
    d = infer_origin(events, dep(9), 125, HOTEL)  # leave at 06:55
    assert d.source == "appointment"
    assert d.confident


def test_an_afternoon_flight_after_a_morning_meeting_goes_back_to_the_hotel():
    # The other case the clock rule gets wrong: 4 pm flight, last call at 9 am.
    events = [ev("Morning call", 8, 9)]
    d = infer_origin(events, dep(16), 125, HOTEL)  # leave at 13:55, gap ~5 h
    assert d.source == "hotel"
    assert not d.confident
    assert d.alternative == OFFICE


def test_the_ambiguous_case_names_the_other_option_and_says_so():
    events = [ev("Morning call", 8, 9)]
    d = infer_origin(events, dep(16), 125, HOTEL)
    text = d.describe()
    assert "Ambiguous" in text
    assert "--origin-from appointment" in text


def test_the_latest_qualifying_appointment_is_chosen_not_the_first():
    events = [ev("Early one", 8, 9), ev("The real last one", 12, 13, location="X St")]
    d = infer_origin(events, dep(16), 125, HOTEL)
    assert d.address == "X St"


def test_an_appointment_after_you_leave_is_ignored():
    # Something scheduled during or after the drive cannot be the origin.
    events = [ev("Too late", 14, 15)]
    d = infer_origin(events, dep(16), 125, HOTEL)  # leave at 13:55
    assert d.source == "hotel"


def test_an_event_with_no_address_cannot_be_an_origin():
    events = [ev("Phone catch up", 12, 13, location="")]
    d = infer_origin(events, dep(16), 125, HOTEL)
    assert d.source == "hotel"


def test_a_video_call_is_not_a_place_you_drive_from():
    events = [ev("Zoom with the region", 12, 13)]
    d = infer_origin(events, dep(16), 125, HOTEL, skip_patterns=SKIP)
    assert d.source == "hotel"


def test_all_day_events_are_ignored():
    events = [{"summary": "San Diego", "location": "San Diego, CA",
               "start": {"date": "2026-10-17"}, "end": {"date": "2026-10-18"}}]
    d = infer_origin(events, dep(16), 125, HOTEL)
    assert d.source == "hotel"


def test_something_from_days_earlier_is_not_dragged_in():
    events = [ev("Two days ago", 12, 13, day=15)]
    d = infer_origin(events, dep(16), 125, HOTEL)
    assert d.source == "hotel"
    assert d.alternative == ""


def test_force_hotel_overrides_a_confident_appointment():
    events = [ev("Cardiology lunch", 12, 13)]
    d = infer_origin(events, dep(16), 125, HOTEL, force="hotel")
    assert d.source == "hotel" and d.confident
    assert "Forced" in d.reason


def test_force_appointment_overrides_the_ambiguous_default():
    events = [ev("Morning call", 8, 9)]
    d = infer_origin(events, dep(16), 125, HOTEL, force="appointment")
    assert d.source == "appointment" and d.confident
    assert d.address == OFFICE


def test_forcing_an_appointment_that_does_not_exist_falls_back_honestly():
    d = infer_origin([], dep(16), 125, HOTEL, force="appointment")
    assert d.source == "hotel"
    assert "nothing on the calendar" in d.reason.lower()


def test_the_plan_length_shifts_which_appointment_qualifies():
    # A longer plan means an earlier leave time, which can push the last
    # appointment out of the direct window. The inference has to move with it.
    events = [ev("Lunch", 12, 13)]
    short = infer_origin(events, dep(15), 60, HOTEL)   # leave 14:00, gap 60
    long = infer_origin(events, dep(15), 240, HOTEL)   # leave 11:00, ends after
    assert short.source == "appointment"
    assert long.source == "hotel"


def test_a_reachable_appointment_reports_no_conflict():
    from departure_kit.origin import conflicts
    events = [ev("Lunch", 11, 13)]
    d = infer_origin(events, dep(16), 140, HOTEL)   # leave 13:40, ends 13:00
    assert d.source == "appointment"
    assert conflicts(dep(13, 40), d) == 0


def test_leaving_before_the_appointment_ends_is_a_conflict_not_ambiguity():
    from departure_kit.origin import conflicts
    events = [ev("Lunch", 12, 14)]
    d = infer_origin(events, dep(16), 115, HOTEL)   # hotel plan: leave 14:05
    assert d.source == "appointment"
    # But the drive from that appointment is longer, so the real leave time
    # lands before the appointment finishes.
    assert conflicts(dep(13, 40), d) == 20


def test_a_hotel_decision_can_never_be_a_conflict():
    from departure_kit.origin import conflicts
    d = infer_origin([], dep(16), 125, HOTEL)
    assert conflicts(dep(13, 40), d) == 0
