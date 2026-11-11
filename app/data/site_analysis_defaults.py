"""
Thresholds used to classify a site from OpenStreetMap + elevation data.

See ``app.application.site_analysis``.

These are documented modelling assumptions, not measured constants — the user can always override
the resulting terrain/environmental-sensitivity/context in the UI, exactly as with the manual
project parameters they replace. Keeping them here (rather than buried in classification code)
makes them one place to defend, cite or recalibrate.
"""

from __future__ import annotations

from typing import Dict

# ---------------------------------------------------------------------------
# Terrain, from the grid's steepest adjacent-point grade (%).
# ---------------------------------------------------------------------------
# AASHTO's Green Book (A Policy on Geometric Design of Highways and Streets) describes terrain
# qualitatively by how much it constrains alignment and sight distance, without one universal
# numeric cutoff. The percent-grade bands below are the commonly cited approximation of that
# description used across transportation-engineering references, and match the terrain classes
# already in this app's UI (Flat / Rolling / Mountainous, see app/data/adjustment_rules.py).
TERRAIN_FLAT_MAX_GRADE_PCT = 3.0        # <= this  -> "Flat"
TERRAIN_ROLLING_MAX_GRADE_PCT = 8.0      # <= this (and > flat) -> "Rolling"; above -> "Mountainous"

# ---------------------------------------------------------------------------
# Road classification (OSM `highway` tag -> a design-relevance rank).
# ---------------------------------------------------------------------------
# Ways below MIN_MAJOR_ROAD_RANK (service roads, tracks, footpaths, cycleways, ...) are excluded
# from context inference: they are not the crossing roads an interchange is designed around.
ROAD_CLASS_RANK: Dict[str, int] = {
    "motorway": 4, "motorway_link": 4,
    "trunk": 4, "trunk_link": 4,
    "primary": 3, "primary_link": 3,
    "secondary": 2, "secondary_link": 2,
    "tertiary": 1, "tertiary_link": 1,
}
MIN_MAJOR_ROAD_RANK = 1  # tertiary and above
HIGHWAY_RANK = 4         # motorway / trunk -- the "highway" side of every context

# Roads are grouped into corridors by direction; two ways within this many degrees of each other
# (mod 180 deg, since a road has no inherent direction) are treated as the same corridor.
CORRIDOR_BEARING_TOLERANCE_DEG = 30.0

# ---------------------------------------------------------------------------
# Environmental sensitivity.
# ---------------------------------------------------------------------------
# Any OSM protected-area / nature-reserve feature within the search radius -> "Critical":
# permitting is assumed to dominate regardless of anything else found.
# A water feature closer than this to the site centre -> "High" (plausible wetland/crossing risk).
WATER_HIGH_SENSITIVITY_DISTANCE_M = 150.0
# Residential land covering more than this share of the search circle -> "Medium" (utility
# relocation, noise mitigation, more right-of-way negotiation than open land).
RESIDENTIAL_MEDIUM_SENSITIVITY_SHARE = 0.15

# ---------------------------------------------------------------------------
# Right-of-way / demolition cost.
# ---------------------------------------------------------------------------
# No authoritative single source for this (it varies hugely by country and by site) -- a
# placeholder the user should calibrate against local land/demolition cost data before relying on
# the estimate for anything beyond a rough order of magnitude.
DEFAULT_DEMOLITION_COST_PER_SQM_USD = 150.0

# ---------------------------------------------------------------------------
# Site sampling defaults.
# ---------------------------------------------------------------------------
DEFAULT_RADIUS_M = 500.0
DEFAULT_ELEVATION_GRID_N = 5  # 5x5 = 25 points, one Open Topo Data request

# ---------------------------------------------------------------------------
# Load limits for a public deployment.
# ---------------------------------------------------------------------------
# Site requests in progress at once (both /api/site routes together). The API has one worker whose
# sync routes share 40 threads; 4 leaves the rest for every other route and the health check.
SITE_REQUEST_SLOTS = 4
# Time one site request may spend on outbound calls, retries included. Well under nginx's 120 s
# proxy timeout and Cloudflare's 100 s, so the planner gets a clear 503 rather than a gateway error.
SITE_REQUEST_DEADLINE_S = 40.0
# Overpass calls in flight at once, over all mirrors. Each public Overpass server gives a client IP
# 2 query slots and answers 429 beyond them, so the client also holds at most 2 per mirror (see
# SLOTS_PER_ENDPOINT in overpass.py). The cap is that times the two mirrors plus room for the OSM
# API fallback: its tile requests (3 at a time) need slots while hung mirrors still hold theirs.
OVERPASS_MAX_CONCURRENT = 6
# Every attempt counts, hedges and retries included, and a busy day can need two or three
# attempts per lookup. overpass-api.de's usage policy asks for well under 10,000 queries a day,
# and the load is spread over two mirrors; a cached 100 m cell costs nothing.
OVERPASS_MAX_PER_DAY = 1000
# The public Open Topo Data API allows 1 call per second and 1000 calls a day per client;
# 800 leaves a margin so its own limit is never what stops us.
ELEVATION_MIN_INTERVAL_S = 1.0
ELEVATION_MAX_PER_DAY = 800
# Open-Meteo, the elevation fallback, allows 10,000 non-commercial calls a day.
OPEN_METEO_MAX_PER_DAY = 2000
# Each visitor's daily share of new lookups, per service (so up to 40 Overpass and 40 elevation
# lookups; only a lookup's first call is charged, not the mirrors, retries or fallback it needed).
# Far more than a planner exploring sites needs once cache hits (free) are counted out, and small
# enough that one visitor cannot spend the whole Overpass budget.
CLIENT_MAX_OUTBOUND_PER_DAY = 40
# Nodes accepted in OSM data the browser fetched itself (when this server could not reach Overpass).
# A dense city centre at the largest radius has about 100,000; the right-of-way estimate already
# skips any building over MAX_BUILDING_NODES.
MAX_CLIENT_OSM_NODES = 200_000
# Map features returned for display. Buildings make up most of a dense cell and give way first;
# the analysis itself always uses every feature.
MAX_MAP_FEATURES = 5000
# Buildings with more vertices than this are left out of the right-of-way estimate. Real building
# outlines rarely come near it (OSM's own cap is 2000 per way), while repairing a self-intersecting
# outline costs seconds of CPU at that size.
MAX_BUILDING_NODES = 500


def terrain_class(max_grade_pct: float) -> str:
    if max_grade_pct <= TERRAIN_FLAT_MAX_GRADE_PCT:
        return "Flat"
    if max_grade_pct <= TERRAIN_ROLLING_MAX_GRADE_PCT:
        return "Rolling"
    return "Mountainous"


def road_rank(tags: Dict[str, str]) -> int:
    """Design-relevance rank of a way's `highway` tag; 0 if unranked or missing."""
    return ROAD_CLASS_RANK.get(tags.get("highway", ""), 0)


CONTEXT_SYSTEM = "System (Highway + Highway)"
CONTEXT_SERVICE = "Service (Highway + Urban)"
CONTEXT_TTYPE = "T-Type (3 Directions)"
# Used when too few distinct road corridors were found to classify with any confidence -- the
# most common real-world case, but always paired with a low-confidence note (see site_analysis.py).
DEFAULT_CONTEXT_FALLBACK = CONTEXT_SERVICE
