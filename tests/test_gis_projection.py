"""Local ↔ geographic projection: round-trips, accuracy vs. haversine, bearing/rotation."""

import math

import pytest

from app.infrastructure.gis.projection import (
    LocalOrigin,
    bearing,
    haversine_m,
    rotate,
    to_latlon,
    to_local,
)

KYIV = LocalOrigin(lat=50.4501, lon=30.5234)
EQUATOR = LocalOrigin(lat=0.0, lon=0.0)
LATITUDES = [EQUATOR, LocalOrigin(lat=25.0, lon=10.0), KYIV, LocalOrigin(lat=70.0, lon=-40.0)]


@pytest.mark.parametrize("origin", LATITUDES)
@pytest.mark.parametrize(("dx", "dy"), [(0, 0), (100, 0), (0, 100), (-350, 220), (500, -500)])
def test_round_trip(origin, dx, dy):
    lat, lon = to_latlon(dx, dy, origin)
    x2, y2 = to_local(lat, lon, origin)
    assert x2 == pytest.approx(dx, abs=1e-6)
    assert y2 == pytest.approx(dy, abs=1e-6)


def test_origin_maps_to_itself():
    for origin in LATITUDES:
        assert to_local(origin.lat, origin.lon, origin) == (pytest.approx(0), pytest.approx(0))


@pytest.mark.parametrize("origin", LATITUDES)
def test_north_south_distance_matches_haversine(origin):
    # Pure north-south offsets have no longitude-scaling error at all.
    lat, lon = to_latlon(0, 1000, origin)
    assert haversine_m(origin.lat, origin.lon, lat, lon) == pytest.approx(1000, rel=1e-3)


@pytest.mark.parametrize("origin", LATITUDES)
@pytest.mark.parametrize("offset", [(300, 400), (-500, 500), (800, -200)])
def test_local_projection_matches_haversine_within_one_percent(origin, offset):
    """At interchange scale the flat-earth approximation should track the true distance closely."""
    dx, dy = offset
    lat, lon = to_latlon(dx, dy, origin)
    true_dist = haversine_m(origin.lat, origin.lon, lat, lon)
    local_dist = math.hypot(dx, dy)
    assert local_dist == pytest.approx(true_dist, rel=0.01)


def test_uncorrected_longitude_scale_would_be_wrong_at_kyiv_latitude():
    """Demonstrates the bug this module fixes: a flat (uncorrected) scale distorts east-west."""
    dx, dy = 1000.0, 0.0
    lat, lon = to_latlon(dx, dy, KYIV)
    # Naive: treat degrees-of-longitude like degrees-of-latitude (generators.py's mistake).
    naive_lon = KYIV.lon + dx / (math.pi * 6_371_000.0 / 180.0)
    corrected_dist = haversine_m(KYIV.lat, KYIV.lon, lat, lon)
    naive_dist = haversine_m(KYIV.lat, KYIV.lon, KYIV.lat, naive_lon)
    assert corrected_dist == pytest.approx(1000.0, rel=1e-3)
    # The naive version compresses the same 1000 m east offset down to ~640 m worth of ground truth.
    assert naive_dist < 700.0


@pytest.mark.parametrize(
    ("lat2", "lon2", "expected_deg"),
    [
        (51.4501, 30.5234, 0),
        (50.4501, 31.5234, 90),
        (49.4501, 30.5234, 180),
        (50.4501, 29.5234, 270),
    ],
)
def test_bearing_cardinal_directions(lat2, lon2, expected_deg):
    b = math.degrees(bearing(KYIV.lat, KYIV.lon, lat2, lon2))
    assert b == pytest.approx(expected_deg, abs=1.0)


def test_bearing_wraps_to_0_360():
    for lat2, lon2 in [(51, 31), (49, 29), (49, 31), (51, 29)]:
        assert 0.0 <= bearing(KYIV.lat, KYIV.lon, lat2, lon2) < 2 * math.pi


def test_rotate_by_zero_is_identity():
    assert rotate(37.0, -12.0, 0.0) == pytest.approx((37.0, -12.0))


def test_rotate_north_vector_to_bearing():
    """Rotating the local north axis (0, 1) by a bearing should yield that bearing's unit vector."""
    for deg in [0, 30, 90, 135, 200, 315]:
        b = math.radians(deg)
        x, y = rotate(0.0, 1.0, b)
        assert x == pytest.approx(math.sin(b), abs=1e-9)
        assert y == pytest.approx(math.cos(b), abs=1e-9)


def test_rotate_preserves_length():
    x, y = rotate(300.0, -450.0, math.radians(77.0))
    assert math.hypot(x, y) == pytest.approx(math.hypot(300.0, -450.0))


def test_rotate_full_turn_is_identity():
    x, y = rotate(123.0, -45.0, 2 * math.pi)
    assert (x, y) == pytest.approx((123.0, -45.0))
