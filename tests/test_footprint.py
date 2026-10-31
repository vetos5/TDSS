"""Footprint placement (rotation + projection of the existing generators) and right-of-way."""

import math
import random

import pytest

from app.application.footprint import (
    FOOTPRINT_GENERATORS,
    _building_polygon,
    estimate_right_of_way,
    is_footprint_available,
    place_footprint,
)
from app.data.site_analysis_defaults import MAX_BUILDING_NODES
from app.domain.geometry import METRES_PER_COORD, ControlPoint, RoadNetwork, RoadSegment
from app.infrastructure.gis.overpass import OsmWay
from app.infrastructure.gis.projection import LocalOrigin, bearing, haversine_m, to_latlon

KYIV = (50.4501, 30.5234)

SUPPORTED = ["Cloverleaf", "DDI", "SPUI", "Turbine"]
UNSUPPORTED = ["Stack (4-Level)", "Diamond", "Trumpet", "Directional T"]


class FakeGenerator:
    """A single straight east-west segment of known length, for deterministic geometry tests."""

    def __init__(self, center_lon=0.0, center_lat=0.0, length=200.0, lanes=2, lane_width=4.0):
        self.length = length
        self.lanes = lanes
        self.lane_width = lane_width

    def generate(self) -> RoadNetwork:
        half = (self.length / 2) / METRES_PER_COORD
        network = RoadNetwork()
        network.add_segment(RoadSegment(
            id="fake-ew",
            control_points=[ControlPoint(x=-half, y=0), ControlPoint(x=half, y=0)],
            num_lanes=self.lanes,
            lane_width_meters=self.lane_width,
        ))
        return network


@pytest.fixture
def fake_registered(monkeypatch):
    monkeypatch.setitem(FOOTPRINT_GENERATORS, "Fake", FakeGenerator)


# ── Availability ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", SUPPORTED)
def test_supported_alternatives_are_available(name):
    assert is_footprint_available(name)
    assert place_footprint(name, *KYIV) is not None


@pytest.mark.parametrize("name", UNSUPPORTED)
def test_unsupported_alternatives_are_not_available(name):
    assert not is_footprint_available(name)
    assert place_footprint(name, *KYIV) is None


def test_unknown_name_is_not_available():
    assert not is_footprint_available("Nonsense")
    assert place_footprint("Nonsense", *KYIV) is None


# ── Placement geometry (deterministic, via FakeGenerator) ────────────────────

def test_endpoints_land_the_right_distance_from_origin(fake_registered):
    fp = place_footprint("Fake", *KYIV, length=200.0)
    seg = fp.segments[0]
    for lat, lon in (seg.coords_latlon[0], seg.coords_latlon[-1]):
        assert haversine_m(*KYIV, lat, lon) == pytest.approx(100.0, rel=1e-6)


def test_bearing_zero_points_due_east_and_west(fake_registered):
    # A 2-control-point segment is linearly interpolated (see RoadSegment.generate_centreline),
    # so only the two ENDS of the interpolated line sit at the segment's true length -- points in
    # between are progressively closer to the origin, down to 0 at the midpoint.
    fp = place_footprint("Fake", *KYIV, bearing_rad=0.0, length=200.0)
    coords = fp.segments[0].coords_latlon
    p1, p2 = coords[0], coords[-1]
    bearings = sorted(math.degrees(bearing(*KYIV, lat, lon)) for lat, lon in (p1, p2))
    assert bearings == pytest.approx([90.0, 270.0], abs=0.05)


def test_rotating_90_degrees_points_due_south_and_north(fake_registered):
    fp = place_footprint("Fake", *KYIV, bearing_rad=math.pi / 2, length=200.0)
    coords = fp.segments[0].coords_latlon
    p1, p2 = coords[0], coords[-1]
    bearings = sorted(math.degrees(bearing(*KYIV, lat, lon)) for lat, lon in (p1, p2))
    assert bearings == pytest.approx([0.0, 180.0], abs=0.05)


def test_rotation_preserves_distance_from_origin(fake_registered):
    # Only the segment's two endpoints sit at the full 150 m radius (see the comment above).
    # rel=1e-3 comfortably covers the projection's own documented sub-1% approximation error
    # (see test_gis_projection.py) while still catching a real rotation/distance bug.
    for deg in [0, 37, 90, 180, 271]:
        fp = place_footprint("Fake", *KYIV, bearing_rad=math.radians(deg), length=300.0)
        coords = fp.segments[0].coords_latlon
        for lat, lon in (coords[0], coords[-1]):
            assert haversine_m(*KYIV, lat, lon) == pytest.approx(150.0, rel=1e-3)


def test_origin_moves_the_whole_footprint():
    fp_kyiv = place_footprint("Cloverleaf", 50.4501, 30.5234)
    fp_lviv = place_footprint("Cloverleaf", 49.8397, 24.0297)
    assert fp_kyiv.segments[0].coords_latlon != fp_lviv.segments[0].coords_latlon
    # Both should still be tightly clustered around their own origin.
    for fp, origin in [(fp_kyiv, (50.4501, 30.5234)), (fp_lviv, (49.8397, 24.0297))]:
        for seg in fp.segments:
            for lat, lon in seg.coords_latlon:
                assert haversine_m(*origin, lat, lon) < 1000.0


def test_polygon_has_positive_area_and_reflects_road_width(fake_registered):
    narrow = place_footprint("Fake", *KYIV, length=200.0, lanes=1, lane_width=3.0)
    wide = place_footprint("Fake", *KYIV, length=200.0, lanes=4, lane_width=3.0)
    assert narrow.polygon.area > 0
    assert wide.polygon.area > narrow.polygon.area


# ── Real generators: basic invariants ────────────────────────────────────────

@pytest.mark.parametrize("name", SUPPORTED)
def test_real_generator_segment_count_matches_network(name):
    fp = place_footprint(name, *KYIV)
    network = FOOTPRINT_GENERATORS[name](center_lon=0.0, center_lat=0.0).generate()
    assert len(fp.segments) == len(network.segments)
    assert {s.id for s in fp.segments} == {s.id for s in network.segments}


@pytest.mark.parametrize("name", SUPPORTED)
def test_real_generator_footprint_stays_near_the_site(name):
    fp = place_footprint(name, *KYIV)
    for seg in fp.segments:
        for lat, lon in seg.coords_latlon:
            assert haversine_m(*KYIV, lat, lon) < 2000.0  # generously within a couple km


@pytest.mark.parametrize("name", SUPPORTED)
def test_real_generator_polygon_is_nonempty(name):
    assert place_footprint(name, *KYIV).polygon.area > 0


# ── Right-of-way ──────────────────────────────────────────────────────────────

def square_building(way_id, cx, cy, half, origin):
    ring = [(cx - half, cy - half), (cx + half, cy - half), (cx + half, cy + half),
            (cx - half, cy + half), (cx - half, cy - half)]
    return OsmWay(way_id, {"building": "yes"}, [to_latlon(x, y, origin) for x, y in ring])


def test_building_overlapping_footprint_is_counted(fake_registered):
    fp = place_footprint("Fake", *KYIV, length=200.0, lanes=2, lane_width=4.0)  # road half-width 4m
    origin = LocalOrigin(*KYIV)
    building = square_building(1, 0, 0, 5, origin)  # 10x10 m square straddling the road centre
    row = estimate_right_of_way(fp, [building], demolition_cost_per_sqm=150.0)
    assert row.buildings_affected == 1
    assert row.demolished_area_m2 > 0
    assert row.estimated_cost_usd == pytest.approx(row.demolished_area_m2 * 150.0)


def test_building_far_from_footprint_is_not_counted(fake_registered):
    fp = place_footprint("Fake", *KYIV, length=200.0)
    origin = LocalOrigin(*KYIV)
    building = square_building(1, 500, 500, 5, origin)
    row = estimate_right_of_way(fp, [building], demolition_cost_per_sqm=150.0)
    assert row == estimate_right_of_way(fp, [], demolition_cost_per_sqm=150.0)


def test_no_buildings_gives_zero_row():
    fp = place_footprint("Cloverleaf", *KYIV)
    row = estimate_right_of_way(fp, [], demolition_cost_per_sqm=150.0)
    assert row.buildings_affected == 0
    assert row.demolished_area_m2 == 0.0
    assert row.estimated_cost_usd == 0.0


def test_unclosed_building_way_is_ignored(fake_registered):
    fp = place_footprint("Fake", *KYIV, length=200.0)
    origin = LocalOrigin(*KYIV)
    open_ring = [(-5, -5), (5, -5), (5, 5)]  # not closed
    building = OsmWay(1, {"building": "yes"}, [to_latlon(x, y, origin) for x, y in open_ring])
    row = estimate_right_of_way(fp, [building], demolition_cost_per_sqm=150.0)
    assert row.buildings_affected == 0


def test_multiple_overlapping_buildings_sum(fake_registered):
    fp = place_footprint("Fake", *KYIV, length=200.0, lanes=4, lane_width=4.0)
    origin = LocalOrigin(*KYIV)
    b1 = square_building(1, -20, 0, 3, origin)
    b2 = square_building(2, 20, 0, 3, origin)
    row_both = estimate_right_of_way(fp, [b1, b2], demolition_cost_per_sqm=100.0)
    row_one = estimate_right_of_way(fp, [b1], demolition_cost_per_sqm=100.0)
    assert row_both.buildings_affected == 2
    assert row_both.demolished_area_m2 > row_one.demolished_area_m2


def test_building_over_the_node_cap_is_skipped(fake_registered):
    fp = place_footprint("Fake", *KYIV, length=200.0, lanes=2, lane_width=4.0)
    origin = LocalOrigin(*KYIV)
    # A 10x10 m square straddling the road, traced with more vertices than the cap allows.
    side = MAX_BUILDING_NODES // 4 + 1
    ring = [(-5 + 10 * i / side, -5) for i in range(side)]
    ring += [(5, -5 + 10 * i / side) for i in range(side)]
    ring += [(5 - 10 * i / side, 5) for i in range(side)]
    ring += [(-5, 5 - 10 * i / side) for i in range(side)]
    ring.append(ring[0])
    building = OsmWay(1, {"building": "yes"}, [to_latlon(x, y, origin) for x, y in ring])
    assert len(building.coords) > MAX_BUILDING_NODES
    assert estimate_right_of_way(fp, [building], 150.0).buildings_affected == 0


def _brute_force_row(fp, buildings, cost):
    """The estimate as it was before the bounding-box prefilter: every building, no shortcuts."""
    affected, area = 0, 0.0
    for way in buildings:
        poly = _building_polygon(way, fp.origin)
        if poly is None or poly.is_empty:
            continue
        overlap = poly.intersection(fp.polygon)
        if not overlap.is_empty:
            affected += 1
            area += overlap.area
    return affected, round(area, 1), round(area * cost, 0)


@pytest.mark.parametrize("name", SUPPORTED)
def test_prefilter_does_not_change_the_estimate(name):
    rnd = random.Random(7)
    origin = LocalOrigin(*KYIV)
    fp = place_footprint(name, *KYIV, bearing_rad=0.6)
    buildings = [
        square_building(i, rnd.uniform(-400, 400), rnd.uniform(-400, 400), rnd.uniform(3, 15),
                        origin)
        for i in range(400)
    ]
    row = estimate_right_of_way(fp, buildings, 150.0)
    assert row.buildings_affected > 0
    assert (row.buildings_affected, row.demolished_area_m2, row.estimated_cost_usd) == (
        _brute_force_row(fp, buildings, 150.0)
    )
