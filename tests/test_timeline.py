import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from departure_kit.profile import Airport, ConfigError, Profile
from departure_kit.timeline import build_plan

FAST = Profile(security_minutes=5, terminal_walk_minutes=5, fuel_stop_minutes=8)
SLOW = Profile(security_minutes=35, terminal_walk_minutes=5, fuel_stop_minutes=8,
               round_to_minutes=1)
# Rounding to 5 makes leave times readable but adds up to 4 minutes of noise,
# which hides real differences when comparing two plans. Comparisons use this.
EXACT = Profile(security_minutes=5, terminal_walk_minutes=5, fuel_stop_minutes=8,
                round_to_minutes=1)
EXACT_CLT = Profile(security_minutes=5, terminal_walk_minutes=5, fuel_stop_minutes=8,
                    round_to_minutes=1)

SAN = Airport(
    code="SAN", name="San Diego", timezone="America/Los_Angeles",
    return_type="shuttle", return_address="3355 Admiral Boland Way",
    return_latlon=(32.73618, -117.179286),
    return_minutes=10, transfer_ride=8, transfer_wait=15,
)
CLT = Airport(
    code="CLT", name="Charlotte", timezone="America/New_York",
    return_type="terminal", return_address="5501 Josh Birmingham Pkwy",
    return_latlon=(35.2172, -80.9474), return_minutes=10,
)


def dep(y, m, d, hh, mm, zone):
    return datetime(y, m, d, hh, mm, tzinfo=ZoneInfo(zone))


def test_naive_departure_is_rejected():
    # The failure mode this guards against is silent, so it must be loud.
    with pytest.raises(ValueError, match="timezone aware"):
        build_plan(datetime(2026, 10, 17, 7, 0), SAN, FAST, drive_minutes=11)


def test_off_campus_return_sets_the_leave_time():
    plan = build_plan(
        dep(2026, 10, 17, 7, 0, "America/Los_Angeles"), SAN, FAST, drive_minutes=11
    )
    assert plan.leave_at.strftime("%H:%M") == "04:55"
    assert plan.departure.strftime("%H:%M") == "07:00"


def test_transfer_not_security_is_binding_off_campus():
    plan = build_plan(
        dep(2026, 10, 17, 7, 0, "America/Los_Angeles"), SAN, FAST, drive_minutes=11
    )
    assert "shuttle transfer at SAN" in plan.binding_constraint


def test_terminal_return_leaves_later_by_exactly_the_transfer():
    off = build_plan(dep(2026, 10, 17, 7, 0, "America/Los_Angeles"), SAN, EXACT, 11)
    on = build_plan(dep(2026, 10, 17, 7, 0, "America/New_York"), CLT, EXACT_CLT, 11)
    # Same clock time, same drive, same person. The only difference is that
    # one airport makes you ride something.
    assert off.total_minutes - on.total_minutes == SAN.transfer_total


def test_the_transfer_costs_more_than_a_fast_travellers_entire_security_time():
    # This is the claim the whole tool rests on. Being quick through the
    # checkpoint does not rescue an off campus return, because the transfer
    # is the larger number and no amount of PreCheck touches it.
    assert SAN.transfer_total > EXACT.security_minutes
    fast = build_plan(dep(2026, 10, 17, 7, 0, "America/Los_Angeles"), SAN, EXACT, 11)
    slow = build_plan(dep(2026, 10, 17, 7, 0, "America/Los_Angeles"), SAN, SLOW, 11)
    security_penalty = slow.total_minutes - fast.total_minutes
    assert security_penalty == SLOW.security_minutes - EXACT.security_minutes
    # Even the fast traveller still pays the full transfer.
    assert fast.total_minutes > SAN.transfer_total + SAN.return_minutes


def test_departure_in_another_zone_is_converted_not_reinterpreted():
    # A flight given in Eastern out of a Pacific airport must still produce a
    # Pacific plan. Getting this wrong is a three hour error.
    plan = build_plan(
        dep(2026, 10, 17, 10, 0, "America/New_York"), SAN, FAST, drive_minutes=11
    )
    assert plan.departure.strftime("%H:%M") == "07:00"
    assert plan.leave_at.strftime("%H:%M") == "04:55"


def test_generous_airside_buffer_makes_the_bag_cutoff_irrelevant():
    # Wanting 60 minutes airside puts you at the terminal 70 minutes early,
    # long before a 45 minute bag cutoff. Reporting the cutoff as binding here
    # would be false, and would tell someone to worry about the wrong thing.
    bags = Profile(security_minutes=5, terminal_walk_minutes=5, checks_bags=True,
                   airside_buffer_minutes=60)
    plan = build_plan(dep(2026, 10, 17, 7, 0, "America/Los_Angeles"), SAN, bags, 11)
    assert "bag drop cutoff" not in plan.binding_constraint
    nobags = build_plan(dep(2026, 10, 17, 7, 0, "America/Los_Angeles"), SAN, FAST, 11)
    assert plan.leave_at == nobags.leave_at


def test_tight_airside_buffer_lets_the_bag_cutoff_bind():
    bags = Profile(security_minutes=5, terminal_walk_minutes=5, checks_bags=True,
                   airside_buffer_minutes=20, round_to_minutes=1)
    plan = build_plan(dep(2026, 10, 17, 7, 0, "America/Los_Angeles"), SAN, bags, 11)
    assert "bag drop cutoff" in plan.binding_constraint
    nobags = Profile(security_minutes=5, terminal_walk_minutes=5,
                     airside_buffer_minutes=20, round_to_minutes=1)
    loose = build_plan(dep(2026, 10, 17, 7, 0, "America/Los_Angeles"), SAN, nobags, 11)
    assert plan.leave_at < loose.leave_at


def test_no_fuel_stop_removes_the_step_and_the_time():
    with_fuel = build_plan(dep(2026, 10, 17, 7, 0, "America/Los_Angeles"), SAN, FAST, 11)
    without = build_plan(
        dep(2026, 10, 17, 7, 0, "America/Los_Angeles"), SAN, FAST, 11, fuel_stop=False
    )
    assert any("Fuel" in s.label for s in with_fuel.steps)
    assert not any("Fuel" in s.label for s in without.steps)
    assert without.leave_at > with_fuel.leave_at


def test_terminal_return_with_a_transfer_time_is_a_config_error():
    with pytest.raises(ConfigError, match="not a terminal return"):
        Airport(
            code="XXX", name="Bad", timezone="America/New_York",
            return_type="terminal", return_address="a", return_latlon=(0, 0),
            transfer_ride=10,
        )


def test_shuttle_without_a_ride_time_is_a_config_error():
    with pytest.raises(ConfigError, match="transfer_ride"):
        Airport(
            code="XXX", name="Bad", timezone="America/New_York",
            return_type="shuttle", return_address="a", return_latlon=(0, 0),
        )
