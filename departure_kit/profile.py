"""Loading and validating the two config files.

profile.yaml is the user. airports.yaml is the world. Keeping them apart is
what lets people share airport knowledge without sharing anything personal.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

CONFIG_DIR = os.environ.get(
    "DEPARTURE_KIT_CONFIG",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config"),
)


class ConfigError(Exception):
    """Raised when config is missing or self contradictory.

    Deliberately loud. A silently defaulted airport is worse than a crash,
    because it produces a plan that looks right and is thirty minutes wrong.
    """


@dataclass
class Profile:
    home_timezone: str = "America/New_York"
    airside_buffer_minutes: int = 60
    security_minutes: int = 15
    terminal_walk_minutes: int = 5
    fuel_stop_minutes: int = 8
    checks_bags: bool = False
    bag_drop_cutoff_minutes: int = 45
    round_to_minutes: int = 5
    tz_fixer: dict = field(default_factory=dict)
    watch: dict = field(default_factory=dict)

    def __post_init__(self):
        _require_zone(self.home_timezone, "profile.home_timezone")
        if self.round_to_minutes < 1:
            raise ConfigError("round_to_minutes must be at least 1")
        for name in (
            "airside_buffer_minutes",
            "security_minutes",
            "terminal_walk_minutes",
            "fuel_stop_minutes",
        ):
            if getattr(self, name) < 0:
                raise ConfigError(f"{name} cannot be negative")

    @property
    def trusted_creators(self) -> list[str]:
        raw = self.tz_fixer.get("trusted_local_time_creators") or []
        return [str(x).strip().lower() for x in raw if str(x).strip()]

    @property
    def skip_patterns(self) -> list[str]:
        raw = self.tz_fixer.get("skip_if_matches") or []
        return [str(x).strip().lower() for x in raw if str(x).strip()]

    @property
    def city_overrides(self) -> dict[str, str]:
        raw = self.tz_fixer.get("city_overrides") or {}
        return {str(k).strip().lower(): str(v).strip() for k, v in raw.items()}


@dataclass
class Airport:
    code: str
    name: str
    timezone: str
    return_type: str
    return_address: str
    return_latlon: tuple[float, float]
    return_place_id: str | None = None
    return_minutes: int = 10
    transfer_ride: int = 0
    transfer_wait: int = 0
    notes: str = ""
    avoid_fuel: list = field(default_factory=list)

    VALID_RETURN_TYPES = ("terminal", "shuttle", "train")

    def __post_init__(self):
        _require_zone(self.timezone, f"airports.{self.code}.timezone")
        if self.return_type not in self.VALID_RETURN_TYPES:
            raise ConfigError(
                f"{self.code}: return_type {self.return_type!r} must be one of "
                f"{', '.join(self.VALID_RETURN_TYPES)}"
            )
        if self.return_type == "terminal" and (self.transfer_ride or self.transfer_wait):
            raise ConfigError(
                f"{self.code}: return_type is 'terminal' but a transfer time is set. "
                "If you park and walk there is no transfer; if there is a transfer "
                "it is not a terminal return."
            )
        if self.return_type != "terminal" and self.transfer_ride <= 0:
            raise ConfigError(
                f"{self.code}: return_type is {self.return_type!r} so transfer_ride "
                "must be greater than zero."
            )

    @property
    def transfer_total(self) -> int:
        """Worst case minutes from leaving the rental counter to the terminal door."""
        return self.transfer_ride + self.transfer_wait

    @property
    def is_off_campus(self) -> bool:
        return self.return_type != "terminal"

    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


def _no_zone_database() -> bool:
    """True when no IANA database is reachable, so every name fails alike.

    zoneinfo reads the system database and bundles none of its own. Windows
    ships no such database, and minimal Linux images often drop it. On those
    machines a correct zone name and a typo produce the identical error, and
    the two have opposite fixes: install a package, or edit the config. Probing
    a name that exists in every database tells them apart.
    """
    try:
        ZoneInfo("UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return True
    return False


def _require_zone(name: str, where: str) -> None:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        if _no_zone_database():
            raise ConfigError(
                f"{where}: this machine has no IANA time zone database, so no zone "
                f"name resolves and {name!r} may well be correct. "
                "Install it with: python -m pip install tzdata"
            ) from exc
        raise ConfigError(f"{where}: {name!r} is not a valid IANA time zone") from exc


def load_profile(path: str | None = None) -> Profile:
    path = path or os.path.join(CONFIG_DIR, "profile.yaml")
    if not os.path.exists(path):
        example = os.path.join(CONFIG_DIR, "profile.example.yaml")
        raise ConfigError(
            f"No profile at {path}. Copy {example} to {path} and edit it."
        )
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    known = {f for f in Profile.__dataclass_fields__}
    unknown = set(data) - known
    if unknown:
        raise ConfigError(
            f"Unrecognised keys in profile.yaml: {', '.join(sorted(unknown))}. "
            "A typo here fails silently otherwise."
        )
    return Profile(**data)


def load_airports(path: str | None = None) -> dict[str, Airport]:
    path = path or os.path.join(CONFIG_DIR, "airports.yaml")
    if not os.path.exists(path):
        raise ConfigError(f"No airports file at {path}")
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    out: dict[str, Airport] = {}
    for code, spec in data.items():
        spec = dict(spec or {})
        latlon = spec.pop("return_latlon", None)
        if not latlon or len(latlon) != 2:
            raise ConfigError(f"{code}: return_latlon must be [lat, lon]")
        out[code.upper()] = Airport(
            code=code.upper(), return_latlon=(float(latlon[0]), float(latlon[1])), **spec
        )
    return out


def get_airport(code: str, airports: dict[str, Airport] | None = None) -> Airport:
    airports = airports if airports is not None else load_airports()
    code = code.upper().strip()
    if code not in airports:
        raise ConfigError(
            f"No profile for airport {code}. Add it to config/airports.yaml. "
            "Guessing a rental return transfer time is exactly the error this "
            "tool exists to prevent."
        )
    return airports[code]
