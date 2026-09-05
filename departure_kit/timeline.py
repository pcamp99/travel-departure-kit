"""Building a departure timeline backward from the scheduled departure.

The whole idea is that a departure time is a sum of named segments, not a
single fudge factor. Once the segments are explicit you can see which one is
actually binding. At an airport with a terminal return it is usually security.
At an airport with an off campus return it is almost never security.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .profile import Airport, Profile


@dataclass
class Step:
    at: datetime
    label: str
    detail: str = ""

    def local(self, fmt: str = "%H:%M") -> str:
        return self.at.strftime(fmt)


@dataclass
class Plan:
    steps: list[Step]
    airport: Airport
    profile: Profile
    departure: datetime
    binding_constraint: str

    @property
    def leave_at(self) -> datetime:
        return self.steps[0].at

    @property
    def total_minutes(self) -> int:
        return int((self.departure - self.leave_at).total_seconds() // 60)

    def as_text(self) -> str:
        tzname = self.departure.tzname() or self.airport.timezone
        lines = [
            f"Departure plan, all times {self.airport.name} local ({tzname})",
            "",
        ]
        for step in self.steps:
            lines.append(f"  {step.local()}  {step.label}")
            if step.detail:
                lines.append(f"         {step.detail}")
        lines += [
            "",
            f"Total elapsed: {self.total_minutes} minutes.",
            f"Binding constraint: {self.binding_constraint}.",
        ]
        return "\n".join(lines)


def _round_down(when: datetime, to_minutes: int) -> datetime:
    when = when.replace(second=0, microsecond=0)
    return when - timedelta(minutes=when.minute % to_minutes)


def build_plan(
    departure: datetime,
    airport: Airport,
    profile: Profile,
    drive_minutes: int,
    fuel_stop: bool = True,
    drive_to_fuel_minutes: int | None = None,
    origin_label: str = "hotel",
) -> Plan:
    """Work backward from the scheduled departure to a time to leave.

    departure must be timezone aware. Passing a naive datetime is the single
    most likely way to get a plan that is silently hours wrong, so it raises.

    drive_minutes is the whole drive, origin to rental return, ignoring the
    fuel stop. drive_to_fuel_minutes is how much of that is before the stop;
    it only changes the displayed time of the fuel step, not the total.
    """
    if departure.tzinfo is None:
        raise ValueError(
            "departure must be timezone aware. A naive datetime here produces a "
            "plan that looks correct and is wrong by the offset."
        )
    departure = departure.astimezone(airport.zone())

    airside = departure - timedelta(minutes=profile.airside_buffer_minutes)

    # If a bag is checked, the airline cutoff can bite before the airside
    # target does. Take whichever is earlier.
    bag_cutoff_binds = False
    if profile.checks_bags:
        # The bag counter is on the public side, before the checkpoint. So the
        # cutoff constrains when you must be AT THE TERMINAL, and the walk and
        # security time sit after it, not before. Subtracting them here instead
        # of adding them was a real bug: it made the cutoff look binding when
        # it was not, and pulled departure times 20 minutes early for no reason.
        terminal_deadline = departure - timedelta(
            minutes=profile.bag_drop_cutoff_minutes
        )
        implied_airside = terminal_deadline + timedelta(
            minutes=profile.terminal_walk_minutes + profile.security_minutes
        )
        if implied_airside < airside:
            airside = implied_airside
            bag_cutoff_binds = True

    checkpoint = airside - timedelta(minutes=profile.security_minutes)
    terminal_arrive = checkpoint - timedelta(minutes=profile.terminal_walk_minutes)
    keys = terminal_arrive - timedelta(minutes=airport.transfer_total)
    return_arrive = keys - timedelta(minutes=airport.return_minutes)

    # Precedence matters. A bag drop cutoff is a hard wall set by the airline,
    # so it outranks an observation about which segment is longest. Reporting
    # the transfer here instead would tell someone to relax about the one
    # deadline they cannot negotiate.
    if bag_cutoff_binds:
        binding = f"the {profile.bag_drop_cutoff_minutes} minute bag drop cutoff"
    elif airport.is_off_campus and airport.transfer_total >= profile.security_minutes:
        binding = (
            f"the {airport.transfer_total} minute {airport.return_type} transfer at "
            f"{airport.code}, not security"
        )
    else:
        binding = f"your {profile.airside_buffer_minutes} minute airside buffer"

    fuel_minutes = profile.fuel_stop_minutes if fuel_stop else 0
    leave = return_arrive - timedelta(minutes=drive_minutes + fuel_minutes)
    leave = _round_down(leave, profile.round_to_minutes)

    steps = [Step(leave, f"Leave {origin_label}")]

    if fuel_stop:
        if drive_to_fuel_minutes is None:
            drive_to_fuel_minutes = max(1, drive_minutes // 2)
        steps.append(
            Step(
                leave + timedelta(minutes=drive_to_fuel_minutes),
                "Fuel stop",
                f"{profile.fuel_stop_minutes} minutes including getting off and back on the road",
            )
        )

    steps.append(
        Step(
            return_arrive,
            f"Arrive {airport.code} rental return",
            airport.return_address,
        )
    )
    steps.append(
        Step(keys, "Keys handed over", f"{airport.return_minutes} minutes for the return")
    )

    if airport.is_off_campus:
        steps.append(
            Step(
                keys,
                f"Board the {airport.return_type} to the terminal",
                f"{airport.transfer_ride} minute ride, up to {airport.transfer_wait} minutes waiting",
            )
        )

    steps.append(Step(terminal_arrive, "At the terminal"))
    steps.append(
        Step(checkpoint, "Through security", f"{profile.security_minutes} minutes budgeted")
    )
    steps.append(Step(airside, "Airside, buffer starts"))
    steps.append(Step(departure, "Scheduled departure"))

    return Plan(
        steps=steps,
        airport=airport,
        profile=profile,
        departure=departure,
        binding_constraint=binding,
    )
