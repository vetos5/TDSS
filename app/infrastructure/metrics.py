"""
Static geometric metrics for transport interchange MCDA evaluation.

These functions derive measurable physical quantities directly from parsed
RoadSegment collections — no dynamic traffic simulation is required.  The
resulting values feed the DecisionSupportSystem as quantitative criteria.

Coordinate-space note
---------------------
The SVG parser stores all control points in a *scaled domain coordinate
system* where:

    domain_distance = svg_pixel_distance × scale_factor

To recover real-world metres we apply the inverse relationship:

    metres = domain_distance × (meters_per_pixel / scale_factor)

For the default Cloverleaf SVG (≈810 px wide, ≈300 m half-span, as
documented in svg_parser.py):

    meters_per_pixel ≈ 0.5  →  1 domain unit ≈ 2 000 m
"""

from __future__ import annotations

from typing import List

from app.domain.geometry import RoadSegment


def compute_total_road_length_m(
    segments: List[RoadSegment],
    scale_factor: float = 0.00025,
    meters_per_pixel: float = 0.5,
) -> float:
    """
    Total centreline road length in metres, summed across all segments.

    Method
    ------
    For each segment the Shapely ``LineString.length`` is computed on the
    cubic-spline interpolated centreline (in domain-coordinate units).  The
    result is converted to real-world metres via the pixel-to-metre ratio:

        length_m = domain_length × (meters_per_pixel / scale_factor)

    Using arc-length on the spline (rather than straight-line control-point
    chord sum) ensures that curved ramps and loop segments are measured
    along their actual path, not a coarse polygon approximation.

    Parameters
    ----------
    segments :
        Parsed ``RoadSegment`` objects from the SVG parser or procedural
        generators.
    scale_factor :
        The SVG-to-domain conversion factor used during parsing.  Defaults
        to ``0.00025`` (matches the Cloverleaf SVG default).
    meters_per_pixel :
        Real-world metres represented by one SVG pixel.  Defaults to
        ``0.5 m/px`` (as documented in ``svg_parser.py``).

    Returns
    -------
    float
        Total centreline length in metres (sum over all segments).
    """
    metres_per_domain_unit = meters_per_pixel / scale_factor
    return sum(
        seg.as_shapely_line().length * metres_per_domain_unit
        for seg in segments
    )


def compute_land_area_m2(
    segments: List[RoadSegment],
    scale_factor: float = 0.00025,
    meters_per_pixel: float = 0.5,
) -> float:
    """
    Axis-aligned bounding-box land footprint in square metres.

    Method
    ------
    Collects every control-point coordinate from all segments and computes
    the axis-aligned bounding rectangle (AABB):

        area_m² = (Δx_domain × Δy_domain) × (meters_per_pixel / scale_factor)²

    MCDA interpretation
    -------------------
    A large bounding box implies a greater land-take, which is a direct
    proxy for land acquisition cost and environmental impact.  In real
    interchange assessments the "area of influence" polygon is commonly
    used as a Minimize criterion (Highways England, 2020).

    Parameters
    ----------
    segments :
        Parsed ``RoadSegment`` objects.
    scale_factor, meters_per_pixel :
        Same coordinate-space parameters as ``compute_total_road_length_m``.

    Returns
    -------
    float
        Bounding-box area in square metres.  Returns ``0.0`` for an empty
        segment list.
    """
    all_x: list[float] = []
    all_y: list[float] = []
    for seg in segments:
        for cp in seg.control_points:
            all_x.append(cp.x)
            all_y.append(cp.y)

    if not all_x:
        return 0.0

    m_per_du = meters_per_pixel / scale_factor
    width_m = (max(all_x) - min(all_x)) * m_per_du
    height_m = (max(all_y) - min(all_y)) * m_per_du
    return width_m * height_m
