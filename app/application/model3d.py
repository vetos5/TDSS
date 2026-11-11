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
   alongside them. In between it gets a level stretch ("knot") at every crossing, and the knot
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


@dataclass(frozen=True)
class Segment3D:
    id: str
    kind: str
    lanes: int
    width_m: float
    speed_kmh: float
    points: tuple[tuple[float, float, float], ...]  # x east, y north, z up; in travel direction


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
    parent: "_Line | None" = None      # the ramp this one forks from or merges into
    reverse: bool = False              # samples run against the traffic

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


def _pin(ramp: _Line, roads: list[_Line], ramps: list[_Line]):
    """
    Find what each end of *ramp* is attached to. Returns, for the start and the end, the line it is
    pinned to (or None) and how many samples from that end run alongside it.
    """
    pts = shapely.points(ramp.xy)
    result = []
    for from_start in (True, False):
        tip = pts[0] if from_start else pts[-1]
        best, best_d, best_tol = None, math.inf, 0.0
        for road in roads:
            d = road.line.distance(tip)
            tol = (road.width + ramp.width) / 2 + 1.0
            if d <= tol and d < best_d:
                best, best_d, best_tol = road, d, tol
        if best is None:
            for other in ramps:
                d = other.line.distance(tip)
                if other is not ramp and d <= _CONTACT_M and d < best_d:
                    best, best_d, best_tol = other, d, _CONTACT_M
        run = _pin_run(shapely.distance(best.line, pts), best_tol, from_start) if best else 1
        result.append((best, run))
    return result


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


def _solve_ramps(ramps: list[_Line], crossings: list[_Crossing]) -> None:
    """Set ``z`` on every ramp in *ramps*; every other line in *crossings* must already have it."""
    solving = {id(r) for r in ramps}
    knots: dict[int, list[_Knot]] = {id(r): [] for r in ramps}
    at: dict[tuple[int, int], _Knot] = {}  # (ramp, crossing index) -> its knot

    for n, c in enumerate(crossings):
        for me, other, s in ((c.a, c.b, c.sa), (c.b, c.a, c.sb)):
            if id(me) not in solving or not me.pin_lo < s < me.pin_hi:
                continue
            if other.parent is me or me.parent is other:
                continue
            ca, cb = me.heading_at(s), other.heading_at(c.sb if me is c.a else c.sa)
            skew = max(abs(ca[0] * cb[1] - ca[1] * cb[0]), 0.5)
            half = other.width / 2 / skew + dims.CROSSING_MARGIN_M
            k = _Knot(max(s - half, me.pin_lo + _MIN_GAP_M), min(s + half, me.pin_hi - _MIN_GAP_M))
            knots[id(me)].append(k)
            at[(id(me), n)] = k

    # Merge overlapping level stretches of one ramp, then number the survivors as LP variables.
    n_vars = 0
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

    heights = np.zeros(n_vars)
    if n_vars:
        # Variables: the knot heights, then G, then one "rise or fall" u per gap between knots.
        gaps = []  # (v1, z1, v2, z2, length) for each pair of consecutive nodes of a ramp
        for r in ramps:
            nodes = [(None, r.height_at(r.pin_lo), r.pin_lo, r.pin_lo)]
            nodes += [(k.var, 0.0, k.lo, k.hi) for k in knots[id(r)]]
            nodes += [(None, r.height_at(r.pin_hi), r.pin_hi, r.pin_hi)]
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
            return None, line.height_at(s) if line.z is not None else None

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
            if c.a.parent is c.b or c.b.parent is c.a:
                continue
            (va, za), (vb, zb) = term(c.a, n, c.sa), term(c.b, n, c.sb)
            if (va is None and za is None) or (vb is None and zb is None):
                continue  # the other line is solved in a later pass and will adapt to this one
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
        nodes = [(r.pin_lo, r.pin_lo, r.height_at(r.pin_lo))]
        nodes += [(k.lo, k.hi, float(heights[k.var])) for k in knots[id(r)]]
        nodes += [(r.pin_hi, r.pin_hi, r.height_at(r.pin_hi))]
        z = r.z.copy()
        free = (r.s > r.pin_lo) & (r.s < r.pin_hi)
        for (_, hi1, z1), (lo2, hi2, z2) in zip(nodes, nodes[1:], strict=False):
            span = free & (r.s >= hi1) & (r.s <= hi2)
            t = (r.s[span] - hi1) / max(lo2 - hi1, 1e-9)
            z[span] = z1 + (z2 - z1) * _ease(t)
        r.z = z


def _profile_ramps(lines: list[_Line], crossings: list[_Crossing]) -> None:
    roads = [ln for ln in lines if not ln.is_ramp]
    ramps = [ln for ln in lines if ln.is_ramp]
    pins = {id(r): _pin(r, roads, ramps) for r in ramps}
    for r in ramps:
        for target, _ in pins[id(r)]:
            if target is not None and target.is_ramp:
                r.parent = target

    # Ramps that hang off another ramp (a right-turn roadway forking from an off-ramp) are solved
    # after it, against its finished profile.
    for batch in ([r for r in ramps if r.parent is None], [r for r in ramps if r.parent]):
        for r in batch:
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
                if target is None or target.is_ramp:
                    continue
                here = r.heading_at(s)
                there = target.heading_at(target.line.project(shapely.Point(r.line.interpolate(s))))
                dot = here[0] * there[0] + here[1] * there[1]
                if abs(dot) > abs(best):
                    best = dot
            r.reverse = best < 0
        _solve_ramps(batch, crossings)


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

    segments = []
    max_grade = 0.0
    for ln in lines:
        max_grade = max(max_grade, float(np.max(np.abs(np.diff(ln.z) / np.diff(ln.s)))))
        keep = np.arange(0, len(ln.s), _OUTPUT_STEP)
        if keep[-1] != len(ln.s) - 1:
            keep = np.append(keep, len(ln.s) - 1)
        if ln.reverse:
            keep = keep[::-1]
        segments.append(Segment3D(
            id=ln.id, kind=ln.kind, lanes=ln.lanes, width_m=ln.width, speed_kmh=ln.speed,
            points=tuple(
                (round(float(ln.xy[i, 0]), 2), round(float(ln.xy[i, 1]), 2),
                 round(float(ln.z[i]), 2))
                for i in keep
            ),
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
    )
