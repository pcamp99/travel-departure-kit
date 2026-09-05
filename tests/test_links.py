import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from departure_kit.links import Place, google_maps_route, waze_legs

HOTEL = Place("Hotel", "1515 Hotel Cir S, San Diego, CA 92108", 32.758335, -117.176866,
              "ChIJ6eW7gNOq3oARkKVn74JL28w")
FUEL = Place("ARCO", "3860 Old Town Ave, San Diego, CA 92110", 32.748473, -117.193225,
             "ChIJEzC5miCr3oARAU01dySzfPk")
RETURN = Place("Rental Car Center", "3355 Admiral Boland Way, San Diego, CA 92101",
               32.73618, -117.179286, "ChIJ4ZttTzGr3oARClLTsb4lxIQ")


def test_route_carries_the_stop_and_all_place_ids():
    url = google_maps_route(HOTEL, RETURN, [FUEL])
    assert "waypoints=3860" in url
    assert f"waypoint_place_ids={FUEL.place_id}" in url
    assert f"destination_place_id={RETURN.place_id}" in url
    assert url.startswith("https://www.google.com/maps/dir/?api=1")


def test_addresses_are_url_encoded():
    url = google_maps_route(HOTEL, RETURN)
    assert " " not in url
    assert "1515+Hotel+Cir+S" in url


def test_too_many_stops_raises_rather_than_dropping_them_silently():
    extra = [FUEL, FUEL, FUEL, FUEL]
    with pytest.raises(ValueError, match="ignores more than"):
        google_maps_route(HOTEL, RETURN, extra)


def test_waze_returns_one_link_per_leg_excluding_the_origin():
    legs = waze_legs(HOTEL, RETURN, [FUEL])
    assert len(legs) == 2
    assert legs[0][0] == "ARCO"
    assert legs[1][0] == "Rental Car Center"
    assert "32.748473,-117.193225" in legs[0][1]
    assert all(url.endswith("&navigate=yes") for _, url in legs)


def test_waze_without_coordinates_fails_loudly():
    nocoords = Place("Nowhere", "somewhere")
    with pytest.raises(ValueError, match="lat and lon"):
        waze_legs(HOTEL, nocoords)


def test_omitting_the_origin_starts_from_the_device_location():
    url = google_maps_route(None, RETURN, [FUEL])
    assert "origin=" not in url
    assert "destination=3355" in url
    assert "waypoints=3860" in url


def test_a_dynamic_origin_still_carries_the_fuel_stop():
    # The stop has to survive, or a link generated the morning of quietly
    # drops the one thing the tool exists to add.
    assert "waypoints=" in google_maps_route(None, RETURN, [FUEL])


def test_waze_was_always_dynamic():
    # Waze deep links have no origin parameter at all, so every leg has
    # always started from wherever the phone is.
    for _, url in waze_legs(HOTEL, RETURN, [FUEL]):
        assert "origin" not in url
        assert "ll=" in url
