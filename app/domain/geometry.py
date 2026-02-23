"""
Parametric road geometry domain model.

Provides strictly-typed primitives for procedural road generation using
cubic-spline interpolation and Shapely geometric operations. All distances
are in **metres**; angles in **radians** unless stated otherwise.
"""

from __future__ import annotations

import math
from typing import List, Tuple

import numpy as np
from pydantic import BaseModel, Field, model_validator
from scipy.interpolate import CubicSpline
from shapely.geometry import LineString, Point


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------

class ControlPoint(BaseModel):
    """Single 2-D control point used to define road centrelines."""

    x: float
    y: float

    def as_tuple(self) -> Tuple[float, float]:
        return (self.x, self.y)

    def distance_to(self, other: ControlPoint) -> float:
        return math.hypot(self.x - other.x, self.y - other.y)


class RoadSegment(BaseModel):
    """
    A parametric road segment defined by an ordered sequence of control points.

    The centreline is reconstructed via natural cubic-spline interpolation
    so that even 3-4 control points produce a smooth, C²-continuous curve
    suitable for CAD-quality rendering.
    """

    id: str = Field(default="seg-0", description="Unique segment identifier")
    control_points: List[ControlPoint] = Field(
        ..., min_length=2, description="Ordered control points defining the centreline"
    )
    num_lanes: int = Field(default=2, ge=1, le=8)
    lane_width_meters: float = Field(default=3.5, gt=0, le=10.0)
    speed_limit_kmh: float = Field(default=60.0, ge=5)

    # -- computed helpers (not serialised) --
    _geometry_cache: LineString | None = None

    model_config = {"arbitrary_types_allowed": True}

    @model_validator(mode="after")
    def _invalidate_cache(self) -> "RoadSegment":
        object.__setattr__(self, "_geometry_cache", None)
        return self

    # ------------------------------------------------------------------
    # Core geometry generation
    # ------------------------------------------------------------------

    def generate_centreline(self, steps: int = 200) -> List[Tuple[float, float]]:
        """
        Return *steps* evenly-spaced (x, y) pairs along a natural cubic spline
        fitted through the control points.

        For exactly two control points the result is a straight line (the
        degenerate case of a spline).  Three or more points produce a smooth
        C²-continuous curve.
        """
        pts = [cp.as_tuple() for cp in self.control_points]
        xs = np.array([p[0] for p in pts])
        ys = np.array([p[1] for p in pts])

        if len(pts) == 2:
            t_vals = np.linspace(0, 1, steps)
            interp_x = xs[0] + t_vals * (xs[1] - xs[0])
            interp_y = ys[0] + t_vals * (ys[1] - ys[0])
            return list(zip(interp_x.tolist(), interp_y.tolist()))

        cumulative_dist = np.zeros(len(pts))
        for i in range(1, len(pts)):
            cumulative_dist[i] = cumulative_dist[i - 1] + math.hypot(
                xs[i] - xs[i - 1], ys[i] - ys[i - 1]
            )

        t_param = cumulative_dist / cumulative_dist[-1]

        cs_x = CubicSpline(t_param, xs, bc_type="natural")
        cs_y = CubicSpline(t_param, ys, bc_type="natural")

        t_fine = np.linspace(0, 1, steps)
        interp_x = cs_x(t_fine)
        interp_y = cs_y(t_fine)

        return list(zip(interp_x.tolist(), interp_y.tolist()))

    def road_width(self) -> float:
        """Total paved width in metres."""
        return self.num_lanes * self.lane_width_meters

    def as_shapely_line(self, steps: int = 200) -> LineString:
        """Shapely LineString of the centreline (cached)."""
        if self._geometry_cache is None:
            coords = self.generate_centreline(steps)
            object.__setattr__(self, "_geometry_cache", LineString(coords))
        return self._geometry_cache  # type: ignore[return-value]

    def generate_offset_lines(
        self, steps: int = 200
    ) -> Tuple[LineString, LineString]:
        """
        Return (left_edge, right_edge) offset from the centreline by
        ±road_width/2.  Used for rendering the asphalt polygon.
        """
        centre = self.as_shapely_line(steps)
        half_w = self.road_width() / 2
        left = centre.offset_curve(half_w)
        right = centre.offset_curve(-half_w)
        return left, right

    def capacity_veh_per_hour(self) -> float:
        """
        Rough HCM-style capacity estimate: 1800 pc/h/ln for freeways,
        scaled by speed limit bracket.
        """
        base = 1800.0
        if self.speed_limit_kmh < 50:
            factor = 0.75
        elif self.speed_limit_kmh < 80:
            factor = 0.90
        else:
            factor = 1.0
        return base * self.num_lanes * factor


# ---------------------------------------------------------------------------
# Network aggregate
# ---------------------------------------------------------------------------

class RoadNetwork(BaseModel):
    """Collection of road segments forming a routable network."""

    segments: List[RoadSegment] = Field(default_factory=list)

    def add_segment(self, segment: RoadSegment) -> None:
        self.segments.append(segment)

    def find_intersections(self, steps: int = 200) -> List[Tuple[float, float]]:
        """
        Detect pairwise geometric intersections between all segment
        centrelines.  Returns a flat list of (x, y) conflict points.
        """
        lines = [(seg.id, seg.as_shapely_line(steps)) for seg in self.segments]
        conflicts: list[Tuple[float, float]] = []
        for i in range(len(lines)):
            for j in range(i + 1, len(lines)):
                inter = lines[i][1].intersection(lines[j][1])
                if inter.is_empty:
                    continue
                if inter.geom_type == "Point":
                    conflicts.append((inter.x, inter.y))
                elif inter.geom_type == "MultiPoint":
                    for pt in inter.geoms:
                        conflicts.append((pt.x, pt.y))
        return conflicts

    def all_centrelines(self, steps: int = 200) -> List[List[Tuple[float, float]]]:
        return [seg.generate_centreline(steps) for seg in self.segments]
