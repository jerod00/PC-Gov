"""Distance filtering for state/local opportunities.

Texas is treated as always in-radius per company judgment (config.yaml
state_local_states) and never runs through distance math. For the other
states (OK, LA, AR, NM, KS, MO), only the part of the state within
radius_miles of Stephenville, TX actually qualifies, so every opportunity
with resolvable location data gets a real haversine check.

NOTE ON DATA: this ships with a hand-curated set of state centroids (coarse
fallback) and major-city centroids for the six non-TX states. It is NOT a
full county/ZIP gazetteer — city names outside this list fall back to the
state centroid, which is a rough approximation and can misclassify cities
near a state's edge. Before turning on a Phase 2 source, sample its actual
location field format and expand CITY_CENTROIDS accordingly (a free source:
the Census Gazetteer county/place files at census.gov).
"""

import math
from typing import Optional

EARTH_RADIUS_MILES = 3958.8

# Coarse state centroids — used only when a city-level match isn't found.
STATE_CENTROIDS = {
    "OK": (35.4676, -97.5164),   # Oklahoma City
    "LA": (30.9843, -91.9623),   # roughly central LA
    "AR": (34.7465, -92.2896),   # Little Rock
    "NM": (34.5199, -105.8701),  # roughly central NM
    "KS": (38.5266, -96.7265),   # roughly central KS
    "MO": (38.5767, -92.1735),   # Jefferson City
    "TX": (31.9686, -99.9018),   # not used for filtering, kept for completeness
}

# Major-city centroids, biased toward cities close enough to plausibly be
# in-radius so the state-centroid fallback isn't doing all the work for the
# highest-volume bid sources. Expand as Phase 2 sources reveal more cities.
CITY_CENTROIDS = {
    ("Oklahoma City", "OK"): (35.4676, -97.5164),
    ("Tulsa", "OK"): (36.1540, -95.9928),
    ("Lawton", "OK"): (34.6036, -98.3959),
    ("Ardmore", "OK"): (34.1743, -97.1436),
    ("Shawnee", "OK"): (35.3273, -96.9253),
    ("Shreveport", "LA"): (32.5252, -93.7502),
    ("Bossier City", "LA"): (32.5160, -93.7321),
    ("Monroe", "LA"): (32.5093, -92.1193),
    ("Alexandria", "LA"): (31.3113, -92.4451),
    ("Little Rock", "AR"): (34.7465, -92.2896),
    ("Fort Smith", "AR"): (35.3859, -94.3985),
    ("Texarkana", "AR"): (33.4418, -94.0377),
    ("Hot Springs", "AR"): (34.5037, -93.0552),
    ("Clovis", "NM"): (34.4048, -103.2052),
    ("Roswell", "NM"): (33.3943, -104.5230),
    ("Carlsbad", "NM"): (32.4207, -104.2288),
    ("Hobbs", "NM"): (32.7026, -103.1360),
    ("Wichita", "KS"): (37.6872, -97.3301),
    ("Topeka", "KS"): (39.0473, -95.6752),
    ("Salina", "KS"): (38.8403, -97.6114),
    ("Joplin", "MO"): (37.0842, -94.5133),
    ("Springfield", "MO"): (37.2090, -93.2923),
    ("Kansas City", "MO"): (39.0997, -94.5786),
}


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(a))


def resolve_location(city: Optional[str], state: Optional[str]):
    """Best-effort (lat, lon) for a city/state pair. Returns None if nothing
    resolvable — callers should treat that as 'unknown, can't verify radius'
    rather than silently including or excluding it."""
    if city and state and (city, state) in CITY_CENTROIDS:
        return CITY_CENTROIDS[(city, state)]
    if state and state in STATE_CENTROIDS:
        return STATE_CENTROIDS[state]
    return None


def distance_from_home(lat: Optional[float], lon: Optional[float], city: Optional[str],
                        state: Optional[str], home_lat: float, home_lon: float) -> Optional[float]:
    """Distance in miles from home, preferring exact lat/lon when the source
    provided it, falling back to city/state centroid resolution."""
    if lat is not None and lon is not None:
        return haversine_miles(home_lat, home_lon, lat, lon)
    resolved = resolve_location(city, state)
    if resolved is None:
        return None
    return haversine_miles(home_lat, home_lon, resolved[0], resolved[1])


def is_in_scope(state: Optional[str], lat: Optional[float], lon: Optional[float], city: Optional[str],
                 cfg: dict) -> bool:
    """Gate used for state/local sources only (never call this for sam_gov —
    federal is nationwide by design). Texas always passes; other configured
    states must resolve within radius_miles. Unresolvable locations are
    excluded (fail closed) rather than guessed into or out of scope."""
    company = cfg["company"]
    allowed_states = company.get("state_local_states", [])
    if state not in allowed_states:
        return False
    if state == "TX":
        return True
    dist = distance_from_home(lat, lon, city, state, company["home_location"]["lat"], company["home_location"]["lon"])
    if dist is None:
        return False
    return dist <= company.get("radius_miles", 500)
