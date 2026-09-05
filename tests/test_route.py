import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from departure_kit.route import RoutingFailed, build_url, parse_route

HOTEL = (32.758335, -117.176866)
FUEL = (32.748473, -117.193225)
RETURN = (32.736180, -117.179286)


def test_osrm_wants_lon_lat_which_is_the_reverse_of_everywhere_else():
    # The single most common way to get a nonsense route out of OSRM.
    url = build_url([HOTEL, RETURN])
    assert "-117.176866,32.758335" in url
    assert "32.758335,-117.176866" not in url


def test_waypoints_are_ordered_and_separated_correctly():
    url = build_url([HOTEL, FUEL, RETURN])
    assert url.count(";") == 2
    assert url.index("-117.193225") > url.index("-117.176866")
    assert url.index("-117.179286") > url.index("-117.193225")


def test_a_single_point_is_not_a_route():
    with pytest.raises(RoutingFailed, match="origin and a destination"):
        build_url([HOTEL])


def test_parses_total_and_per_leg_minutes():
    payload = {"code": "Ok", "routes": [{"duration": 1140.0, "legs": [
        {"duration": 260.0}, {"duration": 880.0}]}]}
    total, legs = parse_route(payload)
    assert total == 19
    assert legs == [4, 15]


def test_leg_split_is_what_feeds_drive_to_fuel():
    # The first leg is how long until the fuel stop, which is what the
    # timeline needs to place that step at the right clock time.
    payload = {"code": "Ok", "routes": [{"duration": 1140.0, "legs": [
        {"duration": 260.0}, {"duration": 880.0}]}]}
    _, legs = parse_route(payload)
    assert legs[0] == 4


def test_a_no_route_response_raises_rather_than_returning_zero():
    # Returning zero here would produce a plan telling you to leave as the
    # aircraft doors close.
    with pytest.raises(RoutingFailed, match="NoRoute"):
        parse_route({"code": "NoRoute", "message": "no route found"})


def test_an_empty_routes_list_raises():
    with pytest.raises(RoutingFailed, match="no route"):
        parse_route({"code": "Ok", "routes": []})
