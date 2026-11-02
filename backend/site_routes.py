"""
Phase 3 API: GIS site analysis and real-scale footprint placement.

Kept in its own router (rather than growing routes.py further): these endpoints have a genuinely
different failure mode from the rest of the API (an external service being unreachable, mapped to
HTTP 503 -- see GisUnavailableError) and their own dependency-injected GIS clients, which tests
override with fakes so the suite never touches the network.

When this server cannot reach any Overpass server, the browser can fetch the OSM data itself
(``/overpass-query`` gives it the query) and send it along in ``osm``.

Both routes share SITE_REQUEST_SLOTS (see backend.limits), and each request's outbound calls stop
at SITE_REQUEST_DEADLINE_S. The 503 detail is a fixed message; the upstream error is only logged.
"""

from __future__ import annotations

import ipaddress
import logging
import threading
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.application.footprint import estimate_right_of_way, is_footprint_available, place_footprint
from app.application.site_analysis import analyse_site
from app.data.site_analysis_defaults import (
    CLIENT_MAX_OUTBOUND_PER_DAY,
    DEFAULT_DEMOLITION_COST_PER_SQM_USD,
    DEFAULT_ELEVATION_GRID_N,
    ELEVATION_MAX_PER_DAY,
    ELEVATION_MIN_INTERVAL_S,
    MAX_CLIENT_OSM_NODES,
    MAX_MAP_FEATURES,
    OPEN_METEO_MAX_PER_DAY,
    OVERPASS_MAX_CONCURRENT,
    OVERPASS_MAX_PER_DAY,
    SITE_REQUEST_DEADLINE_S,
    SITE_REQUEST_SLOTS,
)
from app.infrastructure.gis.elevation import ElevationClient
from app.infrastructure.gis.errors import GisUnavailableError
from app.infrastructure.gis.outbound import OutboundBudget
from app.infrastructure.gis.overpass import (
    OVERPASS_MIRROR_ENDPOINTS,
    OsmFeatures,
    OsmWay,
    OverpassClient,
    build_query,
    parse_features,
    within_radius,
)
from app.infrastructure.gis.projection import bearing as compute_bearing
from backend.limits import slot
from backend.schemas import (
    FootprintRequest,
    FootprintResponse,
    FootprintSegmentSchema,
    OsmWayInput,
    OverpassQueryResponse,
    RightOfWaySchema,
    RoadCorridorSchema,
    SiteAnalyseRequest,
    SiteAnalyseResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# Module-level singletons: one pooled httpx.Client and one outbound budget for the process's
# lifetime, not one per request. Tests never touch these -- they override the functions below
# with fakes.
_overpass_client = OverpassClient(budget=OutboundBudget(
    "Overpass", max_concurrent=OVERPASS_MAX_CONCURRENT, per_day=OVERPASS_MAX_PER_DAY,
    per_client_per_day=CLIENT_MAX_OUTBOUND_PER_DAY,
))
_elevation_client = ElevationClient(
    budget=OutboundBudget(
        "Elevation API", max_concurrent=1, per_day=ELEVATION_MAX_PER_DAY,
        per_client_per_day=CLIENT_MAX_OUTBOUND_PER_DAY, min_interval_s=ELEVATION_MIN_INTERVAL_S,
    ),
    fallback_budget=OutboundBudget(
        "Open-Meteo", max_concurrent=1, per_day=OPEN_METEO_MAX_PER_DAY,
        min_interval_s=ELEVATION_MIN_INTERVAL_S,
    ),
)

_SITE_SLOTS = threading.BoundedSemaphore(SITE_REQUEST_SLOTS)


def get_overpass_client() -> OverpassClient:
    return _overpass_client


def get_elevation_client() -> ElevationClient:
    return _elevation_client


def client_key(request: Request) -> str:
    """Who to charge for outbound calls: the client IP, with IPv6 cut to its /64.

    uvicorn takes the client address from X-Forwarded-For only when nginx sent it, and nginx sets
    that from Cloudflare's CF-Connecting-IP. One IPv6 subscriber usually holds a whole /64, so
    rotating addresses inside it does not buy a fresh share.
    """
    host = request.client.host if request.client else "unknown"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return host
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return str(ip.ipv4_mapped)
        return str(ipaddress.IPv6Network((ip, 64), strict=False))
    return str(ip)


def _unavailable(exc: GisUnavailableError) -> HTTPException:
    logger.warning("GIS call failed: %s", exc)
    headers = {"Retry-After": str(exc.retry_after_s)} if exc.retry_after_s else None
    return HTTPException(status_code=503, detail=exc.public_message, headers=headers)


def _bearing_rad(req) -> float:
    if req.bearing_lat is None or req.bearing_lon is None:
        return 0.0
    return compute_bearing(req.lat, req.lon, req.bearing_lat, req.bearing_lon)


def _way_geometry(way: OsmWay) -> dict[str, Any]:
    coords = [[lon, lat] for lat, lon in way.coords]  # GeoJSON order: [lon, lat]
    if len(coords) >= 4 and coords[0] == coords[-1]:
        return {"type": "Polygon", "coordinates": [coords]}
    return {"type": "LineString", "coordinates": coords}


def _osm_to_geojson(osm: OsmFeatures) -> dict[str, Any]:
    """The features for the map, at most MAX_MAP_FEATURES, with only the properties it reads."""
    layers = (
        ("road", osm.roads),
        ("building", osm.buildings),
        ("water", osm.water),
        ("protected", osm.protected),
        ("residential", osm.residential),
    )
    # Buildings are most of a dense cell and the least useful at map scale, so they give way first.
    others = sum(len(ways) for category, ways in layers if category != "building")
    building_room = max(MAX_MAP_FEATURES - others, 0)
    features = []
    for category, ways in layers:
        for way in ways[:building_room] if category == "building" else ways:
            features.append({
                "type": "Feature",
                "geometry": _way_geometry(way),
                "properties": {"category": category, "id": way.id},
            })
    return {"type": "FeatureCollection", "features": features[:MAX_MAP_FEATURES]}


def _features(
    req, client: str, overpass: OverpassClient, deadline: float
) -> OsmFeatures:
    """The OSM features around the request's point: the browser's own, or this server's query.

    Ways the browser fetched (``req.osm``) are classified and cut to the radius exactly as the
    server's own answer would be, and serve this request only: they are never cached, so one
    visitor's data cannot reach another.
    """
    if req.osm is None:
        return overpass.fetch_features(
            req.lat, req.lon, req.radius_m, deadline=deadline, client=client
        )
    if sum(len(way.coords) for way in req.osm) > MAX_CLIENT_OSM_NODES:
        raise HTTPException(
            status_code=422,
            detail="There is too much map data around this point. Choose a smaller radius.",
        )
    return within_radius(parse_features(_overpass_shape(req.osm)), req.lat, req.lon, req.radius_m)


def _overpass_shape(ways: list[OsmWayInput]) -> dict[str, Any]:
    return {"elements": [
        {"type": "way", "id": way.id, "tags": way.tags,
         "geometry": [{"lat": lat, "lon": lon} for lat, lon in way.coords]}
        for way in ways
    ]}


@router.get("/overpass-query", response_model=OverpassQueryResponse)
def overpass_query(
    lat: float = Query(ge=-85, le=85),
    lon: float = Query(ge=-180, le=180),
    radius_m: float = Query(500.0, ge=100, le=1500),
):
    """The Overpass QL this server would send, for the browser to send itself when this server
    cannot reach Overpass (public Overpass servers are meant for browser-based tools, and each
    visitor has their own address and query slots). Makes no outbound call."""
    return OverpassQueryResponse(
        query=build_query(lat, lon, radius_m), endpoints=list(OVERPASS_MIRROR_ENDPOINTS)
    )


@router.post("/analyse", response_model=SiteAnalyseResponse)
def analyse(
    req: SiteAnalyseRequest,
    request: Request,
    overpass: OverpassClient = Depends(get_overpass_client),
    elevation: ElevationClient = Depends(get_elevation_client),
):
    with slot(_SITE_SLOTS):
        return _analyse(req, client_key(request), overpass, elevation)


def _analyse(
    req: SiteAnalyseRequest, client: str, overpass: OverpassClient, elevation: ElevationClient
) -> SiteAnalyseResponse:
    deadline = time.monotonic() + SITE_REQUEST_DEADLINE_S
    try:
        osm = _features(req, client, overpass, deadline)
    except GisUnavailableError as exc:
        raise _unavailable(exc) from exc
    # Terrain is one of five inferred parameters, and the planner can set it by hand: without
    # elevation data the analysis still answers, with a note, rather than failing outright.
    try:
        grid = elevation.fetch_grid(
            req.lat, req.lon, req.radius_m, n=DEFAULT_ELEVATION_GRID_N,
            deadline=deadline, client=client,
        )
    except GisUnavailableError as exc:
        logger.warning("Elevation unavailable, analysing without it: %s", exc)
        grid = None

    result = analyse_site(req.lat, req.lon, osm, grid, req.radius_m)

    return SiteAnalyseResponse(
        context=result.context,
        context_confident=result.context_confident,
        corridors=[
            RoadCorridorSchema(bearing_deg=c.bearing_deg, rank=c.rank, way_count=len(c.way_ids))
            for c in result.corridors
        ],
        terrain=result.terrain,
        max_grade_pct=result.max_grade_pct,
        env_sensitivity=result.env_sensitivity,
        nearest_water_m=result.nearest_water_m,
        residential_share=result.residential_share,
        land_limit_ha=result.land_limit_ha,
        building_count=result.building_count,
        building_area_m2=result.building_area_m2,
        water_area_m2=result.water_area_m2,
        notes=result.notes,
        radius_m=req.radius_m,
        osm_features=_osm_to_geojson(osm),
    )


@router.post("/footprint", response_model=FootprintResponse)
def footprint(
    req: FootprintRequest,
    request: Request,
    overpass: OverpassClient = Depends(get_overpass_client),
):
    if not is_footprint_available(req.alternative_name):
        return FootprintResponse(
            available=False,
            alternative_name=req.alternative_name,
            message=(
                f"No geometry generator for '{req.alternative_name}' yet -- footprint drawing "
                "is only available for Cloverleaf, DDI, SPUI and Turbine."
            ),
        )

    with slot(_SITE_SLOTS):
        return _footprint(req, client_key(request), overpass)


def _footprint(req: FootprintRequest, client: str, overpass: OverpassClient) -> FootprintResponse:
    bearing_rad = _bearing_rad(req)
    fp = place_footprint(req.alternative_name, req.lat, req.lon, bearing_rad)

    deadline = time.monotonic() + SITE_REQUEST_DEADLINE_S
    try:
        osm = _features(req, client, overpass, deadline)
    except GisUnavailableError as exc:
        raise _unavailable(exc) from exc

    cost_per_sqm = req.demolition_cost_per_sqm or DEFAULT_DEMOLITION_COST_PER_SQM_USD
    row = estimate_right_of_way(fp, osm.buildings, cost_per_sqm)

    return FootprintResponse(
        available=True,
        alternative_name=req.alternative_name,
        segments=[
            FootprintSegmentSchema(
                id=seg.id,
                width_m=seg.width_m,
                coords=[[lat, lon] for lat, lon in seg.coords_latlon],
            )
            for seg in fp.segments
        ],
        right_of_way=RightOfWaySchema(
            buildings_affected=row.buildings_affected,
            demolished_area_m2=row.demolished_area_m2,
            estimated_cost_usd=row.estimated_cost_usd,
        ),
    )
