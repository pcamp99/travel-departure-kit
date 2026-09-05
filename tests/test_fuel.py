import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from departure_kit.fuel import (
    build_query, detour_km, haversine_km, is_open_at, parse_overpass, pick, rank,
)

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "overpass_san.json")

HOTEL = (32.758335, -117.176866)      # DoubleTree, Hotel Circle
RETURN = (32.736180, -117.179286)     # SAN Rental Car Center
FIVE_AM = datetime(2026, 10, 17, 4, 56)   # a Saturday


def stations():
    with open(FIXTURE, encoding="utf-8") as fh:
        return parse_overpass(json.load(fh))


# --- opening hours ----------------------------------------------------------

def test_24_7_is_open_at_any_hour():
    assert is_open_at("24/7", FIVE_AM) is True


def test_daytime_hours_are_closed_before_dawn():
    assert is_open_at("Mo-Su 06:00-22:00", FIVE_AM) is False


def test_missing_hours_is_unknown_not_closed():
    # Most stations near an airport are open and simply untagged. Treating
    # absent data as "closed" would throw away the best candidate.
    assert is_open_at("", FIVE_AM) is None


def test_overnight_range_wraps_past_midnight():
    assert is_open_at("Mo-Su 22:00-06:00", FIVE_AM) is True


def test_weekend_only_rule_applies_on_a_saturday():
    assert is_open_at("Mo-Fr 06:00-22:00; Sa-Su 04:00-23:00", FIVE_AM) is True


def test_unparseable_syntax_returns_unknown_rather_than_guessing():
    assert is_open_at("sunrise-sunset", FIVE_AM) is None


# --- geometry ---------------------------------------------------------------

def test_haversine_matches_a_known_short_distance():
    km = haversine_km(HOTEL, RETURN)
    assert 2.4 < km < 2.6  # hotel to rental centre is about 2.5 km straight line


def test_a_station_on_the_line_has_almost_no_detour():
    midpoint = ((HOTEL[0] + RETURN[0]) / 2, (HOTEL[1] + RETURN[1]) / 2)
    assert detour_km(HOTEL, midpoint, RETURN) < 0.05


def test_a_station_off_to_the_side_costs_real_distance():
    far = (32.833939, -117.175311)  # Clairemont Mesa, well north
    assert detour_km(HOTEL, far, RETURN) > 10


def test_query_covers_both_endpoints():
    q = build_query(HOTEL, RETURN)
    assert "amenity" in q and "fuel" in q
    assert "[out:json]" in q


# --- ranking ----------------------------------------------------------------

def test_closed_station_is_dropped():
    picked = rank(stations(), HOTEL, RETURN, FIVE_AM)
    names = [f"{c.station.label} {c.station.street}" for c in picked]
    assert not any("Camino del Rio W" in n for n in names)


def test_far_off_route_station_is_dropped():
    picked = rank(stations(), HOTEL, RETURN, FIVE_AM)
    assert not any("Clairemont" in c.station.street for c in picked)


def test_station_too_close_to_the_return_is_dropped():
    # A pump inside the airport loop leaves no margin and often is not a
    # public station at all.
    picked = rank(stations(), HOTEL, RETURN, FIVE_AM)
    assert not any("Admiral Boland" in c.station.street for c in picked)


def test_the_on_route_24_hour_station_wins():
    best, _ = pick(stations(), HOTEL, RETURN, FIVE_AM)
    assert best is not None
    assert "Old Town Ave" in best.station.street
    assert best.station.label == "ARCO"


def test_only_one_winner_is_returned_not_a_shortlist():
    best, fallback = pick(stations(), HOTEL, RETURN, FIVE_AM)
    assert best is not None
    # A fallback is allowed, but it must be a different brand: if the ARCO is
    # dark at 4 am, the other ARCO probably is too.
    if fallback:
        assert fallback.station.brand.lower() != best.station.brand.lower()


def test_avoid_list_removes_a_known_trap_by_street():
    # This is the human knowledge layer. No API knows a station gouges.
    without = pick(stations(), HOTEL, RETURN, FIVE_AM, avoid=["Old Town Ave"])[0]
    assert without is not None
    assert "Old Town Ave" not in without.station.street


def test_avoid_list_can_target_a_specific_osm_id():
    best, _ = pick(stations(), HOTEL, RETURN, FIVE_AM, avoid=["node/1001"])
    assert best is not None
    assert best.station.osm_id != "node/1001"


def test_reason_string_explains_the_pick():
    best, _ = pick(stations(), HOTEL, RETURN, FIVE_AM)
    assert "off route" in best.why
    assert "from the return" in best.why


def test_no_candidates_returns_a_clean_pair_of_nones():
    best, fallback = pick([], HOTEL, RETURN, FIVE_AM)
    assert best is None and fallback is None


def test_untagged_hours_ranks_below_a_confirmed_24_hour_station():
    ranked = rank(stations(), HOTEL, RETURN, FIVE_AM)
    confirmed = [c for c in ranked if c.open_state is True]
    unknown = [c for c in ranked if c.open_state is None]
    if confirmed and unknown:
        assert max(c.score for c in confirmed) > max(c.score for c in unknown)


def test_the_winner_beats_a_neighbour_on_speed_not_price():
    # The ARCO and the Shell sit across the street from each other with a real
    # price gap between them, but nothing here knows that. OSM carries no
    # prices. The ARCO wins on the large brand heuristic, and the price being
    # better too is a coincidence worth not mistaking for a feature.
    ranked = rank(stations(), HOTEL, RETURN, FIVE_AM)
    top, second = ranked[0], ranked[1]
    assert top.station.label == "ARCO" and second.station.label == "Shell"
    assert abs(top.detour_minutes - second.detour_minutes) < 0.5
    assert top.station.is_fast_brand and not second.station.is_fast_brand


def test_the_minimum_distance_floor_does_not_evict_a_good_stop():
    # The floor is only meant to skip the pump inside the airport loop. A
    # station a mile or two out on the route must survive it.
    ranked = rank(stations(), HOTEL, RETURN, FIVE_AM)
    assert ranked, "the floor should not empty the list"
    assert min(c.km_from_return for c in ranked) < 3.0
