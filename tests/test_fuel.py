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
    # Inside the free window the reason reads "on the way" rather than a
    # spurious minute count.
    assert "on the way" in best.why or "off route" in best.why
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


# --- lessons from the first real run against live OSM data -------------------

def test_a_propane_dealer_is_not_a_gas_station():
    # Live San Diego data returned "Ez Pz Propane" under amenity=fuel.
    from departure_kit.fuel import Station
    assert not Station("n/1", "Ez Pz Propane", 32.74, -117.18).sells_petrol
    assert Station("n/2", "ARCO", 32.74, -117.18, brand="ARCO").sells_petrol


def test_an_lpg_only_site_is_excluded_by_its_tags():
    from departure_kit.fuel import Station
    lpg = Station("n/3", "Gas Depot", 32.74, -117.18, tags={"fuel:lpg": "yes"})
    petrol = Station("n/4", "Gas Depot", 32.74, -117.18,
                     tags={"fuel:lpg": "yes", "fuel:diesel": "yes"})
    assert not lpg.sells_petrol
    assert petrol.sells_petrol


def test_the_same_forecourt_mapped_twice_is_collapsed():
    # Live data returned two Chevrons 1.1 km from the SAN return with identical
    # scores, which is one station offered as a choice between itself.
    from departure_kit.fuel import Station, dedupe
    a = Station("node/1", "Chevron", 32.743133, -117.181903, brand="Chevron")
    b = Station("way/2", "Chevron", 32.743200, -117.181950, brand="Chevron")
    far = Station("node/3", "Chevron", 32.760000, -117.200000, brand="Chevron")
    assert len(dedupe([a, b, far])) == 2


def test_a_small_detour_difference_does_not_decide_the_answer():
    # The detour figure is a straight line estimate. Letting 0.1 minutes beat
    # 2 minutes is false precision, and it is what made live data pick an
    # untagged perimeter station over a large 24 hour brand.
    from departure_kit.fuel import Station
    near_anon = Station("n/1", "Chevron", 32.743133, -117.181903, brand="Chevron")
    further_big = Station("n/2", "ARCO", 32.748473, -117.193225, brand="ARCO")
    best, _ = pick([near_anon, further_big], HOTEL, RETURN, FIVE_AM)
    assert best.station.brand == "ARCO"


def test_an_unnamed_station_ranks_below_a_named_one_all_else_equal():
    from departure_kit.fuel import Station
    named = Station("n/1", "Shell", 32.748473, -117.193225, brand="Shell")
    anon = Station("n/2", "", 32.748480, -117.193230)
    ranked = rank([named, anon], HOTEL, RETURN, FIVE_AM)
    assert ranked[0].station.label == "Shell"


# --- the avoid list was inert against live data ------------------------------
# Found by running the real Phoenix corridor: 213 stations returned, and the
# avoid list excluded exactly none of them. These tests use the strings OSM
# actually returns, not strings chosen to match.

def test_an_abbreviated_entry_matches_a_spelled_out_osm_street():
    from departure_kit.fuel import Station, matches_avoid
    shell = Station("node/1", "Shell", 33.44, -112.05,
                    tags={"addr:housenumber": "1515",
                          "addr:street": "East Buckeye Road"})
    # airports.yaml says "E Buckeye Rd". OSM says "East Buckeye Road".
    assert matches_avoid(shell, "E Buckeye Rd")
    assert matches_avoid(shell, "East Buckeye Road")
    assert matches_avoid(shell, "Buckeye")


def test_a_different_street_with_the_same_name_is_not_matched():
    from departure_kit.fuel import Station, matches_avoid
    shell = Station("node/1", "Shell", 33.44, -112.05,
                    tags={"addr:street": "East Buckeye Road"})
    assert not matches_avoid(shell, "W Buckeye Rd")
    assert not matches_avoid(shell, "Buckeye Ln")


def test_tokens_must_be_consecutive_not_merely_present():
    # "E Main St" must not match a station on "W Main St" that happens to sit
    # in an "East Plaza", which a loose subset test would allow.
    from departure_kit.fuel import Station, matches_avoid
    st = Station("node/1", "Shell", 33.44, -112.05,
                 tags={"addr:street": "West Main Street East Plaza"})
    assert not matches_avoid(st, "E Main St")
    assert matches_avoid(st, "W Main St")


def test_an_osm_id_entry_still_matches_literally():
    from departure_kit.fuel import Station, matches_avoid
    st = Station("node/1001", "Shell", 33.44, -112.05)
    assert matches_avoid(st, "node/1001")
    assert not matches_avoid(st, "node/9999")


def test_an_avoid_entry_that_matches_nothing_is_reported():
    # The real damage was silence. A guard that fires on nothing should say so
    # rather than pass for a working one.
    from departure_kit.fuel import Station
    st = Station("node/1", "ARCO", 32.748473, -117.193225, brand="ARCO",
                 tags={"addr:street": "Old Town Ave"})
    unmatched = set()
    rank([st], HOTEL, RETURN, FIVE_AM,
         avoid=["Old Town Ave", "Nowhere Blvd"], unmatched_avoid=unmatched)
    assert unmatched == {"Nowhere Blvd"}


def test_the_abbreviated_entry_actually_removes_the_station_from_ranking():
    # End to end through rank(), which is where the inert guard hid.
    from departure_kit.fuel import Station
    shell = Station("node/1", "Shell", 32.748117, -117.192902, brand="Shell",
                    tags={"addr:street": "East Moore Street"})
    arco = Station("node/2", "ARCO", 32.748473, -117.193225, brand="ARCO",
                   tags={"addr:street": "Old Town Ave"})
    with_guard = rank([shell, arco], HOTEL, RETURN, FIVE_AM, avoid=["E Moore St"])
    assert [c.station.brand for c in with_guard] == ["ARCO"]
