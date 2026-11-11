"""The 3-D interchange model: every crossing is either at grade or has its clearance."""

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
    assert client.get("/api/interchange/Nope/model3d").status_code == 404
    # The detail route next to it still answers.
    assert client.get("/api/interchange/Cloverleaf").status_code == 200


# ── Cross-section: pavement edges, tapers and junctions ──────────────────────


def _segment(name, seg_id):
    return next(s for s in build_model(name).segments if s.id == seg_id)


def _width(seg, i):
    return seg.left_m[i] + seg.right_m[i]


@pytest.mark.parametrize("name", NAMES)
def test_every_point_has_a_cross_section(name):
    for seg in build_model(name).segments:
        n = len(seg.points)
        assert len(seg.left_m) == len(seg.right_m) == n
        assert len(seg.edge_left) == len(seg.edge_right) == len(seg.marks) == n
        assert set(seg.edge_left + seg.edge_right) <= set("fmso")
        assert all(_width(seg, i) > 0 for i in range(n)), seg.id
        assert max(_width(seg, i) for i in range(n)) == pytest.approx(seg.width_m, abs=1.5)


@pytest.mark.parametrize("name", NAMES)
def test_no_ramp_ends_bluntly(name):
    # A ramp end is either the tip of a merge taper or opens into the pavement it meets.
    for seg in build_model(name).segments:
        if seg.kind != "ramp":
            continue
        for i in (0, len(seg.points) - 1):
            tapered = _width(seg, i) < 0.5
            opens = "o" in (seg.edge_left[i], seg.edge_right[i])
            assert tapered or opens, (seg.id, i)


def test_speed_change_lane_tapers_and_shares_its_edge():
    loop = _segment("Cloverleaf", "loop-SE")
    last = len(loop.points) - 1
    middle = last // 2
    assert _width(loop, middle) == pytest.approx(dims.LANE_WIDTH_M, abs=0.02)
    assert loop.edge_left[middle] == loop.edge_right[middle] == "f"
    for tip, inward in ((0, 1), (last, -1)):
        # The carriageway is on the left of a ramp in right-hand traffic: that edge stays put
        # and is a lane line, the outer edge runs in to meet it.
        assert loop.edge_left[tip] == "s" and loop.edge_right[tip] == "f"
        assert loop.left_m[tip] == pytest.approx(dims.LANE_WIDTH_M / 2, abs=0.01)
        widths = [_width(loop, tip + inward * k) for k in range(8)]
        assert widths == sorted(widths) and widths[0] < 0.5
    # The carriageway has no edge line or parapet along the speed-change lanes.
    road = _segment("Cloverleaf", "mainline-NB")
    assert road.edge_right.count("s") > 40 and set(road.edge_left) == {"f"}


def test_at_grade_junctions_are_open():
    spui = build_model("SPUI")
    arterial = next(s for s in spui.segments if s.id == "crossroad-EB")
    assert "o" in arterial.edge_left and "o" in arterial.edge_right and "0" in arterial.marks
    for seg in spui.segments:
        if seg.id in ("ramp-NB-off", "ramp-SB-off"):
            # The left turn ends inside the far carriageway: no edges, no markings of its own.
            assert seg.edge_left[-1] == seg.edge_right[-1] == "o" and seg.marks[-1] == "0"
    # A grade-separated crossing is not a junction: the stack's freeways keep their lane lines.
    for seg in build_model("Stack (4-Level)").segments:
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


@pytest.mark.parametrize("name, stem, ramp", [
    ("Directional T", "stem-WB", "flyover-stem-out"),
    ("Trumpet", "stem-WB", "ramp-semi-direct"),
])
def test_stem_drops_to_the_width_of_the_ramp_that_carries_on(name, stem, ramp):
    road, onward = _segment(name, stem), _segment(name, ramp)
    assert _width(road, 0) == pytest.approx(road.width_m, abs=0.02)
    assert _width(road, len(road.points) - 1) == pytest.approx(onward.width_m, abs=0.02)


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
