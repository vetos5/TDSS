"""
Place a real interchange footprint on the map, and estimate right-of-way / demolition cost.

Every catalogue alternative has a geometry generator (``app/infrastructure/generators.py``).
Instantiated at the origin, a generator outputs "real metres ÷ METRES_PER_COORD", the convention
shared with ``app/domain/geometry.py``. This module scales that back to metres, rotates it to the
bearing of the planner's primary road (the generators lay that road out along +y), and projects it
to the chosen site with ``app.infrastructure.gis.projection``, so the placement is
latitude-corrected. The generators' own ``center_lon``/``center_lat`` are never used for this (see
the module-level note in ``projection.py``). :func:`place_footprint` returns ``None`` for a name
that is not in the catalogue.

Right-of-way estimation is deliberately display-only: it is inherently per-alternative (each
interchange type has a different footprint) while today's ``ProjectParams`` adjustments apply one
cost scalar across every alternative uniformly, so folding it into the WSM/MCDA scoring would
break that contract. See DOCUMENTATION.md for the fuller scope note.
"""

from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union
from shapely.prepared import prep

from app.data.site_analysis_defaults import MAX_BUILDING_NODES
from app.domain.geometry import METRES_PER_COORD
from app.infrastructure.generators import (
    CloverleafGenerator,
    DDIGenerator,
    DiamondGenerator,
    DirectionalTGenerator,
    SPUIGenerator,
    StackGenerator,
    TrumpetGenerator,
    TurbineGenerator,
)
from app.infrastructure.gis.overpass import OsmWay
from app.infrastructure.gis.projection import LocalOrigin, rotate, to_latlon, to_local

FOOTPRINT_GENERATORS: dict[str, type] = {
    "Cloverleaf": CloverleafGenerator,
    "Turbine": TurbineGenerator,
    "Stack (4-Level)": StackGenerator,
    "Diamond": DiamondGenerator,
    "SPUI": SPUIGenerator,
    "DDI": DDIGenerator,
    "Trumpet": TrumpetGenerator,
    "Directional T": DirectionalTGenerator,
}


def is_footprint_available(alternative_name: str) -> bool:
    return alternative_name in FOOTPRINT_GENERATORS


@dataclass(frozen=True)
class FootprintSegment:
    id: str
    coords_latlon: list[tuple[float, float]]
    width_m: float
    kind: str = "road"  # mainline | crossroad | ramp | road, see RoadSegment.kind


@dataclass(frozen=True)
class Footprint:
    alternative_name: str
    origin: LocalOrigin
    bearing_rad: float
    segments: list[FootprintSegment]
    polygon: Polygon  # in local metres relative to `origin` -- see estimate_right_of_way


@dataclass(frozen=True)
class RightOfWay:
    buildings_affected: int
    demolished_area_m2: float
    estimated_cost_usd: float


def place_footprint(
    alternative_name: str,
    origin_lat: float,
    origin_lon: float,
    bearing_rad: float = 0.0,
    **generator_kwargs,
) -> Footprint | None:
    """
    Build *alternative_name*'s real-scale footprint at (origin_lat, origin_lon), rotated to
    *bearing_rad* (0 = the generator's native north-aligned layout). Returns ``None`` if no
    generator exists for that alternative.
    """
    generator_cls = FOOTPRINT_GENERATORS.get(alternative_name)
    if generator_cls is None:
        return None

    generator = generator_cls(center_lon=0.0, center_lat=0.0, **generator_kwargs)
    network = generator.generate()
    origin = LocalOrigin(lat=origin_lat, lon=origin_lon)

    segments: list[FootprintSegment] = []
    buffers = []
    for seg, raw_points in zip(network.segments, network.all_centrelines(), strict=True):
        local_points = [
            rotate(raw_x * METRES_PER_COORD, raw_y * METRES_PER_COORD, bearing_rad)
            for raw_x, raw_y in raw_points
        ]
        segments.append(FootprintSegment(
            id=seg.id,
            coords_latlon=[to_latlon(x, y, origin) for x, y in local_points],
            width_m=seg.road_width(),
            kind=seg.kind,
        ))
        if len(local_points) >= 2:
            buffers.append(LineString(local_points).buffer(seg.road_width() / 2.0))

    polygon = unary_union(buffers) if buffers else Polygon()
    return Footprint(
        alternative_name=alternative_name,
        origin=origin,
        bearing_rad=bearing_rad,
        segments=segments,
        polygon=polygon,
    )


def _building_polygon(way: OsmWay, origin: LocalOrigin) -> Polygon | None:
    """A closed building way as a local-metre Polygon, or None if it isn't a closed ring."""
    if len(way.coords) < 4 or way.coords[0] != way.coords[-1]:
        return None
    poly = Polygon([to_local(lat, lon, origin) for lat, lon in way.coords])
    return poly if poly.is_valid else poly.buffer(0)


def estimate_right_of_way(
    footprint: Footprint, buildings: list[OsmWay], demolition_cost_per_sqm: float
) -> RightOfWay:
    """How many OSM buildings the footprint would demolish, and a rough cost for that.

    Every building in the search radius is passed in, but only those whose bounding box meets the
    footprint's can overlap it, so the rest are skipped before any geometry is built or repaired.
    Buildings over MAX_BUILDING_NODES vertices are skipped too (see site_analysis_defaults.py).
    """
    affected = 0
    demolished_area = 0.0
    if footprint.polygon.is_empty:
        return RightOfWay(0, 0.0, 0.0)
    # The projection is axis-aligned and linear, so the local bounding box maps to a lat/lon box
    # and each building can be tested on its raw coordinates. The margin (about 1 cm) absorbs
    # rounding in the round trip, so a building touching the box edge is still checked.
    minx, miny, maxx, maxy = footprint.polygon.bounds
    south, west = to_latlon(minx, miny, footprint.origin)
    north, east = to_latlon(maxx, maxy, footprint.origin)
    south, west, north, east = south - 1e-7, west - 1e-7, north + 1e-7, east + 1e-7
    fp_prepared = prep(footprint.polygon)
    for way in buildings:
        if not way.coords or len(way.coords) > MAX_BUILDING_NODES:
            continue
        lats = [lat for lat, _ in way.coords]
        lons = [lon for _, lon in way.coords]
        if (max(lats) < south or min(lats) > north
                or max(lons) < west or min(lons) > east):
            continue
        poly = _building_polygon(way, footprint.origin)
        if poly is None or poly.is_empty or not fp_prepared.intersects(poly):
            continue
        overlap = poly.intersection(footprint.polygon)
        if not overlap.is_empty:
            affected += 1
            demolished_area += overlap.area

    return RightOfWay(
        buildings_affected=affected,
        demolished_area_m2=round(demolished_area, 1),
        estimated_cost_usd=round(demolished_area * demolition_cost_per_sqm, 0),
    )
