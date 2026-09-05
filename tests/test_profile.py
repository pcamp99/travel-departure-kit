import os
import sys
from zoneinfo import ZoneInfoNotFoundError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from departure_kit import profile as profile_mod
from departure_kit.profile import ConfigError, _require_zone


def test_accepts_a_real_zone():
    _require_zone("America/New_York", "profile.home_timezone")


def test_rejects_a_bad_zone_by_name():
    with pytest.raises(ConfigError) as exc:
        _require_zone("America/Charlotte", "profile.home_timezone")
    assert "not a valid IANA time zone" in str(exc.value)
    assert "tzdata" not in str(exc.value)


def test_missing_database_blames_the_database_not_the_name(monkeypatch):
    """A machine with no tz database must not accuse a correct zone name.

    This is the Windows first-run failure: zoneinfo bundles no database, so
    'America/New_York' raised "is not a valid IANA time zone" and sent people
    editing a config file that was already right.
    """

    def no_database(name, *args, **kwargs):
        raise ZoneInfoNotFoundError(f"No time zone found with key {name}")

    monkeypatch.setattr(profile_mod, "ZoneInfo", no_database)

    with pytest.raises(ConfigError) as exc:
        _require_zone("America/New_York", "profile.home_timezone")

    message = str(exc.value)
    assert "no IANA time zone database" in message
    assert "pip install tzdata" in message
    assert "is not a valid IANA time zone" not in message
