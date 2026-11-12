"""
Procedural interchange geometry generators.

Each generator turns a few engineering parameters into a `RoadNetwork` of real-scale road
centrelines for one interchange type. Dimensions come from ``app/data/interchange_geometry.py``.

Geometry rules shared by every generator:

* Everything is laid out in local metres around the crossing point. North is +y, and the
  **primary road runs north-south**: it is the road whose direction the planner sets on the map
  with the second click, and ``footprint.rotate`` keeps +y on that bearing. For the three-leg types
  (trumpet, directional T) the primary road is the through road.
* Traffic keeps to the right (Ukraine). A dual carriageway has its northbound carriageway on the
  east side and its eastbound carriageway on the south side. Ramps leave and join a carriageway on
  its right-hand side.
* **Lanes are conserved.** A ramp does not grow out of the side of a carriageway: it *is* the
  carriageway's outer lane (or lanes), which leaves with it, and where a ramp joins it becomes the
  outer lane. Its centreline therefore starts and ends on the centreline of that lane
  (`_Section.ramp_line`), and the lane counts in ``interchange_geometry`` are chosen so that every
  lane of every road goes somewhere. ``app/application/model3d.py`` checks the balance.
* Every centreline is built by `_Path`, a "turtle" that only moves by straights and circular arcs,
  each starting with the heading the previous piece ended on. Ramps are therefore G1-continuous
  (no kinks) by construction, and meet their carriageway tangentially.
* Symmetric interchanges are built for one quadrant (or one half of a ramp) and copied by
  rotation or reflection, so the copies match exactly.
* Each centreline is sampled every `_STEP_M` metres. ``RoadSegment.generate_centreline`` then
  fits a spline through the samples, and at that density the spline cannot overshoot.

Output coordinates are ``center + metres / METRES_PER_COORD``, the convention shared with
``app/domain/geometry.py``. ``app/application/footprint.py`` builds at the origin and scales back
to metres before projecting to a real site.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Sequence, Tuple

from shapely.geometry import LineString, MultiLineString

from app.data import interchange_geometry as dims
from app.domain.geometry import METRES_PER_COORD, ControlPoint, RoadNetwork, RoadSegment

Point = Tuple[float, float]

_STEP_M = 2.0
_HALF_PI = math.pi / 2
_INV_SQRT2 = 1.0 / math.sqrt(2.0)
_QUADRANTS = ("SE", "NE", "NW", "SW")  # canonical SE, then each 90° anticlockwise rotation


# ── Path construction ────────────────────────────────────────────────────────


class _Path:
    """A centreline built from straights and arcs, each tangent to the one before (G1)."""

    def __init__(self, x: float, y: float, heading: float):
        self.x, self.y, self.heading = x, y, heading
        self.points: List[Point] = [(x, y)]

    def straight(self, length: float) -> "_Path":
        if length <= 1e-9:
            return self
        n = max(1, math.ceil(length / _STEP_M))
        dx, dy = math.cos(self.heading), math.sin(self.heading)
        x0, y0 = self.x, self.y
        for i in range(1, n + 1):
            t = length * i / n
            self.points.append((x0 + dx * t, y0 + dy * t))
        self.x, self.y = self.points[-1]
        return self

    def arc(self, radius: float, angle: float) -> "_Path":
        """Turn through *angle* radians (positive = left, anticlockwise) on a circle of *radius*."""
        if abs(angle) <= 1e-12:
            return self
        side = 1.0 if angle > 0 else -1.0
        h0 = self.heading
        cx = self.x - side * radius * math.sin(h0)
        cy = self.y + side * radius * math.cos(h0)
        n = max(2, math.ceil(abs(angle) * radius / _STEP_M))
        for i in range(1, n + 1):
            h = h0 + angle * i / n
            self.points.append((cx + side * radius * math.sin(h), cy - side * radius * math.cos(h)))
        self.x, self.y = self.points[-1]
        self.heading = h0 + angle
        return self


def _rotate_quarter(points: Sequence[Point], k: int) -> List[Point]:
    """Rotate by k × 90° anticlockwise about the origin (exact, no trigonometric rounding)."""
    out = list(points)
    for _ in range(k % 4):
        out = [(-y, x) for x, y in out]
    return out


def _mirror_x(points: Sequence[Point]) -> List[Point]:
    """Reflect east-west (x → -x)."""
    return [(-x, y) for x, y in points]


def _mirror_y(points: Sequence[Point]) -> List[Point]:
    """Reflect north-south (y → -y)."""
    return [(x, -y) for x, y in points]


def _translate(points: Sequence[Point], dx: float, dy: float) -> List[Point]:
    return [(x + dx, y + dy) for x, y in points]


# ── Cross-section ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _Section:
    """Offsets of a dual carriageway, all measured from the road's centre line."""

    lanes: int
    lane_width: float
    median: float
    ramp_width: float

    @property
    def width(self) -> float:
        return self.lanes * self.lane_width

    @property
    def carriageway(self) -> float:
        """Centreline of each carriageway."""
        return self.median / 2 + self.width / 2

    @property
    def edge(self) -> float:
        """Outer edge of each carriageway."""
        return self.median / 2 + self.width

    def lane(self, k: int) -> float:
        """Centreline of lane *k*, counted from the median (1 is the inside lane)."""
        return self.median / 2 + (k - 0.5) * self.lane_width

    @property
    def ramp_line(self) -> float:
        """Centreline of a ramp where it runs on the outer lane(s) it takes off or brings."""
        return self.edge - self.ramp_width / 2


@dataclass
class _Seg:
    id: str
    points: List[Point]
    lanes: int
    kind: str
    speed_kmh: float
    is_bridge: bool = False


def _dual_carriageway(
    name: str, axis: str, section: _Section, start: float, end: float, kind: str, speed: float
) -> List[_Seg]:
    """Two straight one-way carriageways from *start* to *end* along *axis* ('ns' or 'ew')."""
    d = section.carriageway
    if axis == "ns":  # northbound on the east side
        a = _Path(d, start, _HALF_PI).straight(end - start).points
        b = _Path(-d, end, -_HALF_PI).straight(end - start).points
        ids = (f"{name}-NB", f"{name}-SB")
    else:  # eastbound on the south side
        a = _Path(start, -d, 0.0).straight(end - start).points
        b = _Path(end, d, math.pi).straight(end - start).points
        ids = (f"{name}-EB", f"{name}-WB")
    return [
        _Seg(ids[0], a, section.lanes, kind, speed),
        _Seg(ids[1], b, section.lanes, kind, speed),
    ]


def _extent(segs: Sequence[_Seg]) -> float:
    return max(max(abs(x), abs(y)) for s in segs for x, y in s.points)


# ── Ramp shapes (canonical orientation; callers rotate or reflect them) ──────


def _outer_connector(a: float, mid: float, run: float, radius: float) -> List[Point]:
    """
    Right-turn connector in the SE quadrant, from northbound (ramp line x = a) to eastbound
    (ramp line y = -a), passing the diagonal at (mid, -mid).

    Half the ramp is a parallel run, a right curve of up to *radius* through 45°, and a straight
    tangent that reaches the diagonal. The other half is its mirror image in the line y = -x. If
    *mid* is too close for the full radius, the curve tightens instead of overshooting.
    """
    radius = min(radius, max((mid - a) / (1 - _INV_SQRT2), 1.0))
    tangent = max(0.0, (mid - a - radius * (1 - _INV_SQRT2)) / _INV_SQRT2)
    half = _Path(a, 0.0, _HALF_PI).straight(run).arc(radius, -math.pi / 4).straight(tangent).points
    ex, ey = half[-1]
    half = _translate(half, 0.0, -ex - ey)
    return half + [(-y, -x) for x, y in reversed(half[:-1])]


def _clear_outer_connector(
    a: float, run: float, radius: float, obstacles: Sequence[Sequence[Point]], clearance: float
) -> List[Point]:
    """The tightest `_outer_connector` whose centreline stays *clearance* from every obstacle.

    Solved by bisection on where it crosses the diagonal; moving that point outwards only
    moves the connector away from the loops and ramps inside it.
    """
    blocker = MultiLineString([list(o) for o in obstacles])

    def clear(mid: float) -> bool:
        return LineString(_outer_connector(a, mid, run, radius)).distance(blocker) >= clearance

    lo, hi = a + 5.0, a + 50.0
    if clear(lo):
        return _outer_connector(a, lo, run, radius)
    while not clear(hi):
        lo, hi = hi, hi * 1.5
    for _ in range(40):
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if clear(mid) else (mid, hi)
    return _outer_connector(a, hi, run, radius)


def _directional_left(
    a: float, pass_distance: float, run: float, swing_radius: float, turn_radius: float
) -> List[Point]:
    """
    Directional left turn from northbound (ramp line x = a, SE quadrant) to westbound (ramp line
    y = a, NW quadrant), as in a turbine or a stack.

    In right-hand traffic a left turn still leaves to the right. The ramp swings out on a right
    curve through α, then turns left through 45° + α to cross the diagonal y = x heading north-west.
    The second half is the mirror image in y = x. α is solved so that the ramp passes the centre
    at *pass_distance*: about 70 m makes a turbine's spiral, which goes round the far side of the
    centre. A negative distance passes on the near side: about -15 m makes a stack's flyovers,
    which cross over the centre while opposite left turns stay clear of each other.

        x_mid = a + R_s (1 - cos α) - R_t (cos α - 1/√2),   x_mid = pass_distance / √2
    """
    x_mid = pass_distance * _INV_SQRT2
    cos_a = (a + swing_radius + turn_radius * _INV_SQRT2 - x_mid) / (swing_radius + turn_radius)
    alpha = math.acos(min(1.0, max(math.cos(math.radians(60)), cos_a)))
    half = (
        _Path(a, 0.0, _HALF_PI)
        .straight(run)
        .arc(swing_radius, -alpha)
        .arc(turn_radius, math.pi / 4 + alpha)
        .points
    )
    ex, ey = half[-1]
    half = _translate(half, 0.0, ex - ey)
    return half + [(y, x) for x, y in reversed(half[:-1])]


def _corner_connector(a1: float, a2: float, radius: float, run: float) -> List[Point]:
    """Right turn in the SE quadrant on one quarter circle: north on x = a1 to east on y = -a2."""
    return (
        _Path(a1, -(a2 + radius) - run, _HALF_PI)
        .straight(run)
        .arc(radius, -_HALF_PI)
        .straight(run)
        .points
    )


def _terminal_ramp(a: float, x_terminal: float, y_end: float, run: float) -> _Path:
    """
    Service-interchange ramp in the SE quadrant: leaves northbound (ramp line x = a) on a parallel
    lane, then shifts sideways on a reverse curve (two arcs with a tangent between) to the terminal
    line x = *x_terminal*, and runs straight north to *y_end*. Returns the path so the caller can
    continue it into the turns at the terminal.
    """
    shift = x_terminal - a
    alpha = math.radians(dims.TERMINAL_RAMP_ANGLE_DEG)
    radius = dims.TERMINAL_RAMP_RADIUS_M
    if 2 * radius * (1 - math.cos(alpha)) > shift:
        radius = shift / (2 * (1 - math.cos(alpha)))
    tangent = (shift - 2 * radius * (1 - math.cos(alpha))) / math.sin(alpha)
    rise = run + 2 * radius * math.sin(alpha) + tangent * math.cos(alpha)
    approach = dims.TERMINAL_APPROACH_M
    path = _Path(a, y_end - approach - rise, _HALF_PI)
    return path.straight(run).arc(radius, -alpha).straight(tangent).arc(radius, alpha).straight(
        approach
    )


# ── Base class ───────────────────────────────────────────────────────────────


class _Generator:
    """Shared plumbing: subclasses lay out `_Seg`s in metres, this turns them into a network."""

    def __init__(self, lane_width: float, center_lon: float, center_lat: float):
        self.lane_width = lane_width
        self.cx = center_lon
        self.cy = center_lat
        self.scale = 1.0 / METRES_PER_COORD  # coordinate units per metre

    def layout(self) -> List[_Seg]:
        raise NotImplementedError

    def generate(self) -> RoadNetwork:
        network = RoadNetwork()
        for seg in self.layout():
            network.add_segment(RoadSegment(
                id=seg.id,
                control_points=[
                    ControlPoint(x=self.cx + x * self.scale, y=self.cy + y * self.scale)
                    for x, y in seg.points
                ],
                num_lanes=seg.lanes,
                lane_width_meters=self.lane_width,
                speed_limit_kmh=seg.speed_kmh,
                is_bridge=seg.is_bridge,
                kind=seg.kind,
            ))
        return network

    def _section(self, lanes: int, median: float, ramp_lanes: int = dims.RAMP_LANES) -> _Section:
        return _Section(lanes, self.lane_width, median, ramp_lanes * self.lane_width)


def _service_quadrants(se: Sequence[Point]) -> List[Tuple[str, List[Point]]]:
    """A service-interchange ramp in the SE quadrant copied to the other three by reflection."""
    return [
        ("NB-off", list(se)),
        ("NB-on", _mirror_y(se)),
        ("SB-off", _mirror_x(_mirror_y(se))),
        ("SB-on", _mirror_x(se)),
    ]


def _terminal_ramps(
    stem: Sequence[Point], left: Sequence[Point], right: Sequence[Point], stem_lanes: int,
    speeds: Tuple[float, float, float],
) -> List[_Seg]:
    """
    The ramps of a SPUI or a DDI from the three pieces of the north-bound off-ramp (SE quadrant):
    the ramp itself up to its fork, and the left-turn and right-turn roadways that its lanes carry
    on into. Ids: ``ramp-NB-off``, ``ramp-NB-off-left``, ``ramp-NB-off-right``, and so on.
    """
    ramps: List[_Seg] = []
    parts = (("", stem, stem_lanes), ("-left", left, 1), ("-right", right, 1))
    for (suffix, pts, lanes), speed in zip(parts, speeds, strict=True):
        for name, quadrant in _service_quadrants(pts):
            ramps.append(_Seg(f"ramp-{name}{suffix}", quadrant, lanes, "ramp", speed))
    return ramps


# ── System interchanges (freeway × freeway) ──────────────────────────────────


class CloverleafGenerator(_Generator):
    """
    Full four-leg cloverleaf between two freeways.

    Left turns use a 270° loop in the quadrant after the crossing. For example, eastbound traffic
    bound north leaves just past the bridge, loops clockwise and joins northbound just before it.
    Right turns use an outer connector round the outside of the same quadrant's loop. The loop
    radius (60 m by default, for 40 km/h) sets the size of the whole interchange, because each
    connector must clear its loop by a ramp width plus a verge.

    Lanes, per carriageway of three: the outer lane leaves on the connector, a loop brings a
    lane back before the bridge and the next loop takes it away after it (the weaving lane), and
    the far connector brings the third lane back. 3 - 1 + 1 - 1 + 1 = 3.
    """

    def __init__(
        self,
        radius: float = dims.LOOP_RADIUS_M,
        lane_width: float = dims.LANE_WIDTH_M,
        mainline_lanes: int = dims.FREEWAY_LANES,
        ramp_lanes: int = dims.RAMP_LANES,
        mainline_length: float = 0.0,
        center_lon: float = 30.5234,
        center_lat: float = 50.4501,
    ):
        super().__init__(lane_width, center_lon, center_lat)
        self.radius = radius
        self.mainline_lanes = mainline_lanes
        self.ramp_lanes = ramp_lanes
        self.length = mainline_length  # minimum drawn length; the ramps decide the real one

    def layout(self) -> List[_Seg]:
        sec = self._section(self.mainline_lanes, dims.FREEWAY_MEDIAN_M, self.ramp_lanes)
        a, r = sec.ramp_line, self.radius
        # The loop's runs on the outer lanes stop short of the corner so the two never touch.
        run = max(r - sec.ramp_width - dims.RAMP_GAP_M, 0.0)
        loop = (
            _Path(a + r - run, -a, 0.0).straight(run).arc(r, -1.5 * math.pi).straight(run).points
        )
        connector = _clear_outer_connector(
            a, dims.SPEED_CHANGE_RUN_M, dims.OUTER_CONNECTOR_RADIUS_M, [loop],
            sec.ramp_width + dims.RAMP_GAP_M,
        )
        ramps: List[_Seg] = []
        for k, q in enumerate(_QUADRANTS):
            ramps.append(_Seg(f"loop-{q}", _rotate_quarter(loop, k), self.ramp_lanes, "ramp", 40))
            ramps.append(_Seg(
                f"connector-{q}", _rotate_quarter(connector, k), self.ramp_lanes, "ramp", 50,
            ))
        half = max(_extent(ramps) + dims.ROAD_MARGIN_M, self.length / 2)
        return (
            _dual_carriageway("mainline", "ns", sec, -half, half, "mainline", 100)
            + _dual_carriageway("crossroad", "ew", sec, -half, half, "mainline", 100)
            + ramps
        )


class TurbineGenerator(_Generator):
    """
    Turbine (whirlpool) interchange between two freeways.

    Every left turn is a directional ramp that leaves to the right, then spirals anticlockwise
    round the centre on a ring of *spiral_radius*, crossing both freeways on its way to the
    opposite quadrant. The four spirals together make the turbine's pinwheel. Right turns use
    outer connectors, pushed outwards just far enough to clear the spirals.

    Lanes, per carriageway of four: the outer lane leaves on the connector, then the next lane on
    the left turn, two lanes run through, and the two turns arriving from the other freeway bring
    the lanes back in the opposite order. 4 - 1 - 1 + 1 + 1 = 4.
    """

    def __init__(
        self,
        spiral_radius: float = dims.TURBINE_RING_RADIUS_M,
        mainline_length: float = 0.0,
        lane_width: float = dims.LANE_WIDTH_M,
        mainline_lanes: int = dims.WIDE_FREEWAY_LANES,
        ramp_lanes: int = dims.RAMP_LANES,
        center_lon: float = 30.5234,
        center_lat: float = 50.4501,
    ):
        super().__init__(lane_width, center_lon, center_lat)
        self.spiral_radius = spiral_radius
        self.mainline_length = mainline_length
        self.mainline_lanes = mainline_lanes
        self.ramp_lanes = ramp_lanes

    left_speed_kmh = 60

    def layout(self) -> List[_Seg]:
        sec = self._section(self.mainline_lanes, dims.FREEWAY_MEDIAN_M, self.ramp_lanes)
        # The connector leaves first, on the outer lane; the left turn takes the next lane in.
        a = sec.ramp_line
        left = _directional_left(
            a - sec.ramp_width, self.spiral_radius, dims.SPEED_CHANGE_RUN_M,
            dims.DIRECTIONAL_SWING_RADIUS_M, dims.DIRECTIONAL_RADIUS_M,
        )
        lefts = [_rotate_quarter(left, k) for k in range(4)]
        connector = _clear_outer_connector(
            a, dims.SPEED_CHANGE_RUN_M, dims.OUTER_CONNECTOR_RADIUS_M, lefts,
            sec.ramp_width + dims.RAMP_GAP_M,
        )
        ramps: List[_Seg] = []
        for k, q in enumerate(_QUADRANTS):
            ramps.append(_Seg(
                f"left-from-{q}", lefts[k], self.ramp_lanes, "ramp", self.left_speed_kmh, True,
            ))
            ramps.append(_Seg(
                f"connector-{q}", _rotate_quarter(connector, k), self.ramp_lanes, "ramp", 50,
            ))
        half = max(_extent(ramps) + dims.ROAD_MARGIN_M, self.mainline_length / 2)
        return (
            _dual_carriageway("mainline", "ns", sec, -half, half, "mainline", 100)
            + _dual_carriageway("crossroad", "ew", sec, -half, half, "mainline", 100)
            + ramps
        )


class StackGenerator(TurbineGenerator):
    """
    Four-level stack between two freeways.

    The ramps are the same as a turbine's, but each left-turn flyover crosses close to the centre,
    so the four of them cross one another above the two freeways (levels 3 and 4). The
    interchange is more compact than a turbine but needs taller structures.
    """

    def __init__(
        self,
        centre_pass: float = dims.STACK_CENTRE_PASS_M,
        mainline_length: float = 0.0,
        lane_width: float = dims.LANE_WIDTH_M,
        mainline_lanes: int = dims.WIDE_FREEWAY_LANES,
        ramp_lanes: int = dims.RAMP_LANES,
        center_lon: float = 30.5234,
        center_lat: float = 50.4501,
    ):
        # The turbine's ring radius is simply set small enough to cross the centre.
        super().__init__(
            spiral_radius=centre_pass, mainline_length=mainline_length, lane_width=lane_width,
            mainline_lanes=mainline_lanes, ramp_lanes=ramp_lanes,
            center_lon=center_lon, center_lat=center_lat,
        )

    left_speed_kmh = 70


# ── Service interchanges (freeway × arterial) ────────────────────────────────


class DiamondGenerator(_Generator):
    """
    Conventional diamond: a freeway (north-south) under an arterial, with one ramp in each
    quadrant ending at a signalised terminal on the arterial.

    Each ramp leaves the freeway on a parallel lane, moves out to the terminal line on a flat
    reverse curve, and meets the arterial square-on after a straight approach that stores the
    queue.

    Lanes: the freeway's outer lane leaves on the off-ramp and the on-ramp brings it back
    (3 - 1 + 1 = 3). The ramp terminals are plain junctions on a two-lane arterial.
    """

    def __init__(
        self,
        terminal_offset: float = dims.DIAMOND_TERMINAL_OFFSET_M,
        lane_width: float = dims.LANE_WIDTH_M,
        mainline_lanes: int = dims.FREEWAY_LANES,
        arterial_lanes: int = dims.ARTERIAL_LANES,
        center_lon: float = 30.5234,
        center_lat: float = 50.4501,
    ):
        super().__init__(lane_width, center_lon, center_lat)
        self.terminal_offset = terminal_offset
        self.mainline_lanes = mainline_lanes
        self.arterial_lanes = arterial_lanes

    def layout(self) -> List[_Seg]:
        fwy = self._section(self.mainline_lanes, dims.FREEWAY_MEDIAN_M)
        art = self._section(self.arterial_lanes, dims.ARTERIAL_MEDIAN_M)
        se = _terminal_ramp(
            fwy.ramp_line, self.terminal_offset, -art.edge, dims.SPEED_CHANGE_RUN_M
        ).points
        ramps = [_Seg(f"ramp-{n}", pts, 1, "ramp", 50) for n, pts in _service_quadrants(se)]
        half_fwy = _extent(ramps) + dims.ROAD_MARGIN_M
        half_art = self.terminal_offset + 2 * dims.ROAD_MARGIN_M
        return (
            _dual_carriageway("mainline", "ns", fwy, -half_fwy, half_fwy, "mainline", 100)
            + _dual_carriageway("crossroad", "ew", art, -half_art, half_art, "crossroad", 60)
            + ramps
        )


class SPUIGenerator(_Generator):
    """
    Single-point urban interchange: a compact diamond whose four ramp terminals merge into one
    signalised intersection over the freeway.

    The ramps come in close to the bridge. Each left turn then sweeps through the shared central
    area on a large radius to the far side of the arterial, and opposing left turns pass
    left-to-left without crossing. Right turns peel off just before on a channelised turning
    roadway.

    Lanes. Every ramp has two, one per turn: where an off-ramp forks, its left lane carries on
    into the left turn and its right lane into the right-turn roadway, and an on-ramp is put
    together the same way. The freeway gives its two outer lanes to the off-ramp and gets them
    back from the on-ramp (4 - 2 + 2 = 4). The arterial has a lane per movement: the inside lane
    turns left onto the on-ramp and is refilled by the left turn from the opposite off-ramp, the
    middle lane runs straight through, and the outer lane turns right and is refilled by the
    right turn from the off-ramp.
    """

    def __init__(
        self,
        leg_length: float = 2 * dims.ROAD_MARGIN_M,
        lane_width: float = dims.LANE_WIDTH_M,
        mainline_lanes: int = dims.WIDE_FREEWAY_LANES,
        arterial_lanes: int = dims.TURNING_ARTERIAL_LANES,
        center_lon: float = 30.5234,
        center_lat: float = 50.4501,
    ):
        super().__init__(lane_width, center_lon, center_lat)
        self.leg_length = leg_length  # arterial drawn beyond the right-turn roadways
        self.mainline_lanes = mainline_lanes
        self.arterial_lanes = arterial_lanes

    def layout(self) -> List[_Seg]:
        fwy = self._section(self.mainline_lanes, dims.FREEWAY_MEDIAN_M, dims.TERMINAL_RAMP_LANES)
        art = self._section(self.arterial_lanes, dims.ARTERIAL_MEDIAN_M)
        x_t = max(dims.SPUI_TERMINAL_OFFSET_M, fwy.edge + fwy.ramp_width / 2 + 5.0)
        x_left, x_right = x_t - self.lane_width / 2, x_t + self.lane_width / 2  # the ramp's lanes
        r_left = dims.SPUI_LEFT_TURN_RADIUS_M
        r_right = dims.TERMINAL_RIGHT_TURN_RADIUS_M
        # The left turn is tangent to the ramp's left lane and to the far carriageway's inside lane.
        y_fork = art.lane(1) - r_left
        stem = _terminal_ramp(fwy.ramp_line, x_t, y_fork, dims.SPEED_CHANGE_RUN_M).points
        left = _Path(x_left, y_fork, _HALF_PI).arc(r_left, _HALF_PI).points
        right = (
            _Path(x_right, y_fork, _HALF_PI)
            .straight(-art.ramp_line - r_right - y_fork)
            .arc(r_right, -_HALF_PI)
            .straight(dims.SPEED_CHANGE_RUN_M)
            .points
        )
        ramps = _terminal_ramps(stem, left, right, dims.TERMINAL_RAMP_LANES, (50, 40, 25))
        half_fwy = _extent(ramps) + dims.ROAD_MARGIN_M
        half_art = x_right + r_right + dims.SPEED_CHANGE_RUN_M + self.leg_length
        return (
            _dual_carriageway("mainline", "ns", fwy, -half_fwy, half_fwy, "mainline", 100)
            + _dual_carriageway("crossroad", "ew", art, -half_art, half_art, "crossroad", 60)
            + ramps
        )


class DDIGenerator(_Generator):
    """
    Diverging diamond: the arterial's two carriageways swap sides at a crossover on each side of
    the freeway, so between the crossovers traffic drives on the left. Left turns to and from the
    ramps then need no signal phase of their own: they turn off the arterial's outer side.

    Approaching a crossover the two carriageways flare apart round an island, then each curves
    back through half the crossing angle and they cross on a straight tangent (40° by default,
    FHWA's recommended 40-50°). Between the crossovers they stay apart, on a bridge each, and
    beyond the second crossover they close up again round another island:

        offset beside an island   D = d + (R_f + R_x)(1 - cos β)
        tangent through the crossover, half of it   t = (D - R_x (1 - cos α)) / sin α

    with d the normal carriageway offset, β the flare angle, α half the crossing angle and R_f,
    R_x the flare and crossover radii.

    Lanes. Every ramp has two, one per turn, as in a SPUI, so the freeway gives up and gets back
    two lanes (4 - 2 + 2 = 4). The arterial has three. Its outer lane leaves before the first
    crossover as the right turn onto the on-ramp, so two lanes cross over. Between the crossovers
    the left turn from the off-ramp arrives as an extra lane on the outside (the left, here),
    crosses the bridge and leaves again as the left turn onto the opposite on-ramp; traffic swaps
    between it and the lane beside it on the way. Beyond the second crossover the right turn from
    the off-ramp brings the outer lane back, along the straight side of the island.
    3 - 1 + 1 - 1 + 1 = 3.
    """

    def __init__(
        self,
        crossover_angle_deg: float = dims.DDI_CROSSOVER_ANGLE_DEG,
        length: float = dims.DDI_CROSSOVER_SPACING_M,
        lane_width: float = dims.LANE_WIDTH_M,
        mainline_lanes: int = dims.WIDE_FREEWAY_LANES,
        arterial_lanes: int = dims.TURNING_ARTERIAL_LANES,
        center_lon: float = 30.5234,
        center_lat: float = 50.4501,
    ):
        super().__init__(lane_width, center_lon, center_lat)
        self.crossover_angle = math.radians(crossover_angle_deg)
        self.length = length  # least distance between the two crossover points
        self.mainline_lanes = mainline_lanes
        self.arterial_lanes = arterial_lanes

    def layout(self) -> List[_Seg]:
        fwy = self._section(self.mainline_lanes, dims.FREEWAY_MEDIAN_M, dims.TERMINAL_RAMP_LANES)
        art = self._section(self.arterial_lanes, dims.ARTERIAL_MEDIAN_M)
        r_left, r_right = dims.DDI_LEFT_TURN_RADIUS_M, dims.TERMINAL_RIGHT_TURN_RADIUS_M
        run = dims.SPEED_CHANGE_RUN_M
        half_lane = self.lane_width / 2

        alpha = self.crossover_angle / 2
        beta = math.radians(dims.DDI_FLARE_ANGLE_DEG)
        r_x, r_f = dims.DDI_CROSSOVER_RADIUS_M, dims.DDI_FLARE_RADIUS_M
        wide = art.carriageway + (r_f + r_x) * (1 - math.cos(beta))
        half_tangent = (wide - r_x * (1 - math.cos(alpha))) / math.sin(alpha)
        # From a crossover point to where its curves end, and the length of a flare.
        reach = half_tangent * math.cos(alpha) + r_x * math.sin(alpha)
        flare = (r_f + r_x) * math.sin(beta)

        # The left turn needs its straight run before the bridge, and the crossover curves start
        # at the ramp terminal, so that the right turn passes clear of them.
        x_t = max(
            dims.DDI_TERMINAL_OFFSET_M,
            fwy.edge + dims.RAMP_GAP_M + dims.DDI_MERGE_RUN_M + r_left + half_lane,
        )
        x_left, x_right = x_t - half_lane, x_t + half_lane  # the ramp's two lanes
        x_c = max(self.length / 2, x_t + reach)
        island = run + dims.RAMP_GAP_M  # straight outer side of the island beyond a crossover
        lead = 2 * dims.ROAD_MARGIN_M
        half_art = x_c + reach + island + flare + lead
        eb = (
            _Path(-half_art, -art.carriageway, 0.0)
            .straight(lead)
            .arc(r_f, -beta).arc(r_x, beta).straight(island)
            .arc(r_x, alpha).straight(2 * half_tangent).arc(r_x, -alpha)
            .straight(2 * (x_c - reach))
            .arc(r_x, -alpha).straight(2 * half_tangent).arc(r_x, alpha)
            .straight(island).arc(r_x, beta).arc(r_f, -beta)
            .straight(lead)
            .points
        )
        arterial = [
            _Seg("crossroad-EB", eb, self.arterial_lanes, "crossroad", 50),
            _Seg("crossroad-WB", _rotate_quarter(eb, 2), self.arterial_lanes, "crossroad", 50),
        ]

        # Beside an island or between the crossovers a carriageway's centre is `wide` from the
        # arterial's. The right turns run on its outer lane; the left turns on an extra lane
        # outside it.
        a_right = wide + art.width / 2 - half_lane
        a_left = wide + art.width / 2 + half_lane
        y_fork = -a_left - max(r_left, r_right) - 5.0
        stem = _terminal_ramp(fwy.ramp_line, x_t, y_fork, run).points
        # Left turn onto the westbound carriageway, which runs on the south side between the
        # crossovers: it arrives on its outside and runs straight up to the bridge.
        left = (
            _Path(x_left, y_fork, _HALF_PI)
            .straight(-a_left - r_left - y_fork)
            .arc(r_left, _HALF_PI)
            .straight(x_left - r_left - fwy.edge - dims.RAMP_GAP_M)
            .points
        )
        # Right turn: passes outside the crossover and becomes the eastbound outer lane along the
        # straight side of the island beyond it.
        right = (
            _Path(x_right, y_fork, _HALF_PI)
            .straight(-a_right - r_right - y_fork)
            .arc(r_right, -_HALF_PI)
            .straight(x_c + reach + run - x_right - r_right)
            .points
        )
        ramps = _terminal_ramps(stem, left, right, dims.TERMINAL_RAMP_LANES, (50, 40, 25))
        half_fwy = _extent(ramps) + dims.ROAD_MARGIN_M
        return (
            _dual_carriageway("mainline", "ns", fwy, -half_fwy, half_fwy, "mainline", 100)
            + arterial
            + ramps
        )


# ── Three-leg interchanges ───────────────────────────────────────────────────


def _through_road_north(segs: List[_Seg]) -> List[_Seg]:
    """
    Turn a layout drawn with its through road east-west and its stem to the south through 90°
    anticlockwise. The through road then runs north-south (along the planner's bearing) and the
    stem leaves to the east. Rotation keeps right-hand traffic right-handed. Carriageway ids are
    renamed to their new directions.
    """
    rename = {"EB": "NB", "WB": "SB", "NB": "WB", "SB": "EB"}
    out = []
    for s in segs:
        head, _, tail = s.id.rpartition("-")
        new_id = f"{head}-{rename[tail]}" if tail in rename else s.id
        out.append(_Seg(new_id, _rotate_quarter(s.points, 1), s.lanes, s.kind, s.speed_kmh,
                        s.is_bridge))
    return out


class TrumpetGenerator(_Generator):
    """
    Trumpet: a three-leg interchange where a stem road ends at a freeway.

    The stem crosses the freeway on a bridge and opens into the trumpet's "bell" on the far side.
    One left turn is a 270° loop (freeway to stem), the other a semi-direct ramp that wraps round
    the loop concentrically and drops onto the freeway well downstream. The two right turns are
    single-curve connectors on the stem side.

    Lanes. The stem has two each way, one per turn: outbound, its outer lane leaves on the
    right-turn connector and its inside lane carries on over the bridge into the semi-direct
    ramp; inbound, the loop arrives as the inside lane and the other connector brings the outer
    one. Each carriageway of the through road gives its outer lane to a ramp and gets it back
    from the next (3 - 1 + 1 = 3).
    """

    def __init__(
        self,
        radius: float = dims.LOOP_RADIUS_M,
        lane_width: float = dims.LANE_WIDTH_M,
        mainline_lanes: int = dims.FREEWAY_LANES,
        stem_lanes: int = dims.STEM_LANES,
        ramp_lanes: int = dims.RAMP_LANES,
        center_lon: float = 30.5234,
        center_lat: float = 50.4501,
    ):
        super().__init__(lane_width, center_lon, center_lat)
        self.radius = radius
        self.mainline_lanes = mainline_lanes
        self.stem_lanes = stem_lanes
        self.ramp_lanes = ramp_lanes

    def layout(self) -> List[_Seg]:
        # Drawn with the through road east-west and the stem from the south, then turned.
        thr = self._section(self.mainline_lanes, dims.FREEWAY_MEDIAN_M, self.ramp_lanes)
        stem = self._section(self.stem_lanes, dims.FREEWAY_MEDIAN_M, self.ramp_lanes)
        a, d_s, r = thr.ramp_line, stem.carriageway, self.radius
        x_lane = stem.lane(1)  # the stem's inside lane: the loop ends on it, the semi-direct starts
        run = dims.SPEED_CHANGE_RUN_M

        # Loop: westbound's outer lane leaves on the north side, passes under the stem and turns
        # clockwise 270° to run south as the inside lane of the stem's southbound carriageway.
        x_loop = -x_lane - r
        x_div = stem.ramp_line + run
        loop = _Path(x_div, a, math.pi).straight(x_div - x_loop).arc(r, -1.5 * math.pi).points

        # Semi-direct: the inside lane of the stem's northbound carriageway curves left round the
        # loop, concentric with it, then reverses onto westbound. cos β = (R3 - R) / (R2 + R3).
        r2, r3 = r + 2 * x_lane, dims.DIRECTIONAL_SWING_RADIUS_M
        beta = math.acos((r3 - r) / (r2 + r3))
        semi = (
            _Path(x_lane, a + r, _HALF_PI)
            .arc(r2, _HALF_PI + beta).arc(r3, -beta).straight(run).points
        )

        corner = _corner_connector(stem.ramp_line, a, dims.OUTER_CONNECTOR_RADIUS_M, run)
        ramps = [
            _Seg("loop", loop, self.ramp_lanes, "ramp", 40),
            _Seg("ramp-semi-direct", semi, self.ramp_lanes, "ramp", 60, True),
            _Seg("connector-stem-out", corner, self.ramp_lanes, "ramp", 50),
            _Seg("connector-stem-in", _mirror_x(corner), self.ramp_lanes, "ramp", 50),
        ]
        half = _extent(ramps) + dims.ROAD_MARGIN_M
        stem_end = -max(dims.STEM_LENGTH_M, _extent(ramps[2:]) + dims.ROAD_MARGIN_M)
        stem_segs = [
            _Seg("stem-NB", _Path(d_s, stem_end, _HALF_PI).straight(a + r - stem_end).points,
                 self.stem_lanes, "crossroad", 80),
            _Seg("stem-SB", _Path(-d_s, a + r, -_HALF_PI).straight(a + r - stem_end).points,
                 self.stem_lanes, "crossroad", 80),
        ]
        through = _dual_carriageway("mainline", "ew", thr, -half, half, "mainline", 100)
        return _through_road_north(through + stem_segs + ramps)


class DirectionalTGenerator(_Generator):
    """
    Directional T (fully directional three-leg interchange) between two freeways.

    Both left turns are flyovers that start where the stem's carriageways split. They curve
    across the through road on the diagonal, cross each other above its centre and join the
    through road from the right. The two right turns are single-curve connectors.

    Lanes. The terminating freeway comes in on two lanes each way, one per turn: its outer lane
    leaves on the right-turn connector and its inside lane carries on into the flyover (and the
    reverse inbound). Each carriageway of the through road gives its outer lane to a ramp and
    gets it back from the next (3 - 1 + 1 = 3).
    """

    def __init__(
        self,
        lane_width: float = dims.LANE_WIDTH_M,
        mainline_lanes: int = dims.FREEWAY_LANES,
        stem_lanes: int = dims.STEM_LANES,
        ramp_lanes: int = dims.RAMP_LANES,
        center_lon: float = 30.5234,
        center_lat: float = 50.4501,
    ):
        super().__init__(lane_width, center_lon, center_lat)
        self.mainline_lanes = mainline_lanes
        self.stem_lanes = stem_lanes
        self.ramp_lanes = ramp_lanes

    def layout(self) -> List[_Seg]:
        sec = self._section(self.mainline_lanes, dims.FREEWAY_MEDIAN_M, self.ramp_lanes)
        stem = self._section(self.stem_lanes, dims.FREEWAY_MEDIAN_M, self.ramp_lanes)
        a, d = sec.ramp_line, stem.carriageway
        run = dims.SPEED_CHANGE_RUN_M
        split = dims.DIRECTIONAL_T_SPLIT_M
        r_l, r3 = dims.DIRECTIONAL_RADIUS_M, dims.DIRECTIONAL_SWING_RADIUS_M
        # The stem's inside lane carries on from its end at y = -split: a left arc heading north,
        # then a reverse curve onto y = a heading west. cos β = (a + split + R3) / (R_l + R3).
        beta = math.acos((a + split + r3) / (r_l + r3))
        flyover = _Path(stem.lane(1), -split, _HALF_PI).arc(r_l, _HALF_PI + beta).arc(r3, -beta)
        flyover = flyover.straight(run).points
        corner = _corner_connector(stem.ramp_line, a, dims.OUTER_CONNECTOR_RADIUS_M, run)
        ramps = [
            _Seg("flyover-stem-out", flyover, self.ramp_lanes, "ramp", 70, True),
            _Seg("flyover-stem-in", _mirror_x(flyover), self.ramp_lanes, "ramp", 70, True),
            _Seg("connector-stem-out", corner, self.ramp_lanes, "ramp", 50),
            _Seg("connector-stem-in", _mirror_x(corner), self.ramp_lanes, "ramp", 50),
        ]
        half = _extent(ramps) + dims.ROAD_MARGIN_M
        stem_end = -max(dims.STEM_LENGTH_M, _extent(ramps[2:]) + dims.ROAD_MARGIN_M)
        stem_segs = [
            _Seg("stem-NB", _Path(d, stem_end, _HALF_PI).straight(-split - stem_end).points,
                 self.stem_lanes, "mainline", 100),
            _Seg("stem-SB", _Path(-d, -split, -_HALF_PI).straight(-split - stem_end).points,
                 self.stem_lanes, "mainline", 100),
        ]
        through = _dual_carriageway("mainline", "ew", sec, -half, half, "mainline", 100)
        return _through_road_north(through + stem_segs + ramps)


# ── At-grade (legacy view only) ──────────────────────────────────────────────


class RoundaboutGenerator(_Generator):
    """
    Circular roundabout with *num_entries* evenly spaced radial arms.

    The circulatory carriageway is split into one arc per gap between arms. Each arm is a
    straight radial road ending at the ring's outer edge.
    """

    def __init__(
        self,
        radius: float = dims.ROUNDABOUT_RADIUS_M,
        num_entries: int = 4,
        arm_length: float = dims.ROUNDABOUT_ARM_LENGTH_M,
        lane_width: float = dims.LANE_WIDTH_M,
        circulatory_lanes: int = 2,
        arm_lanes: int = 2,
        center_lon: float = 30.5234,
        center_lat: float = 50.4501,
    ):
        super().__init__(lane_width, center_lon, center_lat)
        self.radius = radius
        self.num_entries = num_entries
        self.arm_length = arm_length
        self.circ_lanes = circulatory_lanes
        self.arm_lanes = arm_lanes

    def layout(self) -> List[_Seg]:
        n, r = self.num_entries, self.radius
        gap = 2 * math.pi / n
        segs: List[_Seg] = []
        for i in range(n):
            theta = i * gap
            start = (r * math.cos(theta), r * math.sin(theta))
            ring = _Path(*start, theta + _HALF_PI).arc(r, gap).points
            segs.append(_Seg(f"circ-{i}", ring, self.circ_lanes, "crossroad", 30))
        inner = r + self.circ_lanes * self.lane_width / 2
        for i in range(n):
            theta = i * gap
            arm = _Path(inner * math.cos(theta), inner * math.sin(theta), theta)
            segs.append(_Seg(f"arm-{i}", arm.straight(self.arm_length).points, self.arm_lanes,
                             "crossroad", 50))
        return segs
