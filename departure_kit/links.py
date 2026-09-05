"""Navigation deep links.

Google Maps URLs take waypoints, so the whole route including the fuel stop
fits in one tappable link. Waze deep links take exactly one destination, so a
route with a stop needs two links. That asymmetry is not a limitation of this
code, it is how the two products work, and pretending otherwise produces a
link that silently drops your fuel stop.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote_plus

GOOGLE_MAPS_BASE = "https://www.google.com/maps/dir/?api=1"
WAZE_BASE = "https://waze.com/ul"

# Google Maps ignores waypoints beyond this on mobile.
MAX_MOBILE_WAYPOINTS = 3


@dataclass
class Place:
    """A point on the route.

    place_id is optional but strongly worth filling in for rental returns.
    An address string search for "airport rental car return" lands people at
    a terminal curb; a place id cannot.
    """

    label: str
    address: str
    lat: float | None = None
    lon: float | None = None
    place_id: str | None = None

    @property
    def latlon(self) -> str:
        if self.lat is None or self.lon is None:
            raise ValueError(f"{self.label}: needs lat and lon for a Waze link")
        return f"{self.lat:.6f},{self.lon:.6f}"


def google_maps_route(
    origin: Place | None, destination: Place, stops: list[Place] | None = None
) -> str:
    """Build a route link. Pass origin=None to start from the device location.

    Omitting the origin makes Google Maps begin wherever the phone is when the
    link is opened, which is a useful safety net for a link generated hours
    earlier. It is only a safety net: the leave time in the plan was computed
    from an assumed origin, so a dynamic start fixes where the blue line
    begins and does nothing about when the alarm went off.
    """
    stops = stops or []
    if len(stops) > MAX_MOBILE_WAYPOINTS:
        raise ValueError(
            f"Google Maps ignores more than {MAX_MOBILE_WAYPOINTS} waypoints on "
            f"mobile; got {len(stops)}. Split the route rather than shipping a "
            "link that quietly drops stops."
        )

    parts = [GOOGLE_MAPS_BASE]
    if origin is not None:
        parts.append(f"origin={quote_plus(origin.address)}")
        if origin.place_id:
            parts.append(f"origin_place_id={origin.place_id}")
    parts.append(f"destination={quote_plus(destination.address)}")
    if destination.place_id:
        parts.append(f"destination_place_id={destination.place_id}")

    if stops:
        parts.append("waypoints=" + "|".join(quote_plus(s.address) for s in stops))
        # Google requires that if any waypoint place id is given, all are, and
        # that they line up positionally with the waypoints.
        if all(s.place_id for s in stops):
            parts.append("waypoint_place_ids=" + "|".join(s.place_id for s in stops))

    parts.append("travelmode=driving")
    return "&".join(parts)


def waze_legs(origin: Place, destination: Place, stops: list[Place] | None = None):
    """Return one Waze link per leg, skipping the origin.

    Waze navigates to a single destination, so a stop means two links: fire
    the first from the hotel, the second while standing at the pump.
    """
    stops = stops or []
    legs = []
    for place in [*stops, destination]:
        legs.append((place.label, f"{WAZE_BASE}?ll={place.latlon}&navigate=yes"))
    return legs
