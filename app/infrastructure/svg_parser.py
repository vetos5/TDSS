"""
SVG-to-RoadSegment parser.

Reads real-world SVG drawings of highway interchanges and converts each
SVG path — including **compound paths** with multiple M…z subpaths — into
one ``RoadSegment`` per detected sub-path, ready for traffic simulation and
CAD rendering.

Coordinate-system contract
--------------------------
SVG origin is the **top-left** corner; Y increases *downward*.
Our domain uses (x, y) pairs where Y increases *upward* (standard math
convention).  Every point extracted here has its Y component negated
(``y = -point.imag``) to perform this flip automatically.

Compound-path (multi-subpath) handling
---------------------------------------
A single SVG ``<path>`` element may encode several disconnected sub-paths
by using multiple ``M`` (move-to) commands inside one ``d`` attribute.
Real-world interchange drawings (e.g. Inkscape exports) exploit this to
store the entire road network as *one* element: mainline bodies, loop
ramps and inner-cutout regions all in a single compound path.

This module detects subpath breaks by inspecting the **Euclidean gap**
between consecutive sampled elements.  Any gap larger than
``_SUBPATH_JUMP_TOL`` SVG pixels is treated as a new subpath, producing a
separate ``RoadSegment``.  This means a drawing like
``Cloverleaf_interchange.svg`` yields ~12 distinct segments
(2 mainline corridors + 4 loop ramps + lane-divider lines).

``scale_factor`` maps SVG pixels to the domain's coordinate units.
The procedural generators use ``scale ≈ 0.0005`` (degrees-per-metre).
For a cloverleaf drawing ~810 px wide representing ~300 m:

    scale_factor = 0.00025   # ≈ 1 px → 0.5 m

After scaling the whole point cloud is *centred* on (center_lon,
center_lat), matching the procedural generators' geographic placement.

Supported SVG path element types
---------------------------------
* ``Line``              → up-sampled to ``num_points`` if requested
* ``CubicBezier``       → sampled via ``.point(t)``
* ``QuadraticBezier``   → sampled via ``.point(t)``
* ``Arc``               → sampled via ``.point(t)``
* Unknown types         → silently skipped (DEBUG log)
"""

from __future__ import annotations

import logging
import warnings
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
from numpy.typing import NDArray

from app.domain.geometry import ControlPoint, RoadNetwork, RoadSegment

_LOG = logging.getLogger(__name__)

# ── Tolerances (SVG pixel units) ─────────────────────────────────────
# Gap larger than this → new subpath detected.
_SUBPATH_JUMP_TOL: float = 1.0

# Gap smaller than this → duplicate endpoint, drop it.
_DEDUP_TOL: float = 1e-6

# Minimum unique control points required to build a RoadSegment.
_MIN_UNIQUE_POINTS: int = 2


# ─────────────────────────────────────────────────────────────────────
# Low-level element sampler
# ─────────────────────────────────────────────────────────────────────

def _sample_element(
    element: object,
    num_points: int,
    upsample_lines: bool,
) -> Optional[NDArray[np.float64]]:
    """
    Discretise a single svgpathtools element into an (N, 2) array.

    Points are in **SVG pixel space** (Y-down); the Y-flip is applied
    later in the pipeline so that subpath-break detection works on raw
    pixel distances.

    Returns *None* for unknown element types.
    """
    try:
        from svgpathtools import Line
    except ImportError as exc:
        raise ImportError(
            "svgpathtools is required for SVG parsing. "
            "Install it with:  pip install svgpathtools>=1.6.1"
        ) from exc

    cls_name: str = type(element).__name__

    if isinstance(element, Line):
        n = num_points if upsample_lines else 2
        t_vals = np.linspace(0.0, 1.0, n)
    elif cls_name in ("CubicBezier", "QuadraticBezier", "Arc"):
        t_vals = np.linspace(0.0, 1.0, num_points)
    else:
        _LOG.debug("Skipping unknown SVG element type: %s", cls_name)
        return None

    pts: list[Tuple[float, float]] = []
    for t in t_vals:
        try:
            z: complex = element.point(float(t))
            pts.append((z.real, z.imag))
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("element.point(%s) raised %s; skipping sample", t, exc)

    return np.array(pts, dtype=np.float64) if pts else None


# ─────────────────────────────────────────────────────────────────────
# Compound-path splitter
# ─────────────────────────────────────────────────────────────────────

def _sample_path_subpaths(
    path: object,
    num_points: int,
    upsample_lines: bool,
) -> List[NDArray[np.float64]]:
    """
    Discretise every element in *path* and split at detected subpath
    breaks, returning **one (N, 2) array per subpath**.

    A subpath break is declared when consecutive sampled arrays have a
    gap > ``_SUBPATH_JUMP_TOL`` pixels at their shared boundary.  This
    corresponds to an ``M`` (move-to) command in the SVG ``d`` attribute
    that starts a geometrically disconnected sub-path.

    The returned arrays are in SVG pixel space (Y still downward).
    """
    try:
        elements = list(path)  # type: ignore[call-overload]
    except TypeError:
        _LOG.warning("Path object is not iterable: %s", type(path))
        return []

    completed_subpaths: list[NDArray[np.float64]] = []
    current_chunks: list[NDArray[np.float64]] = []

    def _flush() -> None:
        if current_chunks:
            combined = np.concatenate(current_chunks, axis=0)
            if len(combined) >= _MIN_UNIQUE_POINTS:
                completed_subpaths.append(combined)
        current_chunks.clear()

    for element in elements:
        arr = _sample_element(element, num_points, upsample_lines)
        if arr is None or len(arr) == 0:
            continue

        if current_chunks:
            prev_end = current_chunks[-1][-1]
            gap = np.hypot(arr[0, 0] - prev_end[0], arr[0, 1] - prev_end[1])

            if gap > _SUBPATH_JUMP_TOL:
                # Subpath break: save current and start fresh.
                _flush()
            elif gap < _DEDUP_TOL:
                # Shared endpoint: drop duplicate first point.
                arr = arr[1:]
                if len(arr) == 0:
                    continue

        current_chunks.append(arr)

    _flush()
    return completed_subpaths


# ─────────────────────────────────────────────────────────────────────
# Coordinate-space helpers
# ─────────────────────────────────────────────────────────────────────

def _flip_y(coords: NDArray[np.float64]) -> NDArray[np.float64]:
    """Negate Y to convert SVG (Y-down) → math (Y-up) convention."""
    flipped = coords.copy()
    flipped[:, 1] = -flipped[:, 1]
    return flipped


def _deduplicate(
    coords: NDArray[np.float64],
    tol: float = _DEDUP_TOL,
) -> NDArray[np.float64]:
    """
    Remove consecutive near-identical points.

    ``CubicSpline`` requires strictly increasing arc-length parametrisation;
    duplicate knots produce a ``ValueError``.
    """
    if len(coords) <= 1:
        return coords
    keep = [0]
    for i in range(1, len(coords)):
        dist = np.hypot(
            coords[i, 0] - coords[keep[-1], 0],
            coords[i, 1] - coords[keep[-1], 1],
        )
        if dist >= tol:
            keep.append(i)
    return coords[keep]


def _normalise_to_domain(
    all_coords: List[NDArray[np.float64]],
    scale_factor: float,
    center_lon: float,
    center_lat: float,
) -> List[NDArray[np.float64]]:
    """
    Centre the combined point cloud on (0, 0), apply ``scale_factor``,
    then translate to (center_lon, center_lat).

    The bounding box is computed over *all* segments together so every
    segment shares the same coordinate origin — matching how procedural
    generators place everything around one (cx, cy) anchor.
    """
    if not all_coords:
        return []

    stacked = np.concatenate(all_coords, axis=0)
    cx_svg = (stacked[:, 0].min() + stacked[:, 0].max()) / 2.0
    cy_svg = (stacked[:, 1].min() + stacked[:, 1].max()) / 2.0

    result: list[NDArray[np.float64]] = []
    for coords in all_coords:
        shifted = coords.copy()
        shifted[:, 0] = (shifted[:, 0] - cx_svg) * scale_factor + center_lon
        shifted[:, 1] = (shifted[:, 1] - cy_svg) * scale_factor + center_lat
        result.append(shifted)
    return result


def _coords_to_control_points(
    coords: NDArray[np.float64],
) -> List[ControlPoint]:
    """Wrap an (N, 2) array as a list of ``ControlPoint`` objects."""
    return [ControlPoint(x=float(r[0]), y=float(r[1])) for r in coords]


# ─────────────────────────────────────────────────────────────────────
# Style helpers
# ─────────────────────────────────────────────────────────────────────

def _attr_matches_skip(attrs: dict, skip_fill_colors: List[str]) -> bool:
    """
    Return *True* when a path's ``style`` or ``fill`` attribute matches
    one of the ``skip_fill_colors`` strings (case-insensitive).

    Used to discard background rectangles that share a well-known fill
    colour (e.g. ``#c4cddb`` in the Cloverleaf SVG).
    """
    style: str = attrs.get("style", "") + " " + attrs.get("fill", "")
    style_lower = style.lower()
    return any(c.lower() in style_lower for c in skip_fill_colors)


# ─────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────

def parse_svg_to_segments(
    filepath: str,
    num_points: int = 50,
    scale_factor: float = 0.00025,
    center_lon: float = 30.5234,
    center_lat: float = 50.4501,
    upsample_lines: bool = True,
    default_lanes: int = 2,
    default_lane_width: float = 3.5,
    default_speed_kmh: float = 60.0,
    skip_ids: Optional[List[str]] = None,
    skip_fill_colors: Optional[List[str]] = None,
) -> List[RoadSegment]:
    """
    Parse an SVG file and return a ``RoadSegment`` for every detected
    sub-path (including sub-paths inside compound ``<path>`` elements).

    Parameters
    ----------
    filepath :
        Absolute or relative path to the ``.svg`` file.
    num_points :
        Samples per curved element (``CubicBezier``, ``QuadraticBezier``,
        ``Arc``).  Higher → smoother splines; lower → faster.
    scale_factor :
        SVG pixels → domain coordinate units.  Default ``0.00025`` maps a
        ~810 px Cloverleaf drawing to a ~300 m interchange, matching the
        scale of procedural generators.
    center_lon, center_lat :
        Geographic centre of the resulting network (degrees).
    upsample_lines :
        When *True*, straight ``Line`` elements are sampled at
        ``num_points`` for uniform control-point density.
    default_lanes, default_lane_width, default_speed_kmh :
        Uniform traffic attributes applied to every segment.  The UI can
        override these per-interchange after the fact.
    skip_ids :
        List of SVG path ``id`` values to exclude entirely.
        Example: ``["path3232"]`` to skip the background rectangle in the
        Cloverleaf SVG.
    skip_fill_colors :
        List of fill colour strings (e.g. ``["#c4cddb"]``).  Paths whose
        ``style`` or ``fill`` attribute contains any of these values are
        excluded.  Useful for skipping background-fill paths without
        knowing their IDs in advance.

    Returns
    -------
    List of ``RoadSegment`` objects — one per sub-path.  Empty on error.

    Raises
    ------
    ImportError
        If ``svgpathtools`` is not installed.
    """
    try:
        from svgpathtools import svg2paths
    except ImportError as exc:
        raise ImportError(
            "svgpathtools is required for SVG parsing. "
            "Install it with:  pip install svgpathtools>=1.6.1"
        ) from exc

    path_obj = Path(filepath)
    if not path_obj.exists():
        _LOG.error("SVG file not found: %s", filepath)
        return []

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            paths, attributes = svg2paths(str(path_obj))
    except Exception as exc:  # noqa: BLE001
        _LOG.error("Failed to parse SVG '%s': %s", filepath, exc)
        return []

    if not paths:
        _LOG.warning("No paths found in SVG: %s", filepath)
        return []

    _skip_ids: set[str] = set(skip_ids or [])
    _skip_fills: List[str] = list(skip_fill_colors or [])

    # ── Discretise each path into one-or-more subpath arrays ─────────
    # raw_groups: list of (path_id, subpath_index, NDArray)
    raw_groups: list[tuple[str, int, NDArray[np.float64]]] = []

    for idx, (path, attrs) in enumerate(zip(paths, attributes)):
        path_id: str = attrs.get("id", f"path-{idx:04d}")

        # Apply explicit ID filter
        if path_id in _skip_ids:
            _LOG.debug("Skipping path '%s' (in skip_ids).", path_id)
            continue

        # Apply fill-colour filter
        if _skip_fills and _attr_matches_skip(attrs, _skip_fills):
            _LOG.debug("Skipping path '%s' (fill colour matched).", path_id)
            continue

        subpath_arrays = _sample_path_subpaths(path, num_points, upsample_lines)

        for sub_idx, arr in enumerate(subpath_arrays):
            arr = _flip_y(arr)
            arr = _deduplicate(arr)
            if len(arr) < _MIN_UNIQUE_POINTS:
                _LOG.debug(
                    "Path '%s' subpath %d has < %d unique points; skipping.",
                    path_id, sub_idx, _MIN_UNIQUE_POINTS,
                )
                continue
            raw_groups.append((path_id, sub_idx, arr))

    if not raw_groups:
        _LOG.warning("All paths were empty or filtered in: %s", filepath)
        return []

    # ── Normalise all subpaths to domain coordinate space together ────
    all_arrays = [g[2] for g in raw_groups]
    domain_arrays = _normalise_to_domain(
        all_arrays, scale_factor, center_lon, center_lat
    )

    # ── Build RoadSegment objects ─────────────────────────────────────
    segments: list[RoadSegment] = []
    for (path_id, sub_idx, _), coords in zip(raw_groups, domain_arrays):
        # Use a stable, human-readable ID: "path3232-s00", etc.
        seg_id = f"{path_id}-s{sub_idx:02d}" if sub_idx > 0 else path_id
        control_pts = _coords_to_control_points(coords)
        try:
            seg = RoadSegment(
                id=seg_id,
                control_points=control_pts,
                num_lanes=default_lanes,
                lane_width_meters=default_lane_width,
                speed_limit_kmh=default_speed_kmh,
            )
            segments.append(seg)
        except Exception as exc:  # noqa: BLE001
            _LOG.warning(
                "Could not build RoadSegment for '%s' subpath %d: %s",
                path_id, sub_idx, exc,
            )

    _LOG.info(
        "parse_svg_to_segments: %d segments from %d paths in '%s'.",
        len(segments), len(paths), filepath,
    )
    return segments


def parse_svg_to_network(
    filepath: str,
    num_points: int = 50,
    scale_factor: float = 0.00025,
    center_lon: float = 30.5234,
    center_lat: float = 50.4501,
    upsample_lines: bool = True,
    default_lanes: int = 2,
    default_lane_width: float = 3.5,
    default_speed_kmh: float = 60.0,
    skip_ids: Optional[List[str]] = None,
    skip_fill_colors: Optional[List[str]] = None,
) -> RoadNetwork:
    """
    Convenience wrapper: parse an SVG file and return a ``RoadNetwork``.

    All parameters are forwarded to :func:`parse_svg_to_segments`.
    Always returns a valid (possibly empty) ``RoadNetwork``; never raises.
    """
    segments = parse_svg_to_segments(
        filepath=filepath,
        num_points=num_points,
        scale_factor=scale_factor,
        center_lon=center_lon,
        center_lat=center_lat,
        upsample_lines=upsample_lines,
        default_lanes=default_lanes,
        default_lane_width=default_lane_width,
        default_speed_kmh=default_speed_kmh,
        skip_ids=skip_ids,
        skip_fill_colors=skip_fill_colors,
    )
    network = RoadNetwork()
    for seg in segments:
        network.add_segment(seg)
    return network


# ─────────────────────────────────────────────────────────────────────
# SVGInterchangeGenerator — drop-in for procedural generators
# ─────────────────────────────────────────────────────────────────────

class SVGInterchangeGenerator:
    """
    Load a real-world SVG drawing and expose the same
    ``.generate() → RoadNetwork`` interface as all procedural generators.

    Compound paths are automatically split into individual sub-paths so
    a single SVG element containing an entire interchange (e.g. the
    ``path1310`` compound path in ``Cloverleaf_interchange.svg``) is
    decomposed into its constituent loop ramps and mainline segments.

    Parameters
    ----------
    filepath :
        Path to the ``.svg`` file.
    num_points :
        Curve-sampling resolution per path element (default 50).
    scale_factor :
        SVG pixels → domain coordinate units (default ``0.00025``).
        Rule of thumb: ``target_half_width_degrees / (svg_px / 2)``

            810 px SVG, want ±0.1 ° half-width → 0.1/405 ≈ 0.00025
    center_lon, center_lat :
        Geographic placement of the network centroid.
    lane_width :
        Default lane width (m) for every segment.
    num_lanes :
        Default lane count for every segment.
    speed_limit_kmh :
        Default speed limit for every segment.
    skip_ids :
        SVG path IDs to exclude (e.g. background rectangles).
    skip_fill_colors :
        Fill colours that mark non-road paths to exclude.

    Example
    -------
    >>> gen = SVGInterchangeGenerator(
    ...     "assets/Cloverleaf_interchange.svg",
    ...     scale_factor=0.00025,
    ...     skip_ids=["path3232"],
    ...     num_lanes=2,
    ... )
    >>> network = gen.generate()
    """

    DEFAULT_SCALE: float = 0.00025
    DEFAULT_LANES: int = 2
    DEFAULT_LANE_WIDTH: float = 3.5
    DEFAULT_SPEED_KMH: float = 60.0

    def __init__(
        self,
        filepath: str,
        num_points: int = 50,
        scale_factor: float = DEFAULT_SCALE,
        center_lon: float = 30.5234,
        center_lat: float = 50.4501,
        lane_width: float = DEFAULT_LANE_WIDTH,
        num_lanes: int = DEFAULT_LANES,
        speed_limit_kmh: float = DEFAULT_SPEED_KMH,
        upsample_lines: bool = True,
        skip_ids: Optional[List[str]] = None,
        skip_fill_colors: Optional[List[str]] = None,
    ) -> None:
        self.filepath = filepath
        self.num_points = num_points
        self.scale_factor = scale_factor
        self.center_lon = center_lon
        self.center_lat = center_lat
        self.lane_width = lane_width
        self.num_lanes = num_lanes
        self.speed_limit_kmh = speed_limit_kmh
        self.upsample_lines = upsample_lines
        self.skip_ids: List[str] = list(skip_ids or [])
        self.skip_fill_colors: List[str] = list(skip_fill_colors or [])

    def generate(self) -> RoadNetwork:
        """
        Parse the SVG and return a fully populated ``RoadNetwork``.

        Falls back to an empty network on any I/O or parse failure so
        Streamlit never crashes on a bad file upload.
        """
        return parse_svg_to_network(
            filepath=self.filepath,
            num_points=self.num_points,
            scale_factor=self.scale_factor,
            center_lon=self.center_lon,
            center_lat=self.center_lat,
            upsample_lines=self.upsample_lines,
            default_lanes=self.num_lanes,
            default_lane_width=self.lane_width,
            default_speed_kmh=self.speed_limit_kmh,
            skip_ids=self.skip_ids,
            skip_fill_colors=self.skip_fill_colors,
        )
