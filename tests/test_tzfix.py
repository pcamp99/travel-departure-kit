import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from departure_kit.tzfix import Ambiguous, examine, same_offset, zone_from_location

TRUSTED = ["assistant@example.com"]
SKIP = ["zoom", "teams"]


def event(**kw):
    base = {
        "id": "e1",
        "summary": "Cardiology lunch",
        "location": "1910 E Thomas Rd, Phoenix, AZ 85016, USA",
        "creator": {"email": "assistant@example.com"},
        "start": {"dateTime": "2026-09-10T11:00:00-04:00", "timeZone": "America/New_York"},
    }
    base.update(kw)
    return base


def test_resolves_a_single_zone_state():
    assert zone_from_location("1910 E Thomas Rd, Phoenix, AZ 85016") == "America/Phoenix"


def test_refuses_a_split_state_rather_than_guessing():
    with pytest.raises(Ambiguous, match="spans more than one"):
        zone_from_location("100 Main St, El Paso, TX 79901")


def test_city_override_rescues_a_split_state():
    got = zone_from_location(
        "100 Main St, El Paso, TX 79901", {"el paso, tx": "America/Denver"}
    )
    assert got == "America/Denver"


def test_refuses_when_there_is_no_state_at_all():
    with pytest.raises(Ambiguous, match="no US state"):
        zone_from_location("Conference room B")


def test_arizona_and_denver_differ_only_in_summer():
    summer = datetime(2026, 7, 1, 12, tzinfo=ZoneInfo("UTC"))
    winter = datetime(2026, 1, 1, 12, tzinfo=ZoneInfo("UTC"))
    assert not same_offset("America/Phoenix", "America/Denver", summer)
    assert same_offset("America/Phoenix", "America/Denver", winter)


def test_trusted_creator_mismatch_is_marked_for_fixing():
    found = examine(event(), "America/New_York", TRUSTED, SKIP, {})
    assert found.action == "fix"
    assert found.location_zone == "America/Phoenix"
    assert found.start_wall.strftime("%H:%M") == "11:00"
    assert found.corrected_start.strftime("%H:%M") == "11:00"


def test_untrusted_creator_is_reported_not_rewritten():
    found = examine(
        event(creator={"email": "noreply@booking.example"}),
        "America/New_York", TRUSTED, SKIP, {},
    )
    assert found.action == "report"
    assert "ambiguous" in found.reason


def test_local_appointment_produces_no_finding():
    local = event(location="6010 E W T Harris Blvd, Charlotte, NC, United States")
    assert examine(local, "America/New_York", TRUSTED, SKIP, {}) is None


def test_video_call_is_skipped_even_with_a_far_away_address():
    call = event(summary="Zoom with Phoenix office")
    assert examine(call, "America/New_York", TRUSTED, SKIP, {}) is None


def test_all_day_event_is_ignored():
    allday = event(start={"date": "2026-09-10"})
    assert examine(allday, "America/New_York", TRUSTED, SKIP, {}) is None


def test_unresolvable_location_is_reported_not_silently_dropped():
    found = examine(
        event(location="500 Congress Ave, Austin, TX 78701"),
        "America/New_York", TRUSTED, SKIP, {},
    )
    assert found.action == "report"
    assert "cannot resolve" in found.reason


def test_correction_preserves_the_wall_clock_and_moves_the_instant():
    found = examine(event(), "America/New_York", TRUSTED, SKIP, {})
    before = datetime.fromisoformat("2026-09-10T11:00:00-04:00")
    after = found.corrected_start
    assert after.utcoffset() != before.utcoffset()
    assert (after - before).total_seconds() == 3 * 3600
