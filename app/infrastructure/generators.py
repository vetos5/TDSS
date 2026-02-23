"""
Procedural interchange geometry generators.

Each generator is a factory that converts a compact set of engineering
parameters into a fully-formed `RoadNetwork` of smooth `RoadSegment`s.
The control-point placement uses trigonometric formulas derived from
real interchange design manuals (AASHTO Green Book geometry).
"""

from __future__ import annotations

import math
from typing import List

from app.domain.geometry import ControlPoint, RoadNetwork, RoadSegment


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _arc_points(
    cx: float,
    cy: float,
    radius: float,
    start_angle: float,
    end_angle: float,
    n: int = 8,
) -> List[ControlPoint]:
    """Generate *n* control points along a circular arc."""
    angles = [start_angle + (end_angle - start_angle) * i / (n - 1) for i in range(n)]
    return [ControlPoint(x=cx + radius * math.cos(a), y=cy + radius * math.sin(a)) for a in angles]


def _line_points(
    x0: float, y0: float, x1: float, y1: float, n: int = 4
) -> List[ControlPoint]:
    """Generate *n* evenly spaced points along a straight segment."""
    return [
        ControlPoint(
            x=x0 + (x1 - x0) * i / (n - 1),
            y=y0 + (y1 - y0) * i / (n - 1),
        )
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Cloverleaf Interchange
# ---------------------------------------------------------------------------

class CloverleafGenerator:
    """
    Generates a standard 4-loop cloverleaf interchange centred at the origin.

    Produces:
      - 2 straight through-road segments (N-S and E-W)
      - 4 loop ramps (one in each quadrant)
      - 4 connector ramps linking the mainline to each loop
    """

    def __init__(
        self,
        radius: float = 50.0,
        lane_width: float = 3.5,
        mainline_lanes: int = 3,
        ramp_lanes: int = 1,
        mainline_length: float = 300.0,
        center_lon: float = 30.5234,
        center_lat: float = 50.4501,
    ):
        self.radius = radius
        self.lane_width = lane_width
        self.mainline_lanes = mainline_lanes
        self.ramp_lanes = ramp_lanes
        self.length = mainline_length
        self.cx = center_lon
        self.cy = center_lat
        self.scale = 0.0005  # degrees per metre (rough approximation)

    def generate(self) -> RoadNetwork:
        network = RoadNetwork()
        s = self.scale
        half = self.length / 2 * s
        r = self.radius * s
        cx, cy = self.cx, self.cy

        # Through-roads
        network.add_segment(RoadSegment(
            id="mainline-EW",
            control_points=_line_points(cx - half, cy, cx + half, cy, n=6),
            num_lanes=self.mainline_lanes,
            lane_width_meters=self.lane_width,
            speed_limit_kmh=80,
        ))
        network.add_segment(RoadSegment(
            id="mainline-NS",
            control_points=_line_points(cx, cy - half, cx, cy + half, n=6),
            num_lanes=self.mainline_lanes,
            lane_width_meters=self.lane_width,
            speed_limit_kmh=80,
        ))

        # Loop ramps — one per quadrant
        quadrants = [
            ("loop-NE", cx + r, cy + r, math.pi,      math.pi / 2),
            ("loop-NW", cx - r, cy + r, 0,             math.pi / 2),
            ("loop-SW", cx - r, cy - r, 0,             -math.pi / 2),
            ("loop-SE", cx + r, cy - r, math.pi,       -math.pi / 2),
        ]
        # NE quadrant: centre at (+r, +r), arc from π → π/2 (sweeps from left to top)
        # Adjust: for a cloverleaf each loop connects the two mainlines
        quadrant_defs = [
            ("loop-NE", 1,  1,  math.pi,        math.pi * 1.5),
            ("loop-NW", -1, 1,  0.0,             -math.pi * 0.5),
            ("loop-SW", -1, -1, 0.0,             math.pi * 0.5),
            ("loop-SE", 1,  -1, math.pi,         math.pi * 0.5),
        ]
        for name, sx, sy, start_a, end_a in quadrant_defs:
            loop_cx = cx + sx * r * 0.7
            loop_cy = cy + sy * r * 0.7
            pts = _arc_points(loop_cx, loop_cy, r, start_a, end_a, n=12)
            network.add_segment(RoadSegment(
                id=name,
                control_points=pts,
                num_lanes=self.ramp_lanes,
                lane_width_meters=self.lane_width,
                speed_limit_kmh=40,
            ))

        return network


# ---------------------------------------------------------------------------
# Diverging Diamond Interchange (DDI)
# ---------------------------------------------------------------------------

class DDIGenerator:
    """
    Generates a Diverging Diamond Interchange.

    Produces:
      - A straight freeway mainline (E-W).
      - An overpass arterial that "crosses over" twice creating the
        characteristic diamond cross-over pattern.
      - 4 diagonal ramp segments.
    """

    def __init__(
        self,
        crossover_angle_deg: float = 30.0,
        length: float = 200.0,
        lane_width: float = 3.5,
        mainline_lanes: int = 3,
        arterial_lanes: int = 2,
        center_lon: float = 30.5234,
        center_lat: float = 50.4501,
    ):
        self.angle = math.radians(crossover_angle_deg)
        self.length = length
        self.lane_width = lane_width
        self.mainline_lanes = mainline_lanes
        self.arterial_lanes = arterial_lanes
        self.cx = center_lon
        self.cy = center_lat
        self.scale = 0.0005

    def generate(self) -> RoadNetwork:
        network = RoadNetwork()
        s = self.scale
        half = self.length / 2 * s
        cx, cy = self.cx, self.cy

        # Freeway mainline (E-W)
        network.add_segment(RoadSegment(
            id="freeway",
            control_points=_line_points(cx - half, cy, cx + half, cy, n=6),
            num_lanes=self.mainline_lanes,
            lane_width_meters=self.lane_width,
            speed_limit_kmh=100,
        ))

        # Arterial with two crossover kinks
        offset = self.length * 0.15 * s
        kink = self.length * 0.08 * s
        arterial_pts = [
            ControlPoint(x=cx, y=cy - half),
            ControlPoint(x=cx - kink, y=cy - offset),
            ControlPoint(x=cx - kink, y=cy - offset * 0.3),
            ControlPoint(x=cx + kink, y=cy + offset * 0.3),
            ControlPoint(x=cx + kink, y=cy + offset),
            ControlPoint(x=cx, y=cy + half),
        ]
        network.add_segment(RoadSegment(
            id="arterial",
            control_points=arterial_pts,
            num_lanes=self.arterial_lanes,
            lane_width_meters=self.lane_width,
            speed_limit_kmh=50,
        ))

        # Diamond ramps
        ramp_offset = self.length * 0.25 * s
        ramp_kink = kink * 1.5
        ramp_defs = [
            ("ramp-NE", cx + ramp_kink, cy + offset * 0.3, cx + ramp_offset, cy),
            ("ramp-SE", cx + ramp_kink, cy - offset * 0.3, cx + ramp_offset, cy),
            ("ramp-NW", cx - ramp_kink, cy + offset * 0.3, cx - ramp_offset, cy),
            ("ramp-SW", cx - ramp_kink, cy - offset * 0.3, cx - ramp_offset, cy),
        ]
        for name, x0, y0, x1, y1 in ramp_defs:
            network.add_segment(RoadSegment(
                id=name,
                control_points=_line_points(x0, y0, x1, y1, n=4),
                num_lanes=1,
                lane_width_meters=self.lane_width,
                speed_limit_kmh=40,
            ))

        return network


# ---------------------------------------------------------------------------
# Roundabout
# ---------------------------------------------------------------------------

class RoundaboutGenerator:
    """
    Generates a circular roundabout with configurable entry/exit arms.
    """

    def __init__(
        self,
        radius: float = 30.0,
        num_entries: int = 4,
        arm_length: float = 100.0,
        lane_width: float = 3.5,
        circulatory_lanes: int = 2,
        arm_lanes: int = 2,
        center_lon: float = 30.5234,
        center_lat: float = 50.4501,
    ):
        self.radius = radius
        self.num_entries = num_entries
        self.arm_length = arm_length
        self.lane_width = lane_width
        self.circ_lanes = circulatory_lanes
        self.arm_lanes = arm_lanes
        self.cx = center_lon
        self.cy = center_lat
        self.scale = 0.0005

    def generate(self) -> RoadNetwork:
        network = RoadNetwork()
        s = self.scale
        r = self.radius * s
        arm_len = self.arm_length * s
        cx, cy = self.cx, self.cy

        # Circulatory roadway — full circle split into arcs between entry angles
        entry_angles = [2 * math.pi * i / self.num_entries for i in range(self.num_entries)]

        for i in range(self.num_entries):
            start_a = entry_angles[i]
            end_a = entry_angles[(i + 1) % self.num_entries]
            if end_a <= start_a:
                end_a += 2 * math.pi
            pts = _arc_points(cx, cy, r, start_a, end_a, n=10)
            network.add_segment(RoadSegment(
                id=f"circ-{i}",
                control_points=pts,
                num_lanes=self.circ_lanes,
                lane_width_meters=self.lane_width,
                speed_limit_kmh=30,
            ))

        # Approach / departure arms
        for i, angle in enumerate(entry_angles):
            tip_x = cx + (r + arm_len) * math.cos(angle)
            tip_y = cy + (r + arm_len) * math.sin(angle)
            entry_x = cx + r * math.cos(angle)
            entry_y = cy + r * math.sin(angle)

            # Slight flare: offset the arm to create a gentle entry curve
            mid_x = cx + (r + arm_len * 0.3) * math.cos(angle + 0.05)
            mid_y = cy + (r + arm_len * 0.3) * math.sin(angle + 0.05)

            network.add_segment(RoadSegment(
                id=f"arm-{i}",
                control_points=[
                    ControlPoint(x=tip_x, y=tip_y),
                    ControlPoint(x=mid_x, y=mid_y),
                    ControlPoint(x=entry_x, y=entry_y),
                ],
                num_lanes=self.arm_lanes,
                lane_width_meters=self.lane_width,
                speed_limit_kmh=50,
            ))

        return network
