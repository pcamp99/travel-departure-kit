"""Drive times from OSRM, the OpenStreetMap routing engine.

Keyless and free, like Overpass and Nominatim. The public demo server is run
by FOSSGIS for the OSM community and its terms are worth respecting rather
than skirting: reasonable non commercial use, no more than one request per
second, a real User-Agent, and attribution for the route. Access can be
withdrawn at any time and there is no uptime guarantee.

Two calls per trip is well inside that. The manual --drive stays supported
precisely because a volunteer service can be down on the morning you need it,
and a departure plan that cannot be produced without a third party being up is
not a plan.

One property that is usually a weakness and happens to be a strength here:
OSRM routes free flow, with no live traffic. For a five in the morning drive
to return a rental car, free flow is roughly what the road actually is.
"""

from __future__ import annotations

import json
from urllib.request import Request, urlopen

OSRM_URL = "https://router.project-osrm.org/route/v1/driving"
USER_AGENT = "travel-departure-kit (https://github.com/travel-departure-kit)"

ATTRIBUTION = "Routing by OSRM. Map data from OpenStreetMap contributors, ODbL."


class RoutingFailed(Exception):
    pass


def build_url(points, base: str = OSRM_URL) -> str:
    """OSRM takes lon,lat pairs, which is the reverse of everything else here.

    That ordering has cost more people more time than any other detail of this
    API. The whole codebase uses (lat, lon); the flip happens only here.
    """
    if len(points) < 2:
        raise RoutingFailed("need at least an origin and a destination")
    coords = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in points)
    return f"{base}/{coords}?overview=false&annotations=duration"


def parse_route(payload: dict) -> tuple[int, list[int]]:
    """Return (total_minutes, per_leg_minutes)."""
    if payload.get("code") != "Ok":
        raise RoutingFailed(f"OSRM said {payload.get('code')}: {payload.get('message')}")
    routes = payload.get("routes") or []
    if not routes:
        raise RoutingFailed("OSRM returned no route")
    route = routes[0]
    legs = [int(round(leg["duration"] / 60)) for leg in route.get("legs", [])]
    total = int(round(route["duration"] / 60))
    return total, legs


def drive_minutes(points, base: str = OSRM_URL) -> tuple[int, list[int]]:
    """Live call. points is a list of (lat, lon), origin first."""
    req = Request(build_url(points, base), headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=25) as resp:
            payload = json.loads(resp.read().decode())
    except RoutingFailed:
        raise
    except Exception as exc:  # network, timeout, malformed body
        raise RoutingFailed(
            f"could not reach the OSRM demo server ({exc}). "
            "Pass --drive with a number of minutes instead."
        ) from exc
    return parse_route(payload)
