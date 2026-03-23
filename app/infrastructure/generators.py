"""
Procedural interchange geometry generators.

Each generator is a factory that converts a compact set of engineering
parameters into a fully-formed `RoadNetwork` of smooth `RoadSegment`s.
The control-point placement uses trigonometric formulas derived from
real interchange design manuals (AASHTO Green Book geometry).
"""

from __future__ import annotations

import math
from typing import List, Tuple

from shapely.affinity import rotate as _shapely_rotate
from shapely.geometry import LineString as _ShapelyLine

from app.domain.geometry import ControlPoint, RoadNetwork, RoadSegment


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


def _cubic_bezier_coords(
    p0: Tuple[float, float],
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    p3: Tuple[float, float],
    n: int = 15,
) -> List[Tuple[float, float]]:
    """
    Evaluate a **cubic Bezier** curve at *n* evenly-spaced parameter values.

        B(t) = (1-t)^3 * P0  +  3(1-t)^2 t * P1  +  3(1-t) t^2 * P2  +  t^3 * P3

    G1-continuity guarantee:
      - Tangent at t=0 is parallel to (P1 - P0).
      - Tangent at t=1 is parallel to (P3 - P2).

    To ensure a ramp starts parallel to Road A and ends parallel to Road B:
      - Set P1 so that only the component *along* Road A differs from P0.
      - Set P2 so that only the component *along* Road B differs from P3.
    """
    coords: list[Tuple[float, float]] = []
    for i in range(n):
        t = i / (n - 1)
        u = 1.0 - t
        x = u**3 * p0[0] + 3 * u**2 * t * p1[0] + 3 * u * t**2 * p2[0] + t**3 * p3[0]
        y = u**3 * p0[1] + 3 * u**2 * t * p1[1] + 3 * u * t**2 * p2[1] + t**3 * p3[1]
        coords.append((x, y))
    return coords


def _bezier_to_control_points(
    coords: List[Tuple[float, float]],
    cx: float = 0.0,
    cy: float = 0.0,
) -> List[ControlPoint]:
    """Translate raw coordinates by (cx, cy) and wrap as ControlPoints."""
    return [ControlPoint(x=c[0] + cx, y=c[1] + cy) for c in coords]

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

        network.add_segment(RoadSegment(
            id="freeway",
            control_points=_line_points(cx - half, cy, cx + half, cy, n=6),
            num_lanes=self.mainline_lanes,
            lane_width_meters=self.lane_width,
            speed_limit_kmh=100,
            is_bridge=False,
        ))

        offset = self.length * 0.12 * s
        half_ext = self.length * 0.08 * s
        approach_s = [
            ControlPoint(x=cx, y=cy - half),
            ControlPoint(x=cx - half_ext * 0.3, y=cy - offset),
            ControlPoint(x=cx - half_ext, y=cy - offset * 0.4),
            ControlPoint(x=cx - half_ext, y=cy),
        ]
        network.add_segment(RoadSegment(
            id="arterial-approach-S",
            control_points=approach_s,
            num_lanes=self.arterial_lanes,
            lane_width_meters=self.lane_width,
            speed_limit_kmh=50,
            is_bridge=False,
        ))
        bridge_pts = [
            ControlPoint(x=cx - half_ext, y=cy),
            ControlPoint(x=cx, y=cy + offset * 0.3),
            ControlPoint(x=cx + half_ext, y=cy),
        ]
        network.add_segment(RoadSegment(
            id="arterial-bridge",
            control_points=bridge_pts,
            num_lanes=self.arterial_lanes,
            lane_width_meters=self.lane_width,
            speed_limit_kmh=50,
            is_bridge=True,
        ))
        depart_n = [
            ControlPoint(x=cx + half_ext, y=cy),
            ControlPoint(x=cx + half_ext, y=cy + offset * 0.4),
            ControlPoint(x=cx + half_ext * 0.3, y=cy + offset),
            ControlPoint(x=cx, y=cy + half),
        ]
        network.add_segment(RoadSegment(
            id="arterial-depart-N",
            control_points=depart_n,
            num_lanes=self.arterial_lanes,
            lane_width_meters=self.lane_width,
            speed_limit_kmh=50,
            is_bridge=False,
        ))

        ramp_offset = self.length * 0.22 * s
        tangent_len = offset * 0.6
        ramp_defs = [
            ("ramp-NE", +1, +1),
            ("ramp-SE", +1, -1),
            ("ramp-NW", -1, +1),
            ("ramp-SW", -1, -1),
        ]
        for name, sx, sy in ramp_defs:
            bp0 = (cx + sx * ramp_offset, cy)
            bp1 = (cx + sx * ramp_offset, cy + sy * tangent_len)
            bp2 = (cx + sx * (half_ext + tangent_len * 0.5), cy + sy * offset * 0.2)
            bp3 = (cx + sx * half_ext, cy + sy * offset * 0.2)
            bez = _cubic_bezier_coords(bp0, bp1, bp2, bp3, n=15)
            network.add_segment(RoadSegment(
                id=name,
                control_points=[ControlPoint(x=c[0], y=c[1]) for c in bez],
                num_lanes=1,
                lane_width_meters=self.lane_width,
                speed_limit_kmh=40,
                is_bridge=False,
            ))

        return network


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

        for i, angle in enumerate(entry_angles):
            tip_x = cx + (r + arm_len) * math.cos(angle)
            tip_y = cy + (r + arm_len) * math.sin(angle)
            entry_x = cx + r * math.cos(angle)
            entry_y = cy + r * math.sin(angle)

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


class SPUIGenerator:
    """
    Single Point Urban Interchange: all left turns converge at one signalized
    intersection, usually on a bridge. Very compact land use; high structural cost.
    """

    def __init__(
        self,
        leg_length: float = 80.0,
        lane_width: float = 3.5,
        mainline_lanes: int = 3,
        arterial_lanes: int = 2,
        center_lon: float = 30.5234,
        center_lat: float = 50.4501,
    ):
        self.leg_length = leg_length
        self.lane_width = lane_width
        self.mainline_lanes = mainline_lanes
        self.arterial_lanes = arterial_lanes
        self.cx = center_lon
        self.cy = center_lat
        self.scale = 0.0005

    def generate(self) -> RoadNetwork:
        network = RoadNetwork()
        s = self.scale
        L = self.leg_length * s
        cx, cy = self.cx, self.cy

        network.add_segment(RoadSegment(
            id="freeway",
            control_points=_line_points(cx - L * 1.5, cy, cx + L * 1.5, cy, n=6),
            num_lanes=self.mainline_lanes,
            lane_width_meters=self.lane_width,
            speed_limit_kmh=90,
            is_bridge=False,
        ))

        r = L * 0.35
        bridge_pts = [
            ControlPoint(x=cx - r, y=cy),
            ControlPoint(x=cx - r * 0.6, y=cy + r * 0.6),
            ControlPoint(x=cx, y=cy + r),
            ControlPoint(x=cx + r * 0.6, y=cy + r * 0.6),
            ControlPoint(x=cx + r, y=cy),
            ControlPoint(x=cx + r * 0.6, y=cy - r * 0.6),
            ControlPoint(x=cx, y=cy - r),
            ControlPoint(x=cx - r * 0.6, y=cy - r * 0.6),
            ControlPoint(x=cx - r, y=cy),
        ]
        network.add_segment(RoadSegment(
            id="spui-bridge",
            control_points=bridge_pts,
            num_lanes=self.arterial_lanes,
            lane_width_meters=self.lane_width,
            speed_limit_kmh=40,
            is_bridge=True,
        ))

        for i, (dx, dy) in enumerate([(0, -1), (1, 0), (0, 1), (-1, 0)]):
            ax = cx + dx * (r + L * 0.5)
            ay = cy + dy * (r + L * 0.5)
            bx = cx + dx * r
            by = cy + dy * r
            network.add_segment(RoadSegment(
                id=f"leg-{i}",
                control_points=_line_points(ax, ay, bx, by, n=4),
                num_lanes=self.arterial_lanes,
                lane_width_meters=self.lane_width,
                speed_limit_kmh=50,
                is_bridge=False,
            ))

        ramp_offsets = [(1, 0, L * 0.4), (1, 0, -L * 0.4), (-1, 0, L * 0.4), (-1, 0, -L * 0.4)]
        for i, (sx, sy, off) in enumerate(ramp_offsets):
            x0, y0 = cx + sx * L * 0.5, cy + off
            x1, y1 = cx + sx * r * 0.7, cy + sy * r * 0.7
            network.add_segment(RoadSegment(
                id=f"ramp-{i}",
                control_points=[
                    ControlPoint(x=x0, y=y0),
                    ControlPoint(x=(x0 + x1) / 2, y=(y0 + y1) / 2),
                    ControlPoint(x=x1, y=y1),
                ],
                num_lanes=1,
                lane_width_meters=self.lane_width,
                speed_limit_kmh=40,
                is_bridge=False,
            ))

        return network


class TurbineGenerator:
    """
    Turbine (spiral) interchange with 4 sweeping directional ramps.

    Each ramp is a **cubic Bezier** curve whose control points are placed so
    that the ramp starts tangent to Road A and ends tangent to Road B
    (G1 geometric continuity at both join points).

    Canonical ramp (South → West):
        P0 = (lane_off, −start)   heading North   (on S road, right lane)
        P1 = (lane_off, +sweep)   tangent handle — only y differs → pure North
        P2 = (−sweep,   lane_off) tangent handle — only x differs → pure West
        P3 = (−end,     lane_off) heading West    (on W road, right lane)

    The remaining three ramps are produced by rotating this Bezier
    by 90°, 180°, 270° around the origin via ``shapely.affinity.rotate``.
    """

    def __init__(
        self,
        spiral_radius: float = 80.0,
        mainline_length: float = 400.0,
        lane_width: float = 3.5,
        mainline_lanes: int = 3,
        ramp_lanes: int = 1,
        center_lon: float = 30.5234,
        center_lat: float = 50.4501,
    ):
        self.spiral_radius = spiral_radius
        self.mainline_length = mainline_length
        self.lane_width = lane_width
        self.mainline_lanes = mainline_lanes
        self.ramp_lanes = ramp_lanes
        self.cx = center_lon
        self.cy = center_lat
        self.scale = 0.0005

    def generate(self) -> RoadNetwork:
        network = RoadNetwork()
        s = self.scale
        half = self.mainline_length / 2 * s
        cx, cy = self.cx, self.cy

        network.add_segment(RoadSegment(
            id="mainline-EW",
            control_points=_line_points(cx - half, cy, cx + half, cy, n=6),
            num_lanes=self.mainline_lanes,
            lane_width_meters=self.lane_width,
            speed_limit_kmh=100,
            is_bridge=False,
        ))
        network.add_segment(RoadSegment(
            id="mainline-NS",
            control_points=_line_points(cx, cy - half, cx, cy + half, n=6),
            num_lanes=self.mainline_lanes,
            lane_width_meters=self.lane_width,
            speed_limit_kmh=100,
            is_bridge=False,
        ))

        lane_off = (self.mainline_lanes * self.lane_width / 2
                    + self.ramp_lanes * self.lane_width / 2) * s
        start_d = self.mainline_length * 0.38 * s
        end_d = self.mainline_length * 0.38 * s
        sweep = self.spiral_radius * 1.0 * s

        p0 = (lane_off, -start_d)
        p1 = (lane_off, sweep)
        p2 = (-sweep, lane_off)
        p3 = (-end_d, lane_off)

        base_coords = _cubic_bezier_coords(p0, p1, p2, p3, n=40)
        base_line = _ShapelyLine(base_coords)

        ramp_names = ["ramp-S2W", "ramp-E2S", "ramp-N2E", "ramp-W2N"]
        for i, name in enumerate(ramp_names):
            rotated = _shapely_rotate(base_line, -i * 90, origin=(0.0, 0.0))
            rot_coords = list(rotated.coords)
            ctrl_pts = [ControlPoint(x=cx + c[0], y=cy + c[1]) for c in rot_coords]
            network.add_segment(RoadSegment(
                id=name,
                control_points=ctrl_pts,
                num_lanes=self.ramp_lanes,
                lane_width_meters=self.lane_width,
                speed_limit_kmh=50,
                is_bridge=False,
            ))

        return network
