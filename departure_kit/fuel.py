"""Choosing one fuel stop between where you are and where the car goes back.

Design notes, because the obvious version of this is wrong.

Not price. The people this is for expense their fuel and do not have time to
hunt for a cheaper pump at four in the morning. Optimising for price sends you
off route to save four dollars, which is the opposite of useful. OpenStreetMap
does not carry prices anyway, so the constraint and the data agree.

Not a shortlist. Two options is still a decision, and a decision on unfamiliar
roads in the dark is the thing you are trying to buy your way out of. This
returns one station and one named fallback for when the first is closed or the
pumps are down.

What it ranks on, in order: is it actually on the way, is it open at that hour,
is it close enough to the return that the gauge still reads full, and is it a
brand with enough pumps that you are not queueing behind one person buying
lottery tickets.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Straight line distance times this approximates road distance. Standard
# detour index for US urban arterials.
ROAD_FACTOR = 1.3

EARTH_RADIUS_KM = 6371.0

# Detour below this is treated as free. The detour figure comes from a
# straight line approximation with more error in it than a minute or two, so
# ranking a two minute difference above a known brand is false precision
# deciding the answer. Real San Diego data made this obvious: an untagged
# station 0.1 minutes off route beat a large 24 hour brand 2 minutes off route,
# and the difference between those two numbers is inside the noise.
FREE_DETOUR_MINUTES = 3.0

# amenity=fuel includes propane and LPG dealers you cannot put petrol in.
NOT_A_PETROL_STATION = ("propane", "lpg", "cng", "hydrogen", "ez pz")

# Brands that are reliably large, well lit and quick to get in and out of.
# This is a speed heuristic, not an endorsement, and not about price.
FAST_BRANDS = {
    "quiktrip", "qt", "buc-ee's", "wawa", "sheetz", "racetrac", "pilot",
    "love's", "flying j", "costco", "sam's club", "arco", "circle k",
    "7-eleven", "speedway", "casey's", "kwik trip", "maverik",
}


@dataclass
class Station:
    osm_id: str
    name: str
    lat: float
    lon: float
    brand: str = ""
    opening_hours: str = ""
    tags: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        return self.name or self.brand or "Unnamed station"

    @property
    def street(self) -> str:
        t = self.tags
        parts = [t.get("addr:housenumber", ""), t.get("addr:street", "")]
        return " ".join(p for p in parts if p).strip()

    @property
    def is_fast_brand(self) -> bool:
        haystack = f"{self.brand} {self.name}".lower()
        return any(b in haystack for b in FAST_BRANDS)

    @property
    def is_anonymous(self) -> bool:
        """No name and no brand. You cannot tell from the road what it is."""
        return not (self.name.strip() or self.brand.strip())

    @property
    def sells_petrol(self) -> bool:
        """Filter out propane and LPG dealers, which share amenity=fuel."""
        haystack = f"{self.brand} {self.name}".lower()
        if any(w in haystack for w in NOT_A_PETROL_STATION):
            return False
        fuels = {k for k in self.tags if k.startswith("fuel:")}
        if fuels and not (fuels - {"fuel:lpg", "fuel:cng", "fuel:propane"}):
            return False
        return True


@dataclass
class Candidate:
    station: Station
    detour_minutes: float
    km_from_return: float
    open_state: bool | None  # True, False, or None for unknown
    score: float
    why: str


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def detour_km(origin, station, dest) -> float:
    """Extra distance from routing through the station rather than straight there.

    A straight line approximation. It cannot know about a median you cannot
    cross or a ramp that only goes one way, which is why the result is a
    suggestion the driver still sees on a map before committing.
    """
    direct = haversine_km(origin, dest)
    via = haversine_km(origin, station) + haversine_km(station, dest)
    return max(0.0, (via - direct) * ROAD_FACTOR)


_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})")
_DAYS = ["mo", "tu", "we", "th", "fr", "sa", "su"]


def is_open_at(opening_hours: str, when: datetime) -> bool | None:
    """Evaluate a subset of the OSM opening_hours syntax.

    Returns None rather than guessing when the string uses syntax this does
    not handle. An unknown is ranked below a known 24/7 but is not discarded,
    because most stations near an airport genuinely are open and simply have
    no hours tagged.
    """
    if not opening_hours:
        return None
    text = opening_hours.strip().lower()
    if text in ("24/7", "mo-su 00:00-24:00", "24 hours"):
        return True

    day = _DAYS[when.weekday()]
    for rule in text.split(";"):
        rule = rule.strip()
        if not rule:
            continue
        times = _TIME_RE.search(rule)
        if not times:
            continue
        day_part = rule[: times.start()].strip()
        if day_part and not _day_matches(day_part, day):
            continue
        h1, m1, h2, m2 = (int(g) for g in times.groups())
        start = h1 * 60 + m1
        end = h2 * 60 + m2
        now = when.hour * 60 + when.minute
        if end <= start:  # wraps past midnight
            if now >= start or now < end:
                return True
        elif start <= now < end:
            return True
    return False if _TIME_RE.search(text) else None


def _day_matches(day_part: str, day: str) -> bool:
    for token in day_part.replace(" ", "").split(","):
        if "-" in token:
            a, b = token.split("-", 1)
            if a in _DAYS and b in _DAYS:
                i, j, k = _DAYS.index(a), _DAYS.index(b), _DAYS.index(day)
                if i <= j and i <= k <= j:
                    return True
                if i > j and (k >= i or k <= j):  # wraps, eg Sa-Su
                    return True
        elif token == day:
            return True
    return False


def build_query(origin, dest, pad_km: float = 3.0) -> str:
    """Overpass QL for fuel stations in a box around the route."""
    lats = sorted([origin[0], dest[0]])
    lons = sorted([origin[1], dest[1]])
    dlat = pad_km / 111.0
    dlon = pad_km / (111.0 * max(0.1, math.cos(math.radians(sum(lats) / 2))))
    bbox = (lats[0] - dlat, lons[0] - dlon, lats[1] + dlat, lons[1] + dlon)
    return (
        "[out:json][timeout:25];"
        f'(node["amenity"="fuel"]({bbox[0]:.5f},{bbox[1]:.5f},{bbox[2]:.5f},{bbox[3]:.5f});'
        f'way["amenity"="fuel"]({bbox[0]:.5f},{bbox[1]:.5f},{bbox[2]:.5f},{bbox[3]:.5f}););'
        "out center tags;"
    )


def parse_overpass(payload: dict) -> list[Station]:
    stations = []
    for el in payload.get("elements", []):
        tags = el.get("tags", {})
        lat = el.get("lat") or (el.get("center") or {}).get("lat")
        lon = el.get("lon") or (el.get("center") or {}).get("lon")
        if lat is None or lon is None:
            continue
        stations.append(
            Station(
                osm_id=f"{el.get('type', 'node')}/{el.get('id')}",
                name=tags.get("name", ""),
                brand=tags.get("brand", ""),
                lat=float(lat),
                lon=float(lon),
                opening_hours=tags.get("opening_hours", ""),
                tags=tags,
            )
        )
    return stations


def fetch_stations(origin, dest, pad_km: float = 3.0, url: str = OVERPASS_URL):
    """Live call to Overpass. No key, no account, no card.

    Overpass is a volunteer run public endpoint. Be polite: this is one query
    per trip, which is well within any reasonable use.
    """
    data = urlencode({"data": build_query(origin, dest, pad_km)}).encode()
    req = Request(url, data=data, headers={"User-Agent": "travel-departure-kit"})
    with urlopen(req, timeout=30) as resp:
        return parse_overpass(json.loads(resp.read().decode()))


def dedupe(stations: list[Station], metres: float = 120.0) -> list[Station]:
    """Collapse stations mapped more than once.

    OSM regularly carries the same forecourt as both a node and a way, or as
    two nodes a few metres apart. Real data returned two Chevrons 1.1 km from
    the San Diego rental return with identical scores, which is one station
    presented as a choice between itself.
    """
    kept: list[Station] = []
    for st in stations:
        key = (st.brand or st.name).lower()
        if any(
            (k.brand or k.name).lower() == key
            and haversine_km((k.lat, k.lon), (st.lat, st.lon)) * 1000 < metres
            for k in kept
        ):
            continue
        kept.append(st)
    return kept


def rank(
    stations: list[Station],
    origin: tuple[float, float],
    dest: tuple[float, float],
    when: datetime,
    speed_kmh: float = 50.0,
    max_detour_minutes: float = 4.0,
    min_km_from_return: float = 1.0,
    max_km_from_return: float = 25.0,
    avoid: list[str] | None = None,
) -> list[Candidate]:
    """Score and sort. Highest score first."""
    avoid_lower = [a.lower() for a in (avoid or [])]
    out: list[Candidate] = []

    for st in dedupe([s for s in stations if s.sells_petrol]):
        blocked = next(
            (a for a in avoid_lower
             if a in st.osm_id.lower()
             or (a in f"{st.label} {st.street}".lower())),
            None,
        )
        if blocked:
            continue

        d_km = detour_km(origin, (st.lat, st.lon), dest)
        d_min = d_km / speed_kmh * 60
        km_return = haversine_km((st.lat, st.lon), dest) * ROAD_FACTOR
        if d_min > max_detour_minutes:
            continue
        if not (min_km_from_return <= km_return <= max_km_from_return):
            continue

        open_state = is_open_at(st.opening_hours, when)
        if open_state is False:
            continue

        score = 100.0
        # Anything inside the free window is simply "on the way", and brand and
        # hours decide. Past it, distance bites hard.
        if d_min <= FREE_DETOUR_MINUTES:
            reasons = ["on the way"]
        else:
            score -= (d_min - FREE_DETOUR_MINUTES) * 20
            reasons = [f"{d_min:.0f} min off route"]

        if open_state is True:
            score += 25
            reasons.append("confirmed open at that hour")
        else:
            reasons.append("hours not tagged in OSM, worth a glance")

        if st.is_fast_brand:
            score += 15
            reasons.append("large brand, quick in and out")
        if st.is_anonymous:
            # No name and no brand means you cannot spot it from the road in
            # the dark, which is the whole job here.
            score -= 20
            reasons.append("unnamed in OSM, hard to spot")

        # The maximum exists so the gauge still reads full at the counter:
        # fill up twenty miles out and it visibly is not. The minimum is a
        # different thing and a smaller one. It only keeps you out of the
        # scrum of other renters at the very last pump before the lot. It is
        # deliberately low, because a real trap is a named place, not a
        # radius, and the avoid list is the tool for that.
        score -= max(0.0, km_return - min_km_from_return) * 0.4
        reasons.append(f"{km_return:.0f} km from the return")

        out.append(
            Candidate(st, d_min, km_return, open_state, score, ", ".join(reasons))
        )

    return sorted(out, key=lambda c: c.score, reverse=True)


def pick(stations, origin, dest, when, **kw):
    """Return (best, fallback). Either may be None.

    The fallback is deliberately not the runner up by score alone: it is the
    best candidate that is not the same brand as the winner, because if the
    first one is dark at 4 am the second one of the same chain often is too.
    """
    ranked = rank(stations, origin, dest, when, **kw)
    if not ranked:
        return None, None
    best = ranked[0]
    best_brand = (best.station.brand or best.station.name).lower()
    fallback = next(
        (c for c in ranked[1:]
         if (c.station.brand or c.station.name).lower() != best_brand),
        None,
    )
    return best, fallback
