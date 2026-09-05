"""Turning an address into coordinates, with no key and no account.

Needed because an inferred origin arrives as a free text address off a
calendar event, while the fuel search needs a point to draw a corridor from.

Nominatim is the OpenStreetMap geocoder. It is free and keyless, and it is run
on donated infrastructure with a usage policy that matters: at most one request
per second, and a real User-Agent identifying the application. One lookup per
trip is well inside that. Do not put this in a loop.
"""

from __future__ import annotations

import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "travel-departure-kit (https://github.com/travel-departure-kit)"


class GeocodeFailed(Exception):
    pass


def geocode(address: str, url: str = NOMINATIM_URL) -> tuple[float, float]:
    """Return (lat, lon) for an address, or raise.

    Raises rather than returning None because every caller needs a real point
    and a silent failure here would produce a fuel search around the wrong
    part of the city, which looks like a working answer.
    """
    address = (address or "").strip()
    if not address:
        raise GeocodeFailed("empty address")

    query = urlencode({"q": address, "format": "json", "limit": 1})
    req = Request(f"{url}?{query}", headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=20) as resp:
        results = json.loads(resp.read().decode())

    if not results:
        raise GeocodeFailed(
            f"Nominatim found nothing for {address!r}. Calendar locations are often "
            "a room name or a partial address. Pass --from-latlon instead."
        )
    return float(results[0]["lat"]), float(results[0]["lon"])
