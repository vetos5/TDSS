"""
3-D model of a catalogue interchange.

The generators (``app/infrastructure/generators.py``) give each interchange type as plan
centrelines at real scale. This module adds the third dimension: a height for every point of every
centreline, the piers under the elevated decks and the direction of travel, so the frontend only
has to draw the result.

The vertical profile is schematic (see ``app/data/interchange_geometry.py``) and is built in
three steps.

1. **Roads.** A mainline, crossroad or stem of rank *k* in ``VERTICAL_ORDER`` is level at
   ``k · LEVEL_STEP_M`` over everything it bridges and comes down to the ground on a smooth
   approach. Its height depends only on the distance from the interchange centre, so the two
   carriageways of a road stay side by side.

2. **Ramps.** A ramp is pinned to the road it leaves and the road it joins for as long as it runs
   on their lane. In between it gets a level stretch ("knot") at every crossing; where a two-lane
   ramp forks into its turning roadways, the fork is one more unknown height. The knot and fork
   heights are the solution of a small linear programme:

       minimise    G + ε₁ · Σ u_k + ε₂ · Σ z_k
       subject to  z_upper − z_lower ≥ LEVEL_STEP_M      at every grade-separated crossing
                   z_a = z_b                              at every at-grade crossing
                   |z_{k+1} − z_k| ≤ u_k,  p · u_k ≤ G · d_k   between consecutive knots of a ramp
                   z_k ≥ 0

   *G* is the steepest gradient anywhere in the interchange, so the solution is the profile with
   the gentlest possible steepest ramp. The two small ε terms then pick, among those, the profile
   that rises and falls least (no roller coasters) and, last, the lowest one.

   Between knots the ramp follows a parabolic vertical curve, a tangent grade and a second
   vertical curve. Its steepest slope is p = 4/3 of its average slope, which is the factor in
   the gradient constraint.

3. **Piers** go under every deck higher than ``PIER_MIN_HEIGHT_M``, spaced along it and moved
   off any road that passes underneath.

4. **Lanes** ("lane mathematics"). Lanes are conserved: a ramp is the outer lane of the
   carriageway it leaves and becomes the outer lane of the one it joins (the plan puts its ends on
   the centreline of that lane). Every ramp end that lies on a lane of a road is an *event* there:
   the lane leaves the road (a diverge) or arrives on it (a merge). The events give

   * the pavement edges: a carriageway is one lane narrower between a diverge and the next merge,
     and one wider where a ramp brings an auxiliary lane. Building fails if a ramp would take a
     lane that is not there or bring one that already is, so an unbalanced plan cannot be drawn;
   * what each edge is: *free* (the edge of the road: an edge line, and a parapet when the road
     is elevated), *median* (the other carriageway of the same road is less than
     ``MEDIAN_FILL_MAX_M`` away, so the two share one deck), *shared* (a lane of another road
     runs alongside at the same level: a broken line, no barrier) or *open* (the pavement
     continues into another road: a fork, a ramp terminal, a SPUI's intersection, a DDI's
     crossover: neither);
   * the *routes*: each lane followed from where it enters the interchange to where it leaves,
     across the ramps that carry it from road to road. No two routes share a lane.

   An auxiliary lane (brought by one ramp, taken by the next: the weaving lane between a
   cloverleaf's loops) swaps with the lane beside it, so that traffic from a loop joins the
   through lanes instead of circling onto the next loop.

5. **Traffic.** Every route releases a car each ``TRAFFIC_HEADWAY_S``. Where two routes cross at
   one level (a weave, a DDI's crossover, a SPUI's intersection) their release times are offset
   so that the cars pass between one another: a coordinate search over the routes' phases that
   maximises the smallest time gap at any crossing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np
import shapely
from scipy.optimize import linprog
from shapely.geometry import LineString

from app.application.footprint import FOOTPRINT_GENERATORS
from app.data import interchange_geometry as dims

_EPS_UNDULATION = 1e-5    # LP weight of a metre of rise or fall, against the steepest gradient
_EPS_HEIGHT = 1e-7        # LP weight of a metre of height: the last tie-breaker
_MIN_GAP_M = 2.0          # knots closer than this are merged into one level stretch
_CONTACT_M = 1.5          # two ramps this close at an end are a fork or a merge, not a crossing
_OUTPUT_STEP = 2          # keep every n-th 2 m sample in the output
_SAME_LEVEL_M = 0.5       # two surfaces closer than this in height are one pavement
_EDGE_TOL_M = 0.6         # an edge this close to another road's edge touches it
_PARALLEL = 0.35          # sine of the largest angle between two lanes that run alongside
_JUNCTION_MARGIN_M = 2.0  # lane lines stop this far before a road that crosses at grade
_MIN_MERGE_RUN_M = 20.0   # a ramp alongside for less than this meets its road at a junction
_ON_LANE_M = 0.5          # a ramp end this close to a lane's centreline is on that lane
_STRAIGHT_ON = 0.95       # cosine of the largest angle between a ramp end and the lane it is on
_RUN_DRIFT_M = 0.3        # a ramp runs along a lane while it stays this close to its line
_PIN_DRIFT_M = 1.0        # and shares the road's height until it has moved this far off it
_LINK_M = 0.75            # two lane pieces whose ends are this close are one lane
_ROUTE_TOL_M = 0.04       # largest error of a simplified route, in position at a given time
_PHASE_STEPS = 24         # release phases tried per route, as fractions of the headway

FREE, MEDIAN, SHARED, OPEN = "f", "m", "s", "o"
_CODES = FREE + MEDIAN + SHARED + OPEN   # in rising order: the later one wins where two apply


@dataclass(frozen=True)
class Segment3D:
    id: str
    kind: str
    lanes: int
    width_m: float
    speed_kmh: float
    points: tuple[tuple[float, float, float], ...]  # x east, y north, z up; in travel direction
    # Per point, looking in the travel direction: distance from the centreline to each pavement
    # edge, what each edge is (one of FREE, MEDIAN, SHARED, OPEN per point), and whether lane
    # lines are drawn there ("1") or the point is inside a junction ("0").
    left_m: tuple[float, ...] = ()
    right_m: tuple[float, ...] = ()
    edge_left: str = ""
    edge_right: str = ""
    marks: str = ""
    # The road carries on beyond the model at its first / last point (a freeway leaving the
    # interchange), as opposed to ending at a ramp or a junction.
    open_start: bool = False
    open_end: bool = False


@dataclass(frozen=True)
class Route3D:
    """One lane, followed from where it enters the interchange to where it leaves."""

    id: str
    points: tuple[tuple[float, float, float, float], ...]  # x, y, z, seconds from the start
    phase_s: float     # a car passes the first point at phase_s + k * headway, for every integer k
    open_start: bool   # the lane arrives from beyond the model / carries on beyond it
    open_end: bool


@dataclass(frozen=True)
class Pier:
    x: float
    y: float
    top_m: float
    width_m: float


@dataclass(frozen=True)
class Model3D:
    name: str
    segments: tuple[Segment3D, ...]
    piers: tuple[Pier, ...]
    extent_m: float        # half the side of the square the plan fits in
    level_step_m: float
    levels: int            # how many levels the interchange has, the ground included
    max_height_m: float
    max_grade: float       # steepest gradient of any segment, as a fraction
    routes: tuple[Route3D, ...] = ()
    headway_s: float = 0.0  # time between two cars of a route


# ── Working representation ───────────────────────────────────────────────────


@dataclass
class _Line:
    id: str
    kind: str
    lanes: int
    width: float
    speed: float
    flyover: bool
    rank: int
    xy: np.ndarray                     # (n, 2) plan samples
    s: np.ndarray = field(init=False)  # arc length at each sample
    line: LineString = field(init=False)
    z: np.ndarray | None = None
    pin_lo: float = 0.0                # the ramp is free between these two arc lengths
    pin_hi: float = 0.0
    fork: tuple = (None, None)         # LP variable of a start / end that meets other ramps
    reverse: bool = False              # samples run against the traffic (until `_with_traffic`)
    keep: np.ndarray | None = None     # indices of the samples that go into the output
    left: np.ndarray | None = None     # centreline to left pavement edge, per sample
    right: np.ndarray | None = None
    median_left: np.ndarray | None = None  # the edge faces a narrow median, per sample
    median_right: np.ndarray | None = None
    edge_left: np.ndarray | None = None   # index into _CODES, per sample
    edge_right: np.ndarray | None = None
    marks: np.ndarray | None = None       # lane lines drawn at this sample
    open_start: bool = False              # the road carries on beyond the model at this end
    open_end: bool = False

    def tangents(self) -> np.ndarray:
        """Unit direction at each sample, (n, 2)."""
        d = np.gradient(self.xy, axis=0)
        return d / np.maximum(np.hypot(d[:, 0], d[:, 1]), 1e-9)[:, None]

    def __post_init__(self) -> None:
        step = np.hypot(*np.diff(self.xy, axis=0).T)
        self.s = np.concatenate([[0.0], np.cumsum(step)])
        self.line = LineString(self.xy)

    @property
    def is_ramp(self) -> bool:
        return self.kind == "ramp"

    @property
    def length(self) -> float:
        return float(self.s[-1])

    def height_at(self, s: float) -> float:
        return float(np.interp(s, self.s, self.z))

    def height_near(self, x: float, y: float) -> float:
        return self.height_at(self.line.project(shapely.Point(x, y)))

    def heading_at(self, s: float) -> tuple[float, float]:
        i = int(np.clip(np.searchsorted(self.s, s), 1, len(self.s) - 1))
        dx, dy = self.xy[i] - self.xy[i - 1]
        n = math.hypot(dx, dy) or 1.0
        return dx / n, dy / n


@dataclass(frozen=True)
class _Crossing:
    a: _Line
    b: _Line
    x: float
    y: float
    sa: float
    sb: float


def _rank(order: dict[str, int], seg_id: str) -> int:
    best = max((p for p in order if seg_id.startswith(p)), key=len, default=None)
    return order[best] if best is not None else 0


_CURVE_SHARE = 0.25                      # share of a transition taken by each vertical curve
_PEAK_SLOPE = 1.0 / (1.0 - _CURVE_SHARE)  # steepest slope of a transition over its average


def _ease(t):
    """
    Transition from 0 to 1 the way a road profile is designed: a parabolic vertical curve, a
    straight tangent grade, and a second parabolic curve. The slope is continuous, and its
    maximum (on the tangent) is `_PEAK_SLOPE` times the average.
    """
    t = np.clip(np.asarray(t, dtype=float), 0.0, 1.0)
    b = _CURVE_SHARE
    curve = t * t / (2 * b * (1 - b))
    tangent = (t - b / 2) / (1 - b)
    sag = 1 - (1 - t) ** 2 / (2 * b * (1 - b))
    return np.where(t < b, curve, np.where(t <= 1 - b, tangent, sag))


def _crossings(lines: list[_Line]) -> list[_Crossing]:
    out: list[_Crossing] = []
    for i, a in enumerate(lines):
        for b in lines[i + 1:]:
            inter = a.line.intersection(b.line)
            if inter.is_empty:
                continue
            for g in getattr(inter, "geoms", [inter]):
                if g.geom_type == "Point":  # collinear overlaps (a fork's shared stem) are not
                    out.append(_Crossing(a, b, g.x, g.y, a.line.project(g), b.line.project(g)))
    return out


# ── Step 1: roads ────────────────────────────────────────────────────────────


def _road_profile(road: _Line, crossings: list[_Crossing]) -> np.ndarray:
    """Height of a road: level over what it bridges, then down to the ground on an approach."""
    r = np.hypot(road.xy[:, 0], road.xy[:, 1])
    if road.rank == 0:
        return np.zeros(len(r))
    top = road.rank * dims.LEVEL_STEP_M
    bridged = [
        math.hypot(c.x, c.y) + (c.b if c.a is road else c.a).width / 2
        for c in crossings
        if road in (c.a, c.b) and (c.b if c.a is road else c.a).rank <= road.rank
    ]
    ends = (float(r[0]), float(r[-1]))
    plateau = max(bridged) + dims.PLATEAU_MARGIN_M if bridged else min(ends)
    approach = min(_PEAK_SLOPE * top / dims.APPROACH_GRADE, max(ends) - plateau)
    if approach <= 0:
        return np.full(len(r), top)
    return top * (1.0 - _ease((r - plateau) / approach))


# ── Step 2: ramps ────────────────────────────────────────────────────────────


def _pin_run(dist: np.ndarray, tol: float, from_start: bool) -> int:
    """How many samples, counted from one end, stay within *tol* of the line they are pinned to."""
    near = dist <= tol if from_start else dist[::-1] <= tol
    return len(near) if near.all() else int(np.argmin(near))


def _locate(road: _Line, xy: np.ndarray):
    """
    Where the points *xy* are relative to *road*: arc length of the nearest point of its
    centreline, offset to its left, how far they lie beyond its end, and its direction there.
    """
    where = shapely.line_locate_point(road.line, shapely.points(xy))
    foot = shapely.get_coordinates(shapely.line_interpolate_point(road.line, where))
    j = np.clip(np.searchsorted(road.s, where), 1, len(road.s) - 1)
    d = road.xy[j] - road.xy[j - 1]
    t = d / np.maximum(np.hypot(d[:, 0], d[:, 1]), 1e-9)[:, None]
    rel = xy - foot
    left = t[:, 0] * rel[:, 1] - t[:, 1] * rel[:, 0]
    beyond = t[:, 0] * rel[:, 0] + t[:, 1] * rel[:, 1]
    return where, left, beyond, t


def _samples_alongside(ramp: _Line, road: _Line, from_end: bool, drift: float) -> int:
    """How many samples of *ramp*, counted from one end, keep their sideways offset from *road*."""
    where, left, _, _ = _locate(road, ramp.xy)
    tip = len(ramp.s) - 1 if from_end else 0
    on = (
        (np.abs(left - left[tip]) <= drift)
        & (where > 1e-6) & (where < road.length - 1e-6)
    )
    return _pin_run(np.where(on, 0.0, 1.0), 0.5, not from_end)


def _pin(ramp: _Line, roads: list[_Line]):
    """
    Find the road each end of *ramp* is on. Returns, for the start and the end, the road (or None)
    and how many samples from that end run alongside it.
    """
    pts = shapely.points(ramp.xy)
    result = []
    for from_start in (True, False):
        tip = pts[0] if from_start else pts[-1]
        best, best_d = None, math.inf
        for road in roads:
            d = road.line.distance(tip)
            if d <= (road.width + ramp.width) / 2 + 1.0 and d < best_d:
                best, best_d = road, d
        # Alongside: for as long as it has not moved sideways, off the lane it starts or ends on.
        run = max(_samples_alongside(ramp, best, not from_start, _PIN_DRIFT_M), 1) if best else 1
        result.append((best, run))
    return result


def _forks(ramps: list[_Line], pinned: dict) -> int:
    """
    Group the ramp ends that meet each other and no road (a two-lane ramp forking into its two
    turning roadways): each group is one point, whose height the linear programme chooses. Sets
    ``fork`` on every ramp and returns the number of groups.
    """
    ends = [
        (r, k) for r in ramps for k in (0, 1)
        if pinned[id(r)][k][0] is None
    ]
    group = list(range(len(ends)))

    def find(i: int) -> int:
        while group[i] != i:
            i = group[i]
        return i

    for i, (a, ka) in enumerate(ends):
        for j, (b, kb) in enumerate(ends[:i]):
            reach = max(_CONTACT_M, abs(a.width - b.width) / 2 + 0.5)
            if a is not b and math.dist(a.xy[-ka], b.xy[-kb]) <= reach:
                group[find(i)] = find(j)
    roots = sorted({find(i) for i in range(len(ends))})
    for i, (r, k) in enumerate(ends):
        fork = list(r.fork)
        fork[k] = roots.index(find(i))
        r.fork = tuple(fork)
    return len(roots)


def _relation(a: _Line, b: _Line, sa: float, sb: float) -> int:
    """+1 if *a* passes over *b* where they cross, -1 if under, 0 if they meet at grade."""
    if a.rank != b.rank:
        return 1 if a.rank > b.rank else -1
    if a.is_ramp and b.is_ramp and a.flyover and b.flyover:
        fa, fb = sa / a.length, sb / b.length
        if abs(fa - fb) > 1e-6:
            return 1 if fa > fb else -1
        return 1 if a.id > b.id else -1
    return 0


@dataclass
class _Knot:
    lo: float
    hi: float
    var: int = -1


def _solve_ramps(ramps: list[_Line], crossings: list[_Crossing], n_forks: int) -> None:
    """Set ``z`` on every ramp; every other line in *crossings* must already have it."""
    solving = {id(r) for r in ramps}
    knots: dict[int, list[_Knot]] = {id(r): [] for r in ramps}
    at: dict[tuple[int, int], _Knot] = {}  # (ramp, crossing index) -> its knot

    for n, c in enumerate(crossings):
        for me, other, s in ((c.a, c.b, c.sa), (c.b, c.a, c.sb)):
            if id(me) not in solving or not me.pin_lo < s < me.pin_hi:
                continue
            ca, cb = me.heading_at(s), other.heading_at(c.sb if me is c.a else c.sa)
            skew = max(abs(ca[0] * cb[1] - ca[1] * cb[0]), 0.5)
            half = other.width / 2 / skew + dims.CROSSING_MARGIN_M
            k = _Knot(max(s - half, me.pin_lo + _MIN_GAP_M), min(s + half, me.pin_hi - _MIN_GAP_M))
            knots[id(me)].append(k)
            at[(id(me), n)] = k

    # Merge overlapping level stretches of one ramp, then number the survivors as LP variables,
    # after the fork heights.
    n_vars = n_forks
    for r in ramps:
        merged: list[_Knot] = []
        for k in sorted(knots[id(r)], key=lambda k: k.lo):
            if merged and k.lo <= merged[-1].hi + _MIN_GAP_M:
                merged[-1].hi = max(merged[-1].hi, k.hi)
                k.var = merged[-1].var
            else:
                k.var = n_vars
                n_vars += 1
                merged.append(k)
        for k in knots[id(r)]:  # a knot merged into an earlier one shares its extent
            owner = next(m for m in merged if m.var == k.var)
            k.lo, k.hi = owner.lo, owner.hi
        knots[id(r)] = merged

    def end_nodes(r: _Line):
        """The two ends of the free stretch of *r*: (variable or None, known height, arc length)."""
        return [
            (fork, 0.0 if fork is not None else r.height_at(s), s)
            for fork, s in zip(r.fork, (r.pin_lo, r.pin_hi), strict=True)
        ]

    heights = np.zeros(n_vars)
    if n_vars:
        # Variables: the fork and knot heights, then G, then one "rise or fall" u per gap between
        # consecutive nodes.
        gaps = []  # (v1, z1, v2, z2, length) for each pair of consecutive nodes of a ramp
        for r in ramps:
            (v0, z0, s0), (v1, z1, s1) = end_nodes(r)
            nodes = [(v0, z0, s0, s0)]
            nodes += [(k.var, 0.0, k.lo, k.hi) for k in knots[id(r)]]
            nodes += [(v1, z1, s1, s1)]
            for (v1, z1, _, hi1), (v2, z2, lo2, _) in zip(nodes, nodes[1:], strict=False):
                if v1 is not None or v2 is not None:
                    gaps.append((v1, z1, v2, z2, max(lo2 - hi1, 1.0)))
        g = n_vars
        size = n_vars + 1 + len(gaps)
        a_ub, b_ub, a_eq, b_eq = [], [], [], []

        def term(line: _Line, n: int, s: float):
            """Height of *line* at crossing *n*: an LP variable, or a known number."""
            k = at.get((id(line), n))
            if k is not None:
                return k.var, 0.0
            return None, line.height_at(s)

        def difference(v1, z1, v2, z2, sign):
            """The row and constant of sign * (z2 - z1), with known heights moved to the right."""
            row, const = np.zeros(size), 0.0
            if v2 is not None:
                row[v2] += sign
            else:
                const -= sign * z2
            if v1 is not None:
                row[v1] -= sign
            else:
                const += sign * z1
            return row, const

        for n, c in enumerate(crossings):
            (va, za), (vb, zb) = term(c.a, n, c.sa), term(c.b, n, c.sb)
            if va is None and vb is None:
                continue
            rel = _relation(c.a, c.b, c.sa, c.sb)
            if rel == 0:  # z_a = z_b
                row, const = difference(va, za, vb, zb, 1.0)
                a_eq.append(row)
                b_eq.append(const)
            else:  # the upper one clears the lower one: z_low - z_up <= -step
                row, const = difference(va, za, vb, zb, 1.0 if rel > 0 else -1.0)
                a_ub.append(row)
                b_ub.append(const - dims.LEVEL_STEP_M)

        for i, (v1, z1, v2, z2, length) in enumerate(gaps):
            for sign in (1.0, -1.0):
                row, const = difference(v1, z1, v2, z2, sign)  # sign * (z2 - z1) <= u
                row[n_vars + 1 + i] = -1.0
                a_ub.append(row)
                b_ub.append(const)
            row = np.zeros(size)  # p * u <= G * length
            row[n_vars + 1 + i] = _PEAK_SLOPE
            row[g] = -length
            a_ub.append(row)
            b_ub.append(0.0)

        cost = np.full(size, _EPS_UNDULATION)
        cost[:n_vars] = _EPS_HEIGHT
        cost[g] = 1.0
        res = linprog(
            cost,
            A_ub=np.array(a_ub), b_ub=np.array(b_ub),
            A_eq=np.array(a_eq) if a_eq else None, b_eq=np.array(b_eq) if b_eq else None,
            bounds=[(0, None)] * size, method="highs",
        )
        if not res.success:
            raise ValueError(f"no vertical profile satisfies the clearances: {res.message}")
        heights = res.x[:n_vars]

    for r in ramps:
        (v0, z0, s0), (v1, z1, s1) = end_nodes(r)
        nodes = [(s0, s0, float(heights[v0]) if v0 is not None else z0)]
        nodes += [(k.lo, k.hi, float(heights[k.var])) for k in knots[id(r)]]
        nodes += [(s1, s1, float(heights[v1]) if v1 is not None else z1)]
        z = r.z.copy()
        free = (r.s >= r.pin_lo) & (r.s <= r.pin_hi)
        for (_, hi1, z1), (lo2, hi2, z2) in zip(nodes, nodes[1:], strict=False):
            span = free & (r.s >= hi1) & (r.s <= hi2)
            t = (r.s[span] - hi1) / max(lo2 - hi1, 1e-9)
            z[span] = z1 + (z2 - z1) * _ease(t)
        r.z = z


def _profile_ramps(lines: list[_Line], crossings: list[_Crossing]) -> None:
    roads = [ln for ln in lines if not ln.is_ramp]
    ramps = [ln for ln in lines if ln.is_ramp]
    pins = {id(r): _pin(r, roads) for r in ramps}
    n_forks = _forks(ramps, pins)
    for r in ramps:
        (t0, n0), (t1, n1) = pins[id(r)]
        n = len(r.s)
        if n0 + n1 > n:  # alongside something all the way: split the run in the middle
            n0 = min(n0, n // 2)
            n1 = n - n0
        r.z = np.zeros(n)
        pts = shapely.points(r.xy)
        for target, idx in ((t0, slice(0, n0)), (t1, slice(n - n1, n))):
            if target is not None:
                r.z[idx] = np.interp(target.line.project(pts[idx]), target.s, target.z)
        r.pin_lo, r.pin_hi = float(r.s[n0 - 1]), float(r.s[n - n1])
        # A ramp follows the traffic if it runs the same way as the carriageway it is on.
        best = 0.0
        for target, s in ((t0, 0.0), (t1, r.length)):
            if target is None:
                continue
            here = r.heading_at(s)
            there = target.heading_at(target.line.project(shapely.Point(r.line.interpolate(s))))
            dot = here[0] * there[0] + here[1] * there[1]
            if abs(dot) > abs(best):
                best = dot
        r.reverse = best < 0
    _solve_ramps(ramps, crossings, n_forks)


def _with_traffic(lines: list[_Line]) -> None:
    """Turn round every line whose samples run against the traffic (a mirrored ramp)."""
    for ln in lines:
        if ln.reverse:
            ln.xy, ln.z = ln.xy[::-1].copy(), ln.z[::-1].copy()
            ln.__post_init__()
            ln.reverse = False


# ── Step 3: piers ────────────────────────────────────────────────────────────


def _piers(lines: list[_Line]) -> list[Pier]:
    piers: list[Pier] = []
    for ln in lines:
        high = ln.z >= dims.PIER_MIN_HEIGHT_M
        if not high.any():
            continue
        # Contiguous elevated stretches, as (first, last) sample index.
        edges = np.flatnonzero(np.diff(np.concatenate([[False], high, [False]]).astype(int)))
        width = min(max(ln.width * 0.45, 1.6), 5.0)
        for first, last in zip(edges[::2], edges[1::2] - 1, strict=True):
            s0, s1 = ln.s[first], ln.s[last]
            count = max(1, round((s1 - s0) / dims.PIER_SPACING_M))
            for k in range(count):
                s = s0 + (s1 - s0) * (k + 0.5) / count
                spot = _clear_spot(ln, s, lines, width)
                if spot is not None:
                    p = ln.line.interpolate(spot)
                    piers.append(Pier(p.x, p.y, ln.height_at(spot), width))
    return piers


def _clear_spot(ln: _Line, s: float, lines: list[_Line], width: float) -> float | None:
    """The arc length nearest *s* where a pier under *ln* stands on no road passing beneath."""
    for shift in (0.0, 4.0, -4.0, 8.0, -8.0, 12.0, -12.0):
        t = s + shift
        if not 0.0 <= t <= ln.length:
            continue
        p = ln.line.interpolate(t)
        top = ln.height_at(t)
        blocked = False
        for other in lines:
            if other is ln:
                continue
            reach = other.width / 2 + width / 2 + dims.PIER_ROAD_CLEARANCE_M
            if other.line.distance(p) < reach and other.height_near(p.x, p.y) < top - 1.0:
                blocked = True
                break
        if not blocked:
            return t
    return None


# ── Step 4: lanes ────────────────────────────────────────────────────────────


def _lane_width(ln: _Line) -> float:
    return ln.width / ln.lanes


def _lane_offset(ln: _Line, lane: float) -> float:
    """Centre of a lane, left of the centreline positive. Lane 1 is the inside (left) lane."""
    return ln.width / 2 - (lane - 0.5) * _lane_width(ln)


def _normals(tangent: np.ndarray) -> np.ndarray:
    """Unit vectors to the left of the travel direction."""
    return np.stack([-tangent[:, 1], tangent[:, 0]], axis=1)


@dataclass
class _Event:
    """A ramp lane leaves a lane of a road, or arrives on it."""

    s: float          # arc length on the road
    lane: int         # the road's lane; 0 or lanes + 1 lie just outside its declared width
    give: bool        # the ramp ends here and becomes this lane (else the lane leaves on it)
    alongside: bool   # the ramp runs on the lane first, so the pavement changes width here
    run: float        # how far it runs on the lane
    ramp: _Line
    ramp_lane: int


def _run_alongside(ramp: _Line, road: _Line, from_end: bool) -> float:
    """How far *ramp* runs on one lane of *road* (at a constant offset), counted from an end."""
    count = _samples_alongside(ramp, road, from_end, _RUN_DRIFT_M)
    if count == 0:
        return 0.0
    return float(ramp.length - ramp.s[len(ramp.s) - count] if from_end else ramp.s[count - 1])


def _lane_events(lines: list[_Line]) -> dict[int, dict[int, list[_Event]]]:
    """Every ramp end that lies on a lane of a road, per road and lane, in travel order."""
    roads = [ln for ln in lines if not ln.is_ramp]
    events: dict[int, dict[int, list[_Event]]] = {id(road): {} for road in roads}
    for ramp in (ln for ln in lines if ln.is_ramp):
        tangent = ramp.tangents()
        normal = _normals(tangent)
        for give in (False, True):
            i = len(ramp.s) - 1 if give else 0
            for road in roads:
                lane_w = _lane_width(road)
                reach = (road.width + ramp.width) / 2 + 2 * lane_w
                if road.line.distance(shapely.Point(ramp.xy[i])) > reach:
                    continue
                run = None
                for ramp_lane in range(1, ramp.lanes + 1):
                    tip = ramp.xy[i] + normal[i] * _lane_offset(ramp, ramp_lane)
                    where, left, _, t = _locate(road, tip[None, :])
                    s = float(where[0])
                    if s < 1.0 or s > road.length - 1.0:
                        continue  # at the road's end the lane simply carries on: no event
                    if float(tangent[i] @ t[0]) < _STRAIGHT_ON:
                        continue
                    lane = round((road.width / 2 - float(left[0])) / lane_w + 0.5)
                    if abs(float(left[0]) - _lane_offset(road, lane)) > _ON_LANE_M:
                        continue
                    if run is None:
                        run = _run_alongside(ramp, road, give)
                    events[id(road)].setdefault(lane, []).append(_Event(
                        s, lane, give, run >= _MIN_MERGE_RUN_M, run, ramp, ramp_lane,
                    ))
    for lanes in events.values():
        for evs in lanes.values():
            evs.sort(key=lambda e: e.s)
    return events


def _spans(road: _Line, lane: int, events: list[_Event], paving: bool):
    """
    The stretches of one lane of a road, as (start, end, the event that brings it or None, the
    event that takes it or None). With *paving*, only the ramps that run on the lane count: a
    turning roadway that sweeps onto a lane inside a junction interrupts its traffic, not its
    pavement. Raises if the lanes do not balance.
    """
    declared = 1 <= lane <= road.lanes
    evs = [e for e in events if e.alongside] if paving else events
    start = (0.0, None) if (declared if not evs else not evs[0].give) else None
    if start is not None and not declared:
        raise ValueError(f"{road.id}: {evs[0].ramp.id} takes lane {lane}, which the road lacks")
    spans = []
    for e in evs:
        if e.give:
            if start is not None:
                raise ValueError(f"{road.id}: {e.ramp.id} brings lane {lane}, which is in use")
            start = (e.s, e)
        else:
            if start is None:
                raise ValueError(f"{road.id}: {e.ramp.id} takes lane {lane}, which is not there")
            spans.append((start[0], e.s, start[1], e))
            start = None
    if start is not None:
        spans.append((start[0], road.length, start[1], None))
    return spans


def _road_lanes(road: _Line, events: dict[int, list[_Event]]) -> list[int]:
    return sorted(set(range(1, road.lanes + 1)) | set(events))


def _widths(lines: list[_Line], events: dict[int, dict[int, list[_Event]]]) -> None:
    """Pavement edges of every line, from the lanes it has at each point."""
    roads = [ln for ln in lines if not ln.is_ramp]
    ramps = [ln for ln in lines if ln.is_ramp]
    for ln in lines:
        n = len(ln.s)
        keep = np.arange(0, n, _OUTPUT_STEP)
        ln.keep = keep if keep[-1] == n - 1 else np.append(keep, n - 1)
        ln.left = np.full(n, ln.width / 2)
        ln.right = ln.left.copy()
        ln.median_left = np.zeros(n, dtype=bool)
        ln.median_right = ln.median_left.copy()

    # A carriageway is as wide as the lanes it has. Its width changes at an output sample, on the
    # side of the event where the ramp's own pavement covers the step: after the start of a ramp
    # that takes a lane away, before the end of one that brings a lane.
    for road in roads:
        half_lane = _lane_width(road) / 2
        kept = road.s[road.keep]
        left = np.full(len(road.s), -np.inf)
        right = left.copy()
        for lane in _road_lanes(road, events[id(road)]):
            offset = _lane_offset(road, lane)
            for s0, s1, give, take in _spans(road, lane, events[id(road)].get(lane, []), True):
                lo = kept[kept <= s0 + 1e-6].max() if give else 0.0
                hi = kept[kept >= s1 - 1e-6].min() if take else road.length
                on = (road.s >= lo - 1e-6) & (road.s <= hi + 1e-6)
                left[on] = np.maximum(left[on], offset + half_lane)
                right[on] = np.maximum(right[on], half_lane - offset)
        if not np.isfinite(left).all():
            raise ValueError(f"{road.id}: no lane is left at some point")
        road.left, road.right = left, right

    # Two carriageways with only a narrow median between them stand on one deck: each one's
    # pavement runs to the middle of the median. The widening fades out where they move apart.
    limit = dims.MEDIAN_FILL_MAX_M
    for a in roads:
        ta = a.tangents()
        normal = _normals(ta) * (a.width / 2)
        for b in roads:
            if b is a:
                continue
            tb = b.tangents()
            for sign, edge, median in ((1, a.left, a.median_left), (-1, a.right, a.median_right)):
                pts = shapely.points(a.xy + sign * normal)
                dist = shapely.distance(b.line, pts)
                near = dist <= b.width / 2 + limit + 1.0
                if not near.any():
                    continue
                where = shapely.line_locate_point(b.line, pts[near])
                level = np.abs(a.z[near] - np.interp(where, b.s, b.z)) < _SAME_LEVEL_M
                j = np.clip(np.searchsorted(b.s, where), 0, len(b.s) - 1)
                sine = np.abs(ta[near, 0] * tb[j, 1] - ta[near, 1] * tb[j, 0])
                gap = dist[near] - b.width / 2
                ok = level & (sine < _PARALLEL) & (gap > _EDGE_TOL_M)
                fade = np.clip(limit + 1.0 - gap, 0.0, 1.0)
                edge[near] += np.where(ok, gap / 2 * fade, 0.0)
                median[near] |= ok & (gap <= limit)

    # A road end that no ramp carries on from leaves the interchange.
    for road in roads:
        for at_start in (True, False):
            end = road.xy[0 if at_start else -1]
            carried_on = any(
                min(math.dist(r.xy[0], end), math.dist(r.xy[-1], end)) < road.width / 2 + _LINK_M
                for r in ramps
            )
            if at_start:
                road.open_start = not carried_on
            else:
                road.open_end = not carried_on


def _relate(a: _Line, ta: np.ndarray, b: _Line, xy: np.ndarray, reach: float):
    """
    For the points *xy* of *a* within *reach* of *b*'s centreline: their mask, their offset to
    the left of *b*, *b*'s two pavement edges there, whether the two surfaces are level, whether
    the two lines run alongside, and whether they run the same way.
    """
    near = shapely.distance(b.line, shapely.points(xy)) <= reach
    if not near.any():
        return None
    where, left, beyond, tb = _locate(b, xy[near])
    j = np.clip(np.rint(np.interp(where, b.s, np.arange(len(b.s)))).astype(int), 0, len(b.s) - 1)
    level = np.abs(a.z[near] - np.interp(where, b.s, b.z)) < _SAME_LEVEL_M
    level &= np.abs(beyond) < 0.5   # past b's end there is no b to be level with
    sine = np.abs(ta[near, 0] * tb[:, 1] - ta[near, 1] * tb[:, 0])
    same_way = ta[near, 0] * tb[:, 0] + ta[near, 1] * tb[:, 1] > 0
    return near, left, b.left[j], b.right[j], level, sine < _PARALLEL, same_way


def _edges(lines: list[_Line]) -> None:
    """What each pavement edge of every line is, and where its lane lines stop."""
    free, median, shared, open_ = (_CODES.index(c) for c in (FREE, MEDIAN, SHARED, OPEN))
    tol = _EDGE_TOL_M
    for a in lines:
        ta = a.tangents()
        normal = _normals(ta)
        a.edge_left = np.where(a.median_left, median, free)
        a.edge_right = np.where(a.median_right, median, free)
        a.marks = np.ones(len(a.s), dtype=bool)
        for b in lines:
            if b is a:
                continue
            reach = max(float(b.left.max()), float(b.right.max()))
            sides = (
                (1.0, a.left, a.edge_left, a.median_left),
                (-1.0, a.right, a.edge_right, a.median_right),
            )
            for sign, width, codes, is_median in sides:
                rel = _relate(a, ta, b, a.xy + sign * normal * width[:, None], reach + tol)
                if rel is None:
                    continue
                near, off, b_left, b_right, level, parallel, same_way = rel
                if not b.is_ramp:
                    # Across a narrow median the other carriageway's pavement meets this one:
                    # that is what "median" already says.
                    level = level & ~is_median[near]
                inside = (off < b_left - tol) & (off > -b_right + tol)
                at_left, at_right = np.abs(off - b_left) <= tol, np.abs(off + b_right) <= tol
                # b's pavement lies beyond this edge if the edge is on b's near side. Otherwise
                # the two pavements overlap and this is the outer edge of both.
                outward_is_b_left = same_way == (sign > 0)
                beyond = (at_left & ~outward_is_b_left) | (at_right & outward_is_b_left)
                code = np.where(
                    inside | ((at_left | at_right) & ~parallel), open_,
                    np.where(beyond & parallel, shared, free),
                )
                codes[near] = np.maximum(codes[near], np.where(level, code, free))

            rel = _relate(a, ta, b, a.xy, reach + _JUNCTION_MARGIN_M)
            if rel is None:
                continue
            near, off, b_left, b_right, level, parallel, _ = rel
            margin = _JUNCTION_MARGIN_M
            crossing = ~parallel & (off < b_left + margin) & (off > -b_right - margin)
            absorbed = (
                parallel & (off < b_left - tol) & (off > -b_right + tol)
                & a.is_ramp & (not b.is_ramp)
            )
            a.marks[near] &= ~(level & (crossing | absorbed))

        # A lane that is alongside only briefly is not a lane to change into: the two roads meet
        # at a junction or part at a fork, so the edge is open.
        for codes in (a.edge_left, a.edge_right):
            is_shared = np.concatenate([[False], codes == shared, [False]])
            starts = np.flatnonzero(is_shared[1:] & ~is_shared[:-1])
            stops = np.flatnonzero(~is_shared[1:] & is_shared[:-1])
            for i, j in zip(starts, stops, strict=True):
                if a.s[j - 1] - a.s[i] < _MIN_MERGE_RUN_M:
                    codes[i:j] = open_


# ── Step 5: routes and traffic ───────────────────────────────────────────────


@dataclass
class _Piece:
    """One stretch of one lane, in the direction of travel."""

    name: str
    xyz: np.ndarray
    speed: float           # m/s
    open_start: bool = False
    open_end: bool = False


def _lane_path(ln: _Line, s0: float, s1: float, lane: int, to_lane: int | None = None):
    """Centre of a lane of *ln* between two arc lengths; with *to_lane*, a lane change to it."""
    s = np.concatenate([[s0], ln.s[(ln.s > s0 + 0.5) & (ln.s < s1 - 0.5)], [s1]])
    xy = np.stack([np.interp(s, ln.s, ln.xy[:, k]) for k in (0, 1)], axis=1)
    tangent = ln.tangents()
    t = np.stack([np.interp(s, ln.s, tangent[:, k]) for k in (0, 1)], axis=1)
    t /= np.maximum(np.hypot(t[:, 0], t[:, 1]), 1e-9)[:, None]
    offset = np.full(len(s), _lane_offset(ln, lane))
    if to_lane is not None:
        u = (s - s0) / (s1 - s0)
        offset += (_lane_offset(ln, to_lane) - offset) * u * u * (3 - 2 * u)
    xy = xy + _normals(t) * offset[:, None]
    return np.column_stack([xy, np.interp(s, ln.s, ln.z)])


def _pieces(lines: list[_Line], events: dict[int, dict[int, list[_Event]]]) -> list[_Piece]:
    pieces: list[_Piece] = []
    trim: dict[tuple[int, int, bool], float] = {}  # (ramp, lane, at its end) -> length cut off
    for road in (ln for ln in lines if not ln.is_ramp):
        lanes = events[id(road)]
        spans = {k: _spans(road, k, lanes.get(k, []), False) for k in _road_lanes(road, lanes)}
        changes = []
        # An auxiliary lane, brought by one ramp and taken by the next, swaps with the lane
        # beside it: traffic from the first ramp moves over into the through lane, and the
        # through lane's traffic moves out to leave on the second ramp.
        for k in list(spans):
            for span in list(spans[k]):
                s0, s1, give, take = span
                if not (give and take and give.alongside and take.alongside):
                    continue
                c0 = s0 - min(dims.WEAVE_LEAD_M, 0.6 * give.run)
                c1 = s1 + min(dims.WEAVE_LEAD_M, 0.6 * take.run)
                beside = next((
                    (j, t) for j in (k - 1, k + 1) for t in spans.get(j, [])
                    if t[0] <= c0 - 1.0 and t[1] >= c1 + 1.0
                ), None)
                if beside is None:
                    continue
                j, through = beside
                spans[k].remove(span)
                spans[j].remove(through)
                spans[j] += [(through[0], c0, through[2], None), (c1, through[1], None, through[3])]
                changes += [(c0, c1, j, k), (c0, c1, k, j)]
                trim[(id(give.ramp), give.ramp_lane, True)] = s0 - c0
                trim[(id(take.ramp), take.ramp_lane, False)] = c1 - s1
        for k, lane_spans in spans.items():
            for s0, s1, _, _ in lane_spans:
                pieces.append(_Piece(
                    f"{road.id}/{k}", _lane_path(road, s0, s1, k), road.speed / 3.6,
                    open_start=s0 == 0.0 and road.open_start,
                    open_end=s1 == road.length and road.open_end,
                ))
        for c0, c1, j, k in changes:
            path = _lane_path(road, c0, c1, j, k)
            pieces.append(_Piece(f"{road.id}/{j}", path, road.speed / 3.6))
    for ramp in (ln for ln in lines if ln.is_ramp):
        for k in range(1, ramp.lanes + 1):
            s0 = trim.get((id(ramp), k, False), 0.0)
            s1 = ramp.length - trim.get((id(ramp), k, True), 0.0)
            name = ramp.id if ramp.lanes == 1 else f"{ramp.id}/{k}"
            pieces.append(_Piece(name, _lane_path(ramp, s0, s1, k), ramp.speed / 3.6))
    return pieces


@dataclass
class _Route:
    id: str
    xyz: np.ndarray
    t: np.ndarray          # seconds from the start, per point
    open_start: bool
    open_end: bool
    phase: float = 0.0


def _timed(xyz: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Travel time to each point at speeds *v*, eased where the speed limit changes."""
    ds = np.linalg.norm(np.diff(xyz, axis=0), axis=1)
    rate = dims.TRAFFIC_SPEED_CHANGE_PER_M
    v = v.copy()
    for i in range(1, len(v)):
        v[i] = min(v[i], v[i - 1] + rate * ds[i - 1])
    for i in range(len(v) - 2, -1, -1):
        v[i] = min(v[i], v[i + 1] + rate * ds[i])
    return np.concatenate([[0.0], np.cumsum(2 * ds / (v[:-1] + v[1:]))])


def _routes(lines: list[_Line], events: dict[int, dict[int, list[_Event]]]) -> list[_Route]:
    """Join the lane pieces end to end into routes. Raises if two lanes run into one."""
    pieces = _pieces(lines, events)
    starts = np.array([p.xyz[0] for p in pieces])
    after: dict[int, int] = {}
    before: dict[int, int] = {}
    for i, p in enumerate(pieces):
        d = np.hypot(*(starts[:, :2] - p.xyz[-1, :2]).T)
        d[(np.abs(starts[:, 2] - p.xyz[-1, 2]) > 1.0)] = np.inf
        d[i] = np.inf
        j = int(np.argmin(d))
        if d[j] <= _LINK_M:
            if j in before:
                raise ValueError(f"{p.name} and {pieces[before[j]].name} both run into "
                                 f"{pieces[j].name}")
            after[i], before[j] = j, i
    routes: list[_Route] = []
    used = 0
    for head in (i for i in range(len(pieces)) if i not in before):
        chain = [head]
        while chain[-1] in after:
            chain.append(after[chain[-1]])
        used += len(chain)
        first, last = pieces[chain[0]], pieces[chain[-1]]
        xyz = np.concatenate([pieces[chain[0]].xyz] + [pieces[i].xyz[1:] for i in chain[1:]])
        v = np.concatenate(
            [np.full(len(pieces[chain[0]].xyz), first.speed)]
            + [np.full(len(pieces[i].xyz) - 1, pieces[i].speed) for i in chain[1:]]
        )
        name = first.name if len(chain) == 1 else f"{first.name}>{last.name}"
        routes.append(_Route(name, xyz, _timed(xyz, v), first.open_start, last.open_end))
    if used != len(pieces):
        raise ValueError("a lane runs in a circle")
    return routes


def _conflicts(routes: list[_Route]) -> list[tuple[int, int, float, float]]:
    """Where two routes cross at one level: (route, route, time on the first, on the second)."""
    flat = []
    for r in routes:
        along = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(r.xyz[:, :2], axis=0).T))])
        flat.append((LineString(r.xyz[:, :2]), along))
    out = []
    for i, (a, along_a) in enumerate(flat):
        for j in range(i + 1, len(flat)):
            b, along_b = flat[j]
            inter = a.intersection(b)
            if inter.is_empty:
                continue
            for g in getattr(inter, "geoms", [inter]):
                if g.geom_type != "Point":
                    raise ValueError(f"{routes[i].id} and {routes[j].id} share a lane")
                sa, sb = a.project(g), b.project(g)
                za = np.interp(sa, along_a, routes[i].xyz[:, 2])
                zb = np.interp(sb, along_b, routes[j].xyz[:, 2])
                if abs(za - zb) < dims.LEVEL_STEP_M / 2:
                    out.append((i, j, float(np.interp(sa, along_a, routes[i].t)),
                                float(np.interp(sb, along_b, routes[j].t))))
    return out


def _release(routes: list[_Route]) -> float:
    """
    Choose the headway and each route's release phase so that cars of two routes that cross at
    one level pass between one another. Coordinate search: each route in turn takes the phase
    that maximises its smallest time gap at a crossing, until nothing improves; the headway is
    varied a little around its default and the best result kept. Returns the headway.
    """
    conflicts = _conflicts(routes)
    mine: dict[int, list[tuple[int, float, float]]] = {}
    for i, j, ti, tj in conflicts:
        mine.setdefault(i, []).append((j, ti, tj))
        mine.setdefault(j, []).append((i, tj, ti))
    best = (-1.0, dims.TRAFFIC_HEADWAY_S, np.zeros(len(routes)))
    if not conflicts:
        return best[1]

    def gaps(headway, phase_r, others, phases):
        """Time gaps at the crossings of one route, for one or several phases of it."""
        d = (np.asarray(phase_r)[..., None] + others[:, 1] - phases[others[:, 0].astype(int)]
             - others[:, 2]) % headway
        return np.minimum(d, headway - d)

    for step in (0, 1, -1, 2, -2, 3, -3, 4, -4, 5, -5):
        headway = dims.TRAFFIC_HEADWAY_S * (1 + 0.02 * step)
        candidates = np.arange(_PHASE_STEPS) * headway / _PHASE_STEPS
        phases = np.zeros(len(routes))
        for _ in range(20):
            changed = False
            for r, others in mine.items():
                others = np.array(others)
                g = gaps(headway, candidates, others, phases)
                score = g.min(axis=1) + 1e-3 * np.minimum(g, 1.0).mean(axis=1)
                now = gaps(headway, phases[r], others, phases)
                pick = int(np.argmax(score))
                if score[pick] > now.min() + 1e-3 * np.minimum(now, 1.0).mean() + 1e-9:
                    phases[r] = candidates[pick]
                    changed = True
            if not changed:
                break
        worst = min(
            float(gaps(headway, phases[r], np.array(others), phases).min())
            for r, others in mine.items()
        )
        if worst > best[0] + 0.02:
            best = (worst, headway, phases.copy())
    for r, phase in zip(routes, best[2], strict=True):
        r.phase = float(phase)
    return best[1]


def _simplify(xyz: np.ndarray, t: np.ndarray) -> np.ndarray:
    """Indices of the points to keep so that a car's position at any time is within tolerance."""
    keep = np.zeros(len(t), dtype=bool)
    keep[[0, -1]] = True
    stack = [(0, len(t) - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        u = (t[a + 1:b] - t[a]) / max(t[b] - t[a], 1e-9)
        err = np.linalg.norm(xyz[a + 1:b] - (xyz[a] + u[:, None] * (xyz[b] - xyz[a])), axis=1)
        k = int(np.argmax(err))
        if err[k] > _ROUTE_TOL_M:
            keep[a + 1 + k] = True
            stack += [(a, a + 1 + k), (a + 1 + k, b)]
    return np.flatnonzero(keep)


# ── Public API ───────────────────────────────────────────────────────────────


@lru_cache(maxsize=None)
def build_model(alternative_name: str) -> Model3D | None:
    """The 3-D model of a catalogue alternative, or None if it has no geometry generator."""
    generator_cls = FOOTPRINT_GENERATORS.get(alternative_name)
    if generator_cls is None:
        return None
    generator = generator_cls(center_lon=0.0, center_lat=0.0)
    order = dims.VERTICAL_ORDER.get(alternative_name, {})
    lines = [
        _Line(
            id=seg.id, kind=seg.kind, lanes=seg.lanes, width=seg.lanes * generator.lane_width,
            speed=seg.speed_kmh, flyover=seg.is_bridge, rank=_rank(order, seg.id),
            xy=np.asarray(seg.points, dtype=float),
        )
        for seg in generator.layout()
    ]
    crossings = _crossings(lines)
    for ln in lines:
        if not ln.is_ramp:
            ln.z = _road_profile(ln, crossings)
    _profile_ramps(lines, crossings)
    _with_traffic(lines)
    events = _lane_events(lines)
    _widths(lines, events)
    _edges(lines)
    routes = _routes(lines, events)
    headway = _release(routes)

    segments = []
    max_grade = 0.0
    for ln in lines:
        max_grade = max(max_grade, float(np.max(np.abs(np.diff(ln.z) / np.diff(ln.s)))))
        keep = ln.keep
        segments.append(Segment3D(
            id=ln.id, kind=ln.kind, lanes=ln.lanes, width_m=ln.width, speed_kmh=ln.speed,
            points=tuple(
                (round(float(ln.xy[i, 0]), 2), round(float(ln.xy[i, 1]), 2),
                 round(float(ln.z[i]), 2))
                for i in keep
            ),
            left_m=tuple(round(float(ln.left[i]), 2) for i in keep),
            right_m=tuple(round(float(ln.right[i]), 2) for i in keep),
            edge_left="".join(_CODES[ln.edge_left[i]] for i in keep),
            edge_right="".join(_CODES[ln.edge_right[i]] for i in keep),
            marks="".join("1" if ln.marks[i] else "0" for i in keep),
            open_start=ln.open_start,
            open_end=ln.open_end,
        ))
    max_height = max(float(ln.z.max()) for ln in lines)
    return Model3D(
        name=alternative_name,
        segments=tuple(segments),
        piers=tuple(
            Pier(round(p.x, 2), round(p.y, 2), round(p.top_m, 2), round(p.width_m, 2))
            for p in _piers(lines)
        ),
        extent_m=round(float(max(np.abs(ln.xy).max() for ln in lines)), 1),
        level_step_m=dims.LEVEL_STEP_M,
        levels=round(max_height / dims.LEVEL_STEP_M) + 1,
        max_height_m=round(max_height, 2),
        max_grade=round(max_grade, 4),
        routes=tuple(
            Route3D(
                id=r.id,
                points=tuple(
                    (round(float(r.xyz[i, 0]), 2), round(float(r.xyz[i, 1]), 2),
                     round(float(r.xyz[i, 2]), 2), round(float(r.t[i]), 3))
                    for i in _simplify(r.xyz, r.t)
                ),
                phase_s=round(r.phase, 3),
                open_start=r.open_start,
                open_end=r.open_end,
            )
            for r in routes
        ),
        headway_s=round(headway, 4),
    )
