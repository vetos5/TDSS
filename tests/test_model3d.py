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
