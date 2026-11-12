"""The 3-D interchange model: clearances at every crossing, and lanes that all go somewhere."""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import LineString, Point

from app.application.footprint import FOOTPRINT_GENERATORS
from app.application.model3d import build_model
from app.data import interchange_geometry as dims
from backend.main import app

NAMES = list(FOOTPRINT_GENERATORS)
EXPECTED_LEVELS = {
    "Cloverleaf": 2, "Turbine": 4, "Stack (4-Level)": 4, "Diamond": 2,
    "SPUI": 2, "DDI": 2, "Trumpet": 2, "Directional T": 3,
}


def _lines(model):
    out = {}
    for seg in model.segments:
        pts = np.array(seg.points)
        s = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(pts[:, :2], axis=0).T))])
        out[seg.id] = (LineString(pts[:, :2]), s, pts[:, 2])
    return out


def _height(line, point):
    geom, s, z = line
    return float(np.interp(geom.project(point), s, z))


@pytest.mark.parametrize("name", NAMES)
def test_every_crossing_is_at_grade_or_has_clearance(name):
    lines = _lines(build_model(name))
    ids = list(lines)
    crossings = 0
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            inter = lines[a][0].intersection(lines[b][0])
            for g in getattr(inter, "geoms", [inter]):
                if g.is_empty or g.geom_type != "Point":
                    continue
                crossings += 1
                gap = abs(_height(lines[a], g) - _height(lines[b], g))
                assert gap < 0.15 or gap > dims.LEVEL_STEP_M - 0.15, (a, b, round(gap, 2))
    assert crossings >= 4


@pytest.mark.parametrize("name", NAMES)
def test_levels_and_heights(name):
    model = build_model(name)
    assert model.levels == EXPECTED_LEVELS[name]
    top = (model.levels - 1) * dims.LEVEL_STEP_M
    assert top - dims.LEVEL_STEP_M / 2 < model.max_height_m <= top + 0.01
    for seg in model.segments:
        z = np.array(seg.points)[:, 2]
        assert np.isfinite(z).all() and z.min() >= -1e-6


@pytest.mark.parametrize("name", NAMES)
def test_profiles_are_smooth_and_not_absurdly_steep(name):
    model = build_model(name)
    assert model.max_grade < 0.12
    for seg in model.segments:
        pts = np.array(seg.points)
        step = np.hypot(*np.diff(pts[:, :2], axis=0).T)
        slope = np.diff(pts[:, 2]) / step
        # No steps in the surface: the slope changes gradually from sample to sample.
        assert np.abs(np.diff(slope)).max() < 0.05, seg.id


@pytest.mark.parametrize("name", NAMES)
def test_ramp_ends_sit_on_the_road_they_join(name):
    model = build_model(name)
    lines = _lines(model)
    roads = [s for s in model.segments if s.kind != "ramp"]
    for seg in model.segments:
        if seg.kind != "ramp":
            continue
        for x, y, z in (seg.points[0], seg.points[-1]):
            p = Point(x, y)
            near = [
                r for r in roads
                if lines[r.id][0].distance(p) <= (r.width_m + seg.width_m) / 2 + 1
            ]
            if near:
                assert min(abs(_height(lines[r.id], p) - z) for r in near) < 0.1, seg.id


@pytest.mark.parametrize("name", NAMES)
def test_piers_stand_clear_of_the_roads_below(name):
    model = build_model(name)
    lines = _lines(model)
    assert model.piers
    for pier in model.piers:
        assert pier.top_m >= dims.PIER_MIN_HEIGHT_M - 1e-6
        p = Point(pier.x, pier.y)
        for seg in model.segments:
            if _height(lines[seg.id], p) < pier.top_m - 1.0:
                assert lines[seg.id][0].distance(p) >= seg.width_m / 2 + pier.width_m / 2, seg.id


def test_ramps_run_with_the_traffic():
    # Right-hand traffic: a cloverleaf loop leaves eastbound and ends on northbound.
    model = build_model("Cloverleaf")
    loop = next(s for s in model.segments if s.id == "loop-SE")
    (x0, y0, _), (x1, y1, _) = loop.points[0], loop.points[1]
    assert x1 > x0 and abs(y1 - y0) < 0.1
    # A mirrored ramp is stored against the traffic and must be turned round: the diamond's
    # northbound on-ramp starts at the arterial and ends heading north on the freeway.
    model = build_model("Diamond")
    on = next(s for s in model.segments if s.id == "ramp-NB-on")
    assert on.points[-1][1] > on.points[0][1]


def test_unknown_alternative_has_no_model():
    assert build_model("Roundabout") is None


def test_api_returns_the_model():
    client = TestClient(app)
    res = client.get("/api/interchange/Stack (4-Level)/model3d")
    assert res.status_code == 200
    body = res.json()
    assert body["levels"] == 4 and len(body["segments"]) == 12 and body["piers"]
    assert len(body["segments"][0]["points"][0]) == 3
    assert len(body["routes"]) == 16 and body["headway_s"] > 0
    assert len(body["routes"][0]["points"][0]) == 4
    assert client.get("/api/interchange/Nope/model3d").status_code == 404
    # The detail route next to it still answers.
    assert client.get("/api/interchange/Cloverleaf").status_code == 200


# ── Lanes: what leaves a carriageway is a lane, and every lane goes somewhere ─

LANE = dims.LANE_WIDTH_M
# Ramp ends that run on a lane of a road: (lanes taken from carriageways, lanes brought to them).
LANE_EVENTS = {
    "Cloverleaf": (8, 8), "Turbine": (8, 8), "Stack (4-Level)": (8, 8),
    "Diamond": (2, 2),              # the freeway ends of the four ramps
    "SPUI": (6, 6),                 # two two-lane ramps each way, and the four right turns
    "DDI": (8, 8),                  # the same, and the four left turns between the crossovers
    "Trumpet": (3, 3), "Directional T": (3, 3),
}
# Lanes that end, or start, at a plain junction instead of carrying on: a diamond's ramp terminals.
JUNCTION_ENDS = {"Diamond": 2}


def _segment(name, seg_id):
    return next(s for s in build_model(name).segments if s.id == seg_id)


def _width(seg, i):
    return seg.left_m[i] + seg.right_m[i]


def _frame(seg):
    """Centreline, arc length and unit direction of a segment's points."""
    xy = np.array(seg.points)[:, :2]
    s = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(xy, axis=0).T))])
    d = np.gradient(xy, axis=0)
    return xy, s, d / np.hypot(d[:, 0], d[:, 1])[:, None]


def _lane_events(name):
    """
    Every ramp end that runs on a lane of a road, found from the output alone: the ramp is
    parallel to the road there, level with it, and has a lane line (a shared edge) beside it.
    Yields (ramp, road, arc length on the road, True if the ramp ends there).
    """
    model = build_model(name)
    roads = [(r, *_frame(r)) for r in model.segments if r.kind != "ramp"]
    for ramp in (s for s in model.segments if s.kind == "ramp"):
        xy, _, d = _frame(ramp)
        n = len(ramp.points)
        for tip, near in ((0, slice(0, 8)), (n - 1, slice(n - 8, n))):
            if "s" not in ramp.edge_left[near] + ramp.edge_right[near]:
                continue
            for road, rxy, rs, rd in roads:
                line = LineString(rxy)
                p = Point(xy[tip])
                at = line.project(p)
                j = int(np.argmin(np.abs(rs - at)))
                if (line.distance(p) < road.width_m / 2 + LANE and abs(d[tip] @ rd[j]) > 0.95
                        and abs(road.points[j][2] - ramp.points[tip][2]) < 0.2
                        and 2 < at < rs[-1] - 2):
                    yield ramp, road, at, tip != 0


@pytest.mark.parametrize("name", NAMES)
def test_every_point_has_a_cross_section(name):
    for seg in build_model(name).segments:
        n = len(seg.points)
        assert len(seg.left_m) == len(seg.right_m) == n
        assert len(seg.edge_left) == len(seg.edge_right) == len(seg.marks) == n
        assert set(seg.edge_left + seg.edge_right) <= set("fmso")
        # Never less than one lane, never more than its lanes, one auxiliary lane and a median.
        widths = [_width(seg, i) for i in range(n)]
        assert min(widths) >= LANE - 0.01, seg.id
        assert max(widths) <= seg.width_m + LANE + dims.MEDIAN_FILL_MAX_M, seg.id


@pytest.mark.parametrize("name", NAMES)
def test_lanes_are_conserved_at_every_ramp_end(name):
    # Lane mathematics: lanes before a diverge = lanes carrying on + lanes of the ramp, and
    # lanes after a merge = lanes arriving + lanes of the ramp. Nothing tapers away.
    taken = brought = 0
    for ramp, road, at, ramp_ends in _lane_events(name):
        _, rs, _ = _frame(road)
        before = _width(road, int(np.argmin(np.abs(rs - (at - 12)))))
        after = _width(road, int(np.argmin(np.abs(rs - (at + 12)))))
        change = after - before if ramp_ends else before - after
        assert change == pytest.approx(ramp.width_m, abs=0.05), (ramp.id, road.id, before, after)
        brought += ramp.lanes * ramp_ends
        taken += ramp.lanes * (not ramp_ends)
    assert (taken, brought) == LANE_EVENTS[name]


@pytest.mark.parametrize("name", NAMES)
def test_a_ramp_keeps_its_width_from_end_to_end(name):
    # A ramp is a whole lane (or two) all the way: it does not grow out of a taper or die in one.
    for seg in build_model(name).segments:
        if seg.kind == "ramp":
            widths = [_width(seg, i) for i in range(len(seg.points))]
            assert min(widths) == pytest.approx(seg.width_m, abs=0.02), seg.id
            assert max(widths) == pytest.approx(seg.width_m, abs=0.02), seg.id


@pytest.mark.parametrize("name", NAMES)
def test_every_lane_goes_somewhere(name):
    model = build_model(name)
    roads = [s for s in model.segments if s.kind != "ramp"]
    arriving = sum(s.lanes for s in roads if s.open_start)
    leaving = sum(s.lanes for s in roads if s.open_end)
    assert arriving == leaving
    # One route per lane that arrives, each running on to a lane that leaves: no lane ends
    # inside the interchange and no two run into one. The one exception is a plain junction.
    inside = JUNCTION_ENDS.get(name, 0)
    assert sum(r.open_start for r in model.routes) == arriving
    assert sum(r.open_end for r in model.routes) == leaving
    assert sum(not r.open_start for r in model.routes) == inside
    assert sum(not r.open_end for r in model.routes) == inside
    assert len({r.id for r in model.routes}) == len(model.routes)


def _route_lines(model):
    out = []
    for r in model.routes:
        p = np.array(r.points)
        along = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(p[:, :2], axis=0).T))])
        out.append((r, p, LineString(p[:, :2]), along))
    return out


@pytest.mark.parametrize("name", NAMES)
def test_routes_are_drivable(name):
    model = build_model(name)
    for r, p, _, _ in _route_lines(model):
        step = np.linalg.norm(np.diff(p[:, :3], axis=0), axis=1)
        dt = np.diff(p[:, 3])
        assert (dt > 0).all(), r.id
        speed = step / dt * 3.6
        assert 20 < speed.min() and speed.max() < 101, (r.id, speed.min(), speed.max())
        # No sideways jumps: the direction turns by little from one point to the next.
        d = np.diff(p[:, :2], axis=0)
        d = d / np.hypot(d[:, 0], d[:, 1])[:, None]
        turn = np.abs(d[:-1, 0] * d[1:, 1] - d[:-1, 1] * d[1:, 0])
        assert turn.max(initial=0.0) < 0.45, (r.id, turn.max(initial=0.0))
        assert p[:, 2].min() >= -0.01 and p[:, 2].max() <= model.max_height_m + 0.01


@pytest.mark.parametrize("name", NAMES)
def test_no_two_routes_share_a_lane_and_crossing_cars_miss_each_other(name):
    model = build_model(name)
    lines = _route_lines(model)
    crossings = 0
    for i, (ra, pa, la, sa) in enumerate(lines):
        for rb, pb, lb, sb in lines[i + 1:]:
            inter = la.intersection(lb)
            for g in getattr(inter, "geoms", [inter]):
                if g.is_empty:
                    continue
                assert g.geom_type == "Point", (ra.id, rb.id)   # an overlap would be a shared lane
                at_a, at_b = la.project(g), lb.project(g)
                if abs(np.interp(at_a, sa, pa[:, 2]) - np.interp(at_b, sb, pb[:, 2])) > 3:
                    continue                                     # one passes over the other
                crossings += 1
                gap = (ra.phase_s + np.interp(at_a, sa, pa[:, 3])
                       - rb.phase_s - np.interp(at_b, sb, pb[:, 3])) % model.headway_s
                assert min(gap, model.headway_s - gap) > 0.8, (ra.id, rb.id)
    # Routes cross at one level only in a weave or an at-grade junction.
    expected = {"Cloverleaf": 4, "SPUI": 8, "DDI": 10}
    assert crossings == expected.get(name, 0)
    assert 2.0 < model.headway_s < 3.0


def test_a_ramp_runs_on_the_lane_it_takes_and_brings():
    loop = _segment("Cloverleaf", "loop-SE")
    last = len(loop.points) - 1
    # In right-hand traffic the carriageway is on the left of a ramp: a lane line there while it
    # runs alongside, and the edge of the road on the right throughout.
    for near in (slice(2, 10), slice(last - 10, last - 2)):
        assert set(loop.edge_left[near]) == {"s"}
    assert set(loop.edge_right) == {"f"}
    assert loop.edge_left[last // 2] == "f"
    # The carriageway: three lanes, two past the connector, three in the weave between the
    # loops, two again, three once the far connector has joined. Its inside edge never moves.
    road = _segment("Cloverleaf", "mainline-NB")
    lanes = [round(_width(road, i) / LANE) for i in range(len(road.points))]
    runs = [n for i, n in enumerate(lanes) if i == 0 or n != lanes[i - 1]]
    assert runs == [3, 2, 3, 2, 3]
    assert max(road.left_m) - min(road.left_m) < 0.01 and set(road.edge_left) == {"f"}
    assert road.edge_right.count("s") > 40


@pytest.mark.parametrize("name, lanes", [
    ("Turbine", [4, 3, 2, 3, 4]), ("Stack (4-Level)", [4, 3, 2, 3, 4]),
    ("Diamond", [3, 2, 3]), ("SPUI", [4, 2, 4]), ("DDI", [4, 2, 4]),
    ("Trumpet", [3, 2, 3]), ("Directional T", [3, 2, 3]),
])
def test_freeway_lane_counts_through_the_interchange(name, lanes):
    for seg_id in ("mainline-NB", "mainline-SB"):
        road = _segment(name, seg_id)
        counts = [round(_width(road, i) / LANE) for i in range(len(road.points))]
        assert [n for i, n in enumerate(counts) if i == 0 or n != counts[i - 1]] == lanes
        assert min(counts) >= 2   # two lanes always run straight through


def test_at_grade_junctions_are_open():
    spui = build_model("SPUI")
    arterial = next(s for s in spui.segments if s.id == "crossroad-EB")
    assert "o" in arterial.edge_left and "o" in arterial.edge_right and "0" in arterial.marks
    for seg in spui.segments:
        if seg.id in ("ramp-NB-off-left", "ramp-SB-off-left"):
            # The left turn ends inside the far carriageway: no edges, no markings of its own.
            assert seg.edge_left[-1] == seg.edge_right[-1] == "o" and seg.marks[-1] == "0"
    # A grade-separated crossing is not a junction: the stack's freeways keep their lane lines.
    for seg in build_model("Stack (4-Level)").segments:
        if seg.kind != "ramp":
            assert "0" not in seg.marks and "o" not in seg.edge_left + seg.edge_right, seg.id


def test_narrow_median_is_one_deck():
    arterial = _segment("Diamond", "crossroad-EB")
    assert arterial.edge_left.count("m") > len(arterial.points) * 0.9
    assert max(arterial.left_m) == pytest.approx(
        arterial.width_m / 2 + dims.ARTERIAL_MEDIAN_M / 2, abs=0.01
    )
    # A freeway's wider median stays open between its two carriageways.
    freeway = _segment("Diamond", "mainline-NB")
    assert "m" not in freeway.edge_left + freeway.edge_right
    assert max(freeway.left_m) == pytest.approx(freeway.width_m / 2, abs=0.01)


@pytest.mark.parametrize("name, out, onward, back, arriving", [
    ("Directional T", "stem-WB", "flyover-stem-out", "stem-EB", "flyover-stem-in"),
    ("Trumpet", "stem-WB", "ramp-semi-direct", "stem-EB", "loop"),
])
def test_stem_lanes_split_one_per_turn(name, out, onward, back, arriving):
    # Outbound: two lanes, the outer one leaves on the right-turn connector and the inside one
    # carries on into the left-turn ramp, which starts on its centreline.
    road, ramp = _segment(name, out), _segment(name, onward)
    assert _width(road, 0) == pytest.approx(2 * LANE) and _width(road, -1) == pytest.approx(LANE)
    assert road.right_m[-1] == pytest.approx(0.0) and road.left_m[-1] == pytest.approx(LANE)
    assert not road.open_end
    _, _, d = _frame(road)
    inside_lane = np.array(road.points[-1][:2]) + np.array([-d[-1][1], d[-1][0]]) * LANE / 2
    assert np.allclose(ramp.points[0][:2], inside_lane, atol=0.02)
    # Inbound it is the mirror image: one lane arrives from the left-turn ramp, the connector
    # brings the second.
    road, ramp = _segment(name, back), _segment(name, arriving)
    assert _width(road, 0) == pytest.approx(LANE) and _width(road, -1) == pytest.approx(2 * LANE)
    _, _, d = _frame(road)
    inside_lane = np.array(road.points[0][:2]) + np.array([-d[0][1], d[0][0]]) * LANE / 2
    assert np.allclose(ramp.points[-1][:2], inside_lane, atol=0.02)


def test_two_lane_ramp_forks_into_one_lane_per_turn():
    for name in ("SPUI", "DDI"):
        stem = _segment(name, "ramp-NB-off")
        left, right = _segment(name, "ramp-NB-off-left"), _segment(name, "ramp-NB-off-right")
        assert (stem.lanes, left.lanes, right.lanes) == (2, 1, 1)
        end = np.array(stem.points[-1])
        # Side by side at the end of the ramp, at its height: the left lane and the right lane.
        assert left.points[0][0] == pytest.approx(end[0] - LANE / 2, abs=0.02)
        assert right.points[0][0] == pytest.approx(end[0] + LANE / 2, abs=0.02)
        for turn in (left, right):
            assert turn.points[0][1] == pytest.approx(end[1], abs=0.02)
            assert turn.points[0][2] == pytest.approx(end[2], abs=0.05)
        # The fork is part of the climb from the freeway to the arterial, not a step in it.
        assert 0.5 < end[2] < dims.LEVEL_STEP_M - 0.5


def test_ddi_auxiliary_lane_crosses_the_bridge():
    # Between the crossovers the off-ramp's left turn arrives as a fourth lane on the outside,
    # which leaves again as the left turn onto the on-ramp; two lanes pass each crossover.
    road = _segment("DDI", "crossroad-EB")
    lanes = [round((_width(road, i) - 0.01) / LANE) for i in range(len(road.points))]
    assert [n for i, n in enumerate(lanes) if i == 0 or n != lanes[i - 1]] == [3, 2, 3, 2, 3]
    middle = len(road.points) // 2
    assert road.left_m[middle] == pytest.approx(road.width_m / 2 + LANE, abs=0.01)
    assert road.right_m[middle] == pytest.approx(road.width_m / 2 - LANE, abs=0.01)


@pytest.mark.parametrize("name", NAMES)
def test_roads_leaving_the_interchange_are_marked_open(name):
    model = build_model(name)
    for seg in model.segments:
        if seg.kind == "ramp":
            assert not seg.open_start and not seg.open_end, seg.id
    # Every leg of the interchange leaves it on two carriageways: four legs, or three for a T.
    legs = 3 if name in ("Trumpet", "Directional T") else 4
    assert sum(s.open_start + s.open_end for s in model.segments) == 2 * legs
    # An open end is out at the edge of the plan and on the ground.
    for seg in model.segments:
        for is_open, (x, y, z) in ((seg.open_start, seg.points[0]), (seg.open_end, seg.points[-1])):
            if is_open:
                assert max(abs(x), abs(y)) > 150 and z < 0.05, seg.id
