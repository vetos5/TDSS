"""
Infer project parameters (context, terrain, environmental sensitivity, free land) from
OpenStreetMap features and an elevation grid around a clicked map point.

Pure function of already-fetched data — no I/O here, so it is testable with synthetic fixtures
without a network. See ``app/infrastructure/gis/`` for how the data is actually fetched, and
``app/data/site_analysis_defaults.py`` for the thresholds used below.

This is a first-pass heuristic classifier, not a survey: it is meant to save the planner from
typing in parameters by hand and to be *checked*, not trusted blindly — every inferred value comes
with the raw numbers behind it and, where the input data was too sparse to be confident, a note
saying so. The user can always override any of it, exactly as they could before this existed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from app.data.site_analysis_defaults import (
    CONTEXT_SERVICE,
    CONTEXT_SYSTEM,
    CONTEXT_TTYPE,
    CORRIDOR_BEARING_TOLERANCE_DEG,
    DEFAULT_CONTEXT_FALLBACK,
    HIGHWAY_RANK,
    MIN_MAJOR_ROAD_RANK,
    RESIDENTIAL_MEDIUM_SENSITIVITY_SHARE,
    WATER_HIGH_SENSITIVITY_DISTANCE_M,
    road_rank,
    terrain_class,
)
from app.infrastructure.gis.elevation import ElevationGrid
from app.infrastructure.gis.overpass import OsmFeatures, OsmWay
from app.infrastructure.gis.projection import LocalOrigin, haversine_m, to_local


@dataclass(frozen=True)
class RoadCorridor:
    """One or more OSM ways travelling roughly the same direction near the site."""

    bearing_deg: float  # 0-180, direction is meaningless for a two-way road
    rank: int           # highest ROAD_CLASS_RANK among the ways in this corridor
    way_ids: list[int]


@dataclass(frozen=True)
class SiteAnalysis:
    context: str
    context_confident: bool
    corridors: list[RoadCorridor]

    terrain: str
    max_grade_pct: float | None       # None if the elevation grid had no usable data

    env_sensitivity: str
    nearest_water_m: float | None     # None if no water feature was found at all
    residential_share: float

    land_limit_ha: float
    building_count: int
    building_area_m2: float
    water_area_m2: float

    notes: list[str] = field(default_factory=list)


# ── Context: road corridors ──────────────────────────────────────────────────

def _way_bearing_deg(way: OsmWay) -> float | None:
    """Bearing of a way's first-to-last point, folded into [0, 180) (a road has no direction)."""
    if len(way.coords) < 2:
        return None
    (lat1, lon1), (lat2, lon2) = way.coords[0], way.coords[-1]
    if (lat1, lon1) == (lat2, lon2):
        return None
    origin = LocalOrigin(lat=lat1, lon=lon1)
    x, y = to_local(lat2, lon2, origin)
    return math.degrees(math.atan2(x, y)) % 180.0


def _bearing_gap(a: float, b: float) -> float:
    """Smallest difference between two [0, 180) bearings, accounting for the wrap-around."""
    d = abs(a - b) % 180.0
    return min(d, 180.0 - d)


def group_corridors(roads: list[OsmWay]) -> list[RoadCorridor]:
    """Group major roads into direction corridors (see CORRIDOR_BEARING_TOLERANCE_DEG)."""
    majors = [
        (way, road_rank(way.tags)) for way in roads if road_rank(way.tags) >= MIN_MAJOR_ROAD_RANK
    ]
    bearings = [(way, rank, _way_bearing_deg(way)) for way, rank in majors]
    bearings = [(way, rank, b) for way, rank, b in bearings if b is not None]

    corridors: list[dict] = []  # {"bearings": [...], "rank": int, "ids": [...]}
    for way, rank, b in bearings:
        match = next(
            (c for c in corridors if _bearing_gap(b, sum(c["bearings"]) / len(c["bearings"]))
             <= CORRIDOR_BEARING_TOLERANCE_DEG),
            None,
        )
        if match is None:
            corridors.append({"bearings": [b], "rank": rank, "ids": [way.id]})
        else:
            match["bearings"].append(b)
            match["rank"] = max(match["rank"], rank)
            match["ids"].append(way.id)

    return [
        RoadCorridor(
            bearing_deg=sum(c["bearings"]) / len(c["bearings"]), rank=c["rank"], way_ids=c["ids"]
        )
        for c in corridors
    ]


def classify_context(corridors: list[RoadCorridor]) -> tuple[str, bool, list[str]]:
    """Returns (context, confident, notes). Confident means >=2 clearly distinct road corridors."""
    ranks = sorted((c.rank for c in corridors), reverse=True)
    n = len(corridors)

    if n >= 3:
        return CONTEXT_TTYPE, True, []
    if n == 2:
        best, second = ranks[0], ranks[1]
        if best >= HIGHWAY_RANK and second >= HIGHWAY_RANK:
            return CONTEXT_SYSTEM, True, []
        if best >= HIGHWAY_RANK:
            return CONTEXT_SERVICE, True, []
        return (
            CONTEXT_SERVICE,
            False,
            ["Two road corridors found, but neither reaches motorway/trunk class; "
             "context guessed as the most common case -- confirm manually."],
        )
    if n == 1:
        return (
            DEFAULT_CONTEXT_FALLBACK,
            False,
            ["Only one major road corridor found near this point; a junction needs at least two -- "
             "confirm the context manually."],
        )
    return (
        DEFAULT_CONTEXT_FALLBACK,
        False,
        ["No major roads (tertiary or above) found within the search radius; "
         "confirm the context manually or widen the radius."],
    )


# ── Terrain: elevation grid ──────────────────────────────────────────────────

def max_grade_pct(grid: ElevationGrid) -> float | None:
    """
    Steepest grade (%) between any two grid points adjacent in the same row or column.

    None where fewer than two adjacent points have a known elevation (e.g. a grid entirely
    outside SRTM coverage) -- callers should treat that as "unknown", not "flat".
    """
    n = grid.n
    step_m = (2 * grid.radius_m / (n - 1)) if n > 1 else 0.0
    if step_m <= 0:
        return None

    grades = []
    for row in range(n):
        for col in range(n):
            i = row * n + col
            for j in (i + 1 if col + 1 < n else None, i + n if row + 1 < n else None):
                if j is None:
                    continue
                e1, e2 = grid.points[i].elevation_m, grid.points[j].elevation_m
                if e1 is not None and e2 is not None:
                    grades.append(abs(e2 - e1) / step_m * 100.0)
    return max(grades) if grades else None


# ── Environmental sensitivity ────────────────────────────────────────────────

def _nearest_vertex_distance_m(
    origin_lat: float, origin_lon: float, ways: list[OsmWay]
) -> float | None:
    """Distance from (origin_lat, origin_lon) to the closest vertex of any way, or None if empty.

    An approximation of distance-to-feature (nearest vertex, not nearest point on the line/
    polygon boundary) -- adequate for a threshold classification at interchange scale.
    """
    best = None
    for way in ways:
        for lat, lon in way.coords:
            d = haversine_m(origin_lat, origin_lon, lat, lon)
            if best is None or d < best:
                best = d
    return best


def _closed_ring_area_m2(way: OsmWay, origin: LocalOrigin) -> float:
    """Shoelace-formula area of a closed way's ring, in local m^2; 0 if the ring isn't closed."""
    if len(way.coords) < 4 or way.coords[0] != way.coords[-1]:
        return 0.0
    pts = [to_local(lat, lon, origin) for lat, lon in way.coords]
    # pts[1:] is intentionally one shorter (shoelace pairs consecutive vertices); not strict.
    area2 = sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(pts, pts[1:], strict=False))
    return abs(area2) / 2.0


def classify_environment(
    origin_lat: float, origin_lon: float, osm: OsmFeatures, radius_m: float
) -> tuple[str, float | None, float]:
    """Returns (env_sensitivity, nearest_water_m, residential_share)."""
    origin = LocalOrigin(lat=origin_lat, lon=origin_lon)
    nearest_water = _nearest_vertex_distance_m(origin_lat, origin_lon, osm.water)
    residential_area = sum(_closed_ring_area_m2(w, origin) for w in osm.residential)
    circle_area = 3.141592653589793 * radius_m**2
    residential_share = min(residential_area / circle_area, 1.0) if circle_area > 0 else 0.0

    if osm.protected:
        return "Critical", nearest_water, residential_share
    if nearest_water is not None and nearest_water < WATER_HIGH_SENSITIVITY_DISTANCE_M:
        return "High", nearest_water, residential_share
    if residential_share > RESIDENTIAL_MEDIUM_SENSITIVITY_SHARE:
        return "Medium", nearest_water, residential_share
    return "Low", nearest_water, residential_share


# ── Free land ─────────────────────────────────────────────────────────────────

def free_land_ha(
    origin_lat: float, origin_lon: float, osm: OsmFeatures, radius_m: float
) -> tuple[float, int, float, float]:
    """Returns (free_land_ha, building_count, building_area_m2, water_area_m2).

    Approximation: sums each feature's full polygon area rather than clipping to the search
    circle, so a building or lake straddling the radius boundary is counted in full -- a
    documented, minor over-subtraction, not a geometric bug.
    """
    origin = LocalOrigin(lat=origin_lat, lon=origin_lon)
    building_area = sum(_closed_ring_area_m2(w, origin) for w in osm.buildings)
    water_area = sum(_closed_ring_area_m2(w, origin) for w in osm.water)
    circle_area = 3.141592653589793 * radius_m**2
    free_m2 = max(circle_area - building_area - water_area, 0.0)
    return free_m2 / 10_000.0, len(osm.buildings), building_area, water_area


# ── Orchestration ─────────────────────────────────────────────────────────────

def analyse_site(
    lat: float, lon: float, osm: OsmFeatures, elevation: ElevationGrid | None, radius_m: float
) -> SiteAnalysis:
    """*elevation* is ``None`` when the elevation services could not be reached: the rest of the
    analysis still stands, and terrain is left to the planner."""
    corridors = group_corridors(osm.roads)
    context, confident, context_notes = classify_context(corridors)

    grade = max_grade_pct(elevation) if elevation is not None else None
    terrain = terrain_class(grade) if grade is not None else "Flat"
    if elevation is None:
        terrain_notes = [
            "Elevation data is unavailable right now; terrain defaulted to Flat -- "
            "confirm manually."
        ]
    elif grade is None:
        terrain_notes = [
            "No usable elevation data in the search grid; terrain defaulted to Flat -- "
            "confirm manually."
        ]
    else:
        terrain_notes = []

    env, nearest_water, residential_share = classify_environment(lat, lon, osm, radius_m)
    land_ha, building_count, building_area, water_area = free_land_ha(lat, lon, osm, radius_m)

    return SiteAnalysis(
        context=context,
        context_confident=confident,
        corridors=corridors,
        terrain=terrain,
        max_grade_pct=grade,
        env_sensitivity=env,
        nearest_water_m=nearest_water,
        residential_share=residential_share,
        land_limit_ha=round(land_ha, 2),
        building_count=building_count,
        building_area_m2=round(building_area, 1),
        water_area_m2=round(water_area, 1),
        notes=[*context_notes, *terrain_notes],
    )
