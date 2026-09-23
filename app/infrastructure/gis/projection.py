"""
Local ↔ geographic coordinate projection for placing interchange footprints on a real map.

At interchange scale (hundreds of metres) the earth's curvature is negligible, so a simple
**equirectangular / local tangent-plane** projection is accurate enough — provided longitude is
scaled by cos(latitude). Skipping that correction is a real mistake: at Kyiv's latitude
(~50.45°N), one degree of longitude spans only cos(50.45°) ≈ 0.638 of a degree of latitude, so an
uncorrected projection compresses east–west distances by about 36 %.

(`app/infrastructure/generators.py`'s five interchange generators do exactly this — they scale
both axes by the same flat `0.0005` degrees/metre constant. Phase 3 does not touch them; instead
it instantiates a generator at the origin (`center_lon=0, center_lat=0`), multiplies its raw
output by `METRES_PER_COORD` — see `app/domain/geometry.py` — to recover true local metres, and
projects with the corrected code here. See `app/application/footprint.py`.)

All angles in radians unless a name says otherwise (`_deg` suffix); all distances in metres.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

EARTH_RADIUS_M = 6_371_000.0
METRES_PER_DEGREE_LAT = math.pi * EARTH_RADIUS_M / 180.0  # ≈ 111,195 m


@dataclass(frozen=True)
class LocalOrigin:
    """A projection's reference point; longitude is scaled by cos(lat) around this latitude."""

    lat: float
    lon: float

    @property
    def _lon_scale(self) -> float:
        return math.cos(math.radians(self.lat))


def to_local(lat: float, lon: float, origin: LocalOrigin) -> tuple[float, float]:
    """Project (lat, lon) to local metres (x = east, y = north) relative to *origin*."""
    y = (lat - origin.lat) * METRES_PER_DEGREE_LAT
    x = (lon - origin.lon) * METRES_PER_DEGREE_LAT * origin._lon_scale
    return x, y


def to_latlon(x: float, y: float, origin: LocalOrigin) -> tuple[float, float]:
    """Inverse of :func:`to_local`: local metres (east, north) to (lat, lon)."""
    lat = origin.lat + y / METRES_PER_DEGREE_LAT
    lon = origin.lon + x / (METRES_PER_DEGREE_LAT * origin._lon_scale)
    return lat, lon


def rotate(x: float, y: float, bearing_rad: float) -> tuple[float, float]:
    """
    Rotate a local (east, north) point by a compass bearing.

    A bearing of 0 (north) leaves the point unchanged; positive bearings rotate clockwise
    (east), matching :func:`bearing`'s convention.
    """
    sin_b, cos_b = math.sin(bearing_rad), math.cos(bearing_rad)
    return x * cos_b + y * sin_b, -x * sin_b + y * cos_b


def bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Initial compass bearing (radians, 0 = north, π/2 = east) from point 1 to point 2.

    Standard great-circle bearing formula — used at short range here, but exact regardless of
    distance, so it stays correct even if a caller passes distant points by mistake.
    """
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_lambda = math.radians(lon2 - lon1)
    x = math.sin(d_lambda) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(d_lambda)
    return math.atan2(x, y) % (2 * math.pi)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres — used only to validate the local projection's accuracy."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))
