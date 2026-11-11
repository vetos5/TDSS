"""Geometry checks on every interchange generator, in local metres (built at the origin)."""

import math

import pytest
from shapely.geometry import LineString, Point

from app.application.footprint import FOOTPRINT_GENERATORS
from app.data import interchange_geometry as dims
from app.domain.geometry import METRES_PER_COORD
from app.infrastructure.generators import RoundaboutGenerator

ALL = {**FOOTPRINT_GENERATORS, "Roundabout": RoundaboutGenerator}
INTERCHANGES = sorted(FOOTPRINT_GENERATORS)

# Ends closer than this to another road count as joined to it: the drawing is exact, so this only
# absorbs floating-point and spline resampling error.
JOIN_TOLERANCE_M = 0.5
# Ramps must be tangent where they meet a freeway carriageway (sine of the angle between them).
TANGENT_TOLERANCE = 0.02
# The tightest curve anywhere is a 25 m turning roadway; a kink would show as far more curvature.
MAX_CURVATURE = 1 / 20.0


def _layout(name):
    """Segments as (segment, centreline in metres), as RoadSegment resamples them for the map."""
    network = ALL[name](center_lon=0.0, center_lat=0.0).generate()
    return [
        (seg, [(x * METRES_PER_COORD, y * METRES_PER_COORD) for x, y in seg.generate_centreline()])
        for seg in network.segments
    ]


def _heading(p, q):
    return math.atan2(q[1] - p[1], q[0] - p[0])


@pytest.mark.parametrize("name", sorted(ALL))
def test_every_generator_yields_finite_segments(name):
    layout = _layout(name)
    assert len(layout) >= 8
    for seg, pts in layout:
        assert seg.kind in {"mainline", "crossroad", "ramp", "road"}
        assert all(math.isfinite(c) for p in pts for c in p), seg.id
    assert len({seg.id for seg, _ in layout}) == len(layout)


@pytest.mark.parametrize("name", sorted(ALL))
def test_no_centreline_crosses_itself(name):
    for seg, pts in _layout(name):
        assert LineString(pts).is_simple, seg.id


@pytest.mark.parametrize("name", sorted(ALL))
def test_no_kinks(name):
    """Curvature stays within the tightest designed radius all along every centreline."""
    for seg, pts in _layout(name):
        for p, q, r in zip(pts, pts[1:], pts[2:], strict=False):
            turn = abs((_heading(q, r) - _heading(p, q) + math.pi) % (2 * math.pi) - math.pi)
            ds = (math.dist(p, q) + math.dist(q, r)) / 2
            assert turn / ds <= MAX_CURVATURE, f"{seg.id} kinks at {q}"


@pytest.mark.parametrize("name", INTERCHANGES)
def test_extent_is_a_real_interchange_size(name):
    ramps = [p for seg, pts in _layout(name) if seg.kind == "ramp" for p in pts]
    half = max(max(abs(x), abs(y)) for x, y in ramps)
    assert 150 < half < 650, half


@pytest.mark.parametrize("name", INTERCHANGES)
def test_every_ramp_end_meets_a_road(name):
    layout = _layout(name)
    for seg, pts in layout:
        if seg.kind != "ramp":
            continue
        for end in (pts[0], pts[-1]):
            gaps = [
                Point(end).distance(LineString(other_pts))
                - (other.road_width() + seg.road_width()) / 2
                for other, other_pts in layout if other is not seg
            ]
            assert min(gaps) <= JOIN_TOLERANCE_M, f"{seg.id} dangles at {end}"


@pytest.mark.parametrize("name", INTERCHANGES)
def test_ramps_meet_freeways_tangentially(name):
    layout = _layout(name)
    mainlines = [(s, LineString(p)) for s, p in layout if s.kind == "mainline"]
    for seg, pts in layout:
        if seg.kind != "ramp":
            continue
        for end, inner in ((pts[0], pts[1]), (pts[-1], pts[-2])):
            for main, line in mainlines:
                reach = (main.road_width() + seg.road_width()) / 2 + JOIN_TOLERANCE_M
                if Point(end).distance(line) > reach:
                    continue
                along = line.project(Point(end))
                a = line.interpolate(max(along - 1.0, 0.0))
                b = line.interpolate(min(along + 1.0, line.length))
                angle = _heading(inner, end) - _heading((a.x, a.y), (b.x, b.y))
                assert abs(math.sin(angle)) < TANGENT_TOLERANCE, f"{seg.id} meets {main.id}"


@pytest.mark.parametrize("name", INTERCHANGES)
def test_right_hand_traffic(name):
    """Northbound runs on the east side of the primary road."""
    segs = {seg.id: pts for seg, pts in _layout(name)}
    nb, sb = segs["mainline-NB"], segs["mainline-SB"]
    assert all(x > 0 for x, _ in nb) and all(x < 0 for x, _ in sb)
    assert nb[-1][1] > nb[0][1] and sb[-1][1] < sb[0][1]


def test_cloverleaf_loops_sit_in_their_quadrants():
    segs = {seg.id: pts for seg, pts in _layout("Cloverleaf")}
    signs = {"NE": (1, 1), "NW": (-1, 1), "SW": (-1, -1), "SE": (1, -1)}
    for quadrant, (sx, sy) in signs.items():
        pts = segs[f"loop-{quadrant}"]
        assert all(x * sx > 0 and y * sy > 0 for x, y in pts), quadrant
        # A 270° loop on the designed radius: its centre is one radius from both ramp lines.
        xs, ys = [x for x, _ in pts], [y for _, y in pts]
        span = max(max(xs) - min(xs), max(ys) - min(ys))
        assert span == pytest.approx(2 * dims.LOOP_RADIUS_M, abs=1.0)


@pytest.mark.parametrize("name, distance", [
    ("Turbine", dims.TURBINE_RING_RADIUS_M),
    ("Stack (4-Level)", dims.STACK_CENTRE_PASS_M),
])
def test_left_turn_ramps_pass_the_centre_at_their_distance(name, distance):
    for seg, pts in _layout(name):
        if seg.id.startswith("left-from-"):
            nearest = LineString(pts).distance(Point(0, 0))
            assert nearest == pytest.approx(abs(distance), abs=1.0), seg.id


def test_spui_opposing_left_turns_do_not_cross():
    segs = {seg.id: LineString(pts) for seg, pts in _layout("SPUI")}
    assert not segs["ramp-NB-off"].intersects(segs["ramp-SB-off"])
    assert not segs["ramp-NB-on"].intersects(segs["ramp-SB-on"])


def test_ddi_carriageways_cross_twice_at_the_design_angle():
    segs = {seg.id: pts for seg, pts in _layout("DDI")}
    eb, wb = LineString(segs["crossroad-EB"]), LineString(segs["crossroad-WB"])
    crossings = eb.intersection(wb)
    assert crossings.geom_type == "MultiPoint" and len(crossings.geoms) == 2
    # The carriageways are mirror images, each deviating by half the crossing angle at most.
    # Chords of the 2 m samples read a little flatter than the tangent, hence the tolerance.
    pts = list(eb.coords)
    steepest = max(abs(math.degrees(_heading(p, q))) for p, q in zip(pts, pts[1:], strict=False))
    assert 2 * steepest == pytest.approx(dims.DDI_CROSSOVER_ANGLE_DEG, abs=2.5)


@pytest.mark.parametrize("name", ["Trumpet", "Directional T"])
def test_three_leg_stem_leaves_to_the_east(name):
    stems = [pts for seg, pts in _layout(name) if seg.id.startswith("stem-")]
    assert stems and all(max(x for x, _ in pts) > 200 for pts in stems)
