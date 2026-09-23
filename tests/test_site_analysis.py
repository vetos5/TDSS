"""Site classification from synthetic OSM/elevation fixtures -- no network involved."""

import math

import pytest

from app.application.site_analysis import (
    analyse_site,
    classify_context,
    classify_environment,
    free_land_ha,
    group_corridors,
    max_grade_pct,
)
from app.data.site_analysis_defaults import (
    CONTEXT_SERVICE,
    CONTEXT_SYSTEM,
    CONTEXT_TTYPE,
    DEFAULT_CONTEXT_FALLBACK,
)
from app.infrastructure.gis.elevation import ElevationGrid, ElevationPoint
from app.infrastructure.gis.overpass import OsmFeatures, OsmWay
from app.infrastructure.gis.projection import LocalOrigin, to_latlon

KYIV = LocalOrigin(lat=50.4501, lon=30.5234)


def way(way_id, tags, local_coords):
    """A way from a list of (x, y) local-metre offsets from KYIV, converted to (lat, lon)."""
    return OsmWay(way_id, tags, [to_latlon(x, y, KYIV) for x, y in local_coords])


def straight(way_id, tags, angle_deg, length=400):
    """A straight way of *length* metres through the origin at compass angle_deg."""
    dx, dy = length * math.sin(math.radians(angle_deg)), length * math.cos(math.radians(angle_deg))
    return way(way_id, tags, [(-dx, -dy), (dx, dy)])


def features(roads=(), buildings=(), water=(), protected=(), residential=()):
    return OsmFeatures(
        list(roads), list(buildings), list(water), list(protected), list(residential)
    )


def flat_grid(elevation=100.0, n=5, radius_m=500.0):
    return ElevationGrid(KYIV, radius_m, n, [ElevationPoint(0, 0, elevation) for _ in range(n * n)])


# ── Corridor grouping ─────────────────────────────────────────────────────────

def test_two_perpendicular_motorways_form_two_corridors():
    roads = [straight(1, {"highway": "motorway"}, 0), straight(2, {"highway": "motorway"}, 90)]
    corridors = group_corridors(roads)
    assert len(corridors) == 2
    assert {round(c.bearing_deg) for c in corridors} == {0, 90}


def test_ways_within_tolerance_merge_into_one_corridor():
    roads = [straight(1, {"highway": "motorway"}, 0), straight(2, {"highway": "motorway"}, 10)]
    corridors = group_corridors(roads)
    assert len(corridors) == 1
    assert corridors[0].way_ids == [1, 2]


def test_near_opposite_bearings_are_the_same_corridor():
    # 0 deg and 178 deg are both "roughly north-south" once folded into [0, 180).
    roads = [straight(1, {"highway": "motorway"}, 0), straight(2, {"highway": "motorway"}, 178)]
    assert len(group_corridors(roads)) == 1


def test_minor_roads_are_excluded():
    roads = [
        straight(1, {"highway": "motorway"}, 0),
        straight(2, {"highway": "service"}, 90),
        straight(3, {"highway": "footway"}, 45),
    ]
    corridors = group_corridors(roads)
    assert len(corridors) == 1


def test_corridor_rank_is_the_highest_of_its_ways():
    roads = [straight(1, {"highway": "tertiary"}, 0), straight(2, {"highway": "motorway"}, 5)]
    corridors = group_corridors(roads)
    assert len(corridors) == 1 and corridors[0].rank == 4


def test_no_roads_gives_no_corridors():
    assert group_corridors([]) == []


# ── Context classification ────────────────────────────────────────────────────

def test_three_corridors_is_t_type():
    roads = [straight(i, {"highway": "primary"}, deg) for i, deg in enumerate([0, 60, 120])]
    context, confident, notes = classify_context(group_corridors(roads))
    assert context == CONTEXT_TTYPE and confident and not notes


def test_two_motorways_is_system():
    roads = [straight(1, {"highway": "motorway"}, 0), straight(2, {"highway": "trunk"}, 90)]
    context, confident, notes = classify_context(group_corridors(roads))
    assert context == CONTEXT_SYSTEM and confident


def test_motorway_and_secondary_is_service():
    roads = [straight(1, {"highway": "motorway"}, 0), straight(2, {"highway": "secondary"}, 90)]
    context, confident, notes = classify_context(group_corridors(roads))
    assert context == CONTEXT_SERVICE and confident


def test_two_lower_class_roads_is_low_confidence_service():
    roads = [straight(1, {"highway": "primary"}, 0), straight(2, {"highway": "tertiary"}, 90)]
    context, confident, notes = classify_context(group_corridors(roads))
    assert context == CONTEXT_SERVICE and not confident and notes


def test_single_corridor_is_low_confidence_fallback():
    corridors = group_corridors([straight(1, {"highway": "motorway"}, 0)])
    context, confident, notes = classify_context(corridors)
    assert context == DEFAULT_CONTEXT_FALLBACK and not confident and notes


def test_no_corridors_is_low_confidence_fallback():
    context, confident, notes = classify_context([])
    assert context == DEFAULT_CONTEXT_FALLBACK and not confident and notes


# ── Terrain ───────────────────────────────────────────────────────────────────

def test_flat_grid_has_zero_grade():
    assert max_grade_pct(flat_grid()) == 0.0


def test_grade_from_elevation_step():
    # 5x5 grid over a 500 m radius -> 250 m between adjacent points; a 25 m step is 10% grade.
    n = 5
    points = []
    for row in range(n):
        for _col in range(n):
            points.append(ElevationPoint(0, 0, float(row) * 25.0))
    grid = ElevationGrid(KYIV, 500.0, n, points)
    assert max_grade_pct(grid) == pytest.approx(10.0)


def test_missing_elevation_values_are_skipped_not_treated_as_zero():
    grid = flat_grid()
    points = list(grid.points)
    points[0] = ElevationPoint(0, 0, None)
    grid2 = ElevationGrid(grid.origin, grid.radius_m, grid.n, points)
    assert max_grade_pct(grid2) == 0.0  # still flat -- the hole shouldn't fabricate a grade


def test_all_missing_elevations_returns_none():
    grid = ElevationGrid(KYIV, 500.0, 3, [ElevationPoint(0, 0, None) for _ in range(9)])
    assert max_grade_pct(grid) is None


def test_single_point_grid_returns_none():
    assert max_grade_pct(ElevationGrid(KYIV, 500.0, 1, [ElevationPoint(0, 0, 100.0)])) is None


@pytest.mark.parametrize(
    ("grade", "expected"),
    [
        (0.0, "Flat"), (2.9, "Flat"),
        (5.0, "Rolling"), (8.0, "Rolling"),
        (8.1, "Mountainous"), (20.0, "Mountainous"),
    ],
)
def test_analyse_site_terrain_thresholds(grade, expected):
    n = 3
    step_m = 500.0  # for n=3, step = 2*radius/(n-1) = 500
    points = [
        ElevationPoint(0, 0, (row * step_m) * grade / 100.0) for row in range(n) for _ in range(n)
    ]
    grid = ElevationGrid(KYIV, 500.0, n, points)
    result = analyse_site(KYIV.lat, KYIV.lon, features(), grid, 500.0)
    assert result.terrain == expected


def test_no_elevation_data_defaults_to_flat_with_a_note():
    grid = ElevationGrid(KYIV, 500.0, 3, [ElevationPoint(0, 0, None) for _ in range(9)])
    result = analyse_site(KYIV.lat, KYIV.lon, features(), grid, 500.0)
    assert result.terrain == "Flat" and result.max_grade_pct is None
    assert any("elevation" in n.lower() for n in result.notes)


# ── Environmental sensitivity ─────────────────────────────────────────────────

def test_protected_area_present_is_critical():
    protected = [way(1, {"boundary": "protected_area"}, [(0, 0), (1, 1)])]
    env, _, _ = classify_environment(KYIV.lat, KYIV.lon, features(protected=protected), 500.0)
    assert env == "Critical"


def test_nearby_water_is_high():
    water = [way(1, {"natural": "water"}, [(50, 50), (60, 60)])]
    env, dist, _ = classify_environment(KYIV.lat, KYIV.lon, features(water=water), 500.0)
    assert env == "High"
    assert dist == pytest.approx(math.hypot(50, 50), rel=0.01)


def test_distant_water_is_not_high():
    water = [way(1, {"natural": "water"}, [(400, 400), (450, 450)])]
    env, dist, _ = classify_environment(KYIV.lat, KYIV.lon, features(water=water), 500.0)
    assert env != "High"
    assert dist is not None and dist > 150.0


def test_large_residential_share_is_medium():
    # A closed square 400x400 m = 160,000 m^2 against a 500 m-radius circle (~785,000 m^2) is
    # ~20.4%, above the 15% threshold.
    half = 200.0
    ring = [(-half, -half), (half, -half), (half, half), (-half, half), (-half, -half)]
    residential = [way(1, {"landuse": "residential"}, ring)]
    envres = features(residential=residential)
    env, _, share = classify_environment(KYIV.lat, KYIV.lon, envres, 500.0)
    assert env == "Medium" and share > 0.15


def test_nothing_found_is_low():
    env, dist, share = classify_environment(KYIV.lat, KYIV.lon, features(), 500.0)
    assert env == "Low" and dist is None and share == 0.0


def test_protected_beats_water_and_residential():
    water = [way(1, {"natural": "water"}, [(10, 10), (20, 20)])]
    protected = [way(2, {"leisure": "nature_reserve"}, [(0, 0), (1, 1)])]
    both = features(water=water, protected=protected)
    env, _, _ = classify_environment(KYIV.lat, KYIV.lon, both, 500.0)
    assert env == "Critical"


# ── Free land ─────────────────────────────────────────────────────────────────

def test_free_land_with_no_features_is_the_full_circle():
    ha, count, b_area, w_area = free_land_ha(KYIV.lat, KYIV.lon, features(), 500.0)
    assert ha == pytest.approx(math.pi * 500**2 / 10_000, rel=1e-3)
    assert count == 0 and b_area == 0 and w_area == 0


def test_free_land_subtracts_building_area():
    half = 10.0
    ring = [(-half, -half), (half, -half), (half, half), (-half, half), (-half, -half)]
    buildings = [way(1, {"building": "yes"}, ring)]
    ha, count, b_area, _ = free_land_ha(KYIV.lat, KYIV.lon, features(buildings=buildings), 500.0)
    full_ha = math.pi * 500**2 / 10_000
    assert count == 1
    assert b_area == pytest.approx(400.0, rel=1e-2)  # 20m x 20m square
    assert ha < full_ha


def test_open_way_contributes_no_area():
    # An unclosed way (first point != last) should not be treated as a polygon.
    open_way = [way(1, {"building": "yes"}, [(-10, -10), (10, -10), (10, 10)])]
    ha, count, b_area, _ = free_land_ha(KYIV.lat, KYIV.lon, features(buildings=open_way), 500.0)
    assert b_area == 0.0


def test_free_land_never_goes_negative():
    # A building "area" larger than the whole search circle shouldn't produce negative free land.
    half = 2000.0
    ring = [(-half, -half), (half, -half), (half, half), (-half, half), (-half, -half)]
    buildings = [way(1, {"building": "yes"}, ring)]
    ha, *_ = free_land_ha(KYIV.lat, KYIV.lon, features(buildings=buildings), 500.0)
    assert ha == 0.0


# ── Full orchestration ────────────────────────────────────────────────────────

def test_analyse_site_end_to_end_realistic_junction():
    roads = [straight(1, {"highway": "motorway"}, 0), straight(2, {"highway": "primary"}, 90)]
    ring = [(100, 100), (150, 100), (150, 150), (100, 150), (100, 100)]
    buildings = [way(3, {"building": "yes"}, ring)]
    osm = features(roads=roads, buildings=buildings)
    result = analyse_site(KYIV.lat, KYIV.lon, osm, flat_grid(), 500.0)
    assert result.context == CONTEXT_SERVICE
    assert result.context_confident
    assert result.terrain == "Flat"
    assert result.env_sensitivity == "Low"
    assert result.building_count == 1
    assert result.land_limit_ha < math.pi * 500**2 / 10_000
    assert result.notes == []
