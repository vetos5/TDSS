"""
Phase 3 API: GIS site analysis and real-scale footprint placement.

Kept in its own router (rather than growing routes.py further): these endpoints have a genuinely
different failure mode from the rest of the API (an external service being unreachable, mapped to
HTTP 503 -- see GisUnavailableError) and their own dependency-injected GIS clients, which tests
override with fakes so the suite never touches the network.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.application.footprint import estimate_right_of_way, is_footprint_available, place_footprint
from app.application.site_analysis import analyse_site
from app.data.site_analysis_defaults import (
    DEFAULT_DEMOLITION_COST_PER_SQM_USD,
    DEFAULT_ELEVATION_GRID_N,
)
from app.infrastructure.gis.elevation import ElevationClient
from app.infrastructure.gis.errors import GisUnavailableError
from app.infrastructure.gis.overpass import OsmFeatures, OsmWay, OverpassClient
from app.infrastructure.gis.projection import bearing as compute_bearing
from backend.schemas import (
    FootprintRequest,
    FootprintResponse,
    FootprintSegmentSchema,
    RightOfWaySchema,
    RoadCorridorSchema,
    SiteAnalyseRequest,
    SiteAnalyseResponse,
)

router = APIRouter()

# Module-level singletons: one pooled httpx.Client for the process's lifetime, not one per
# request. Tests never touch these -- they override the functions below with fakes.
_overpass_client = OverpassClient()
_elevation_client = ElevationClient()


def get_overpass_client() -> OverpassClient:
    return _overpass_client


def get_elevation_client() -> ElevationClient:
    return _elevation_client


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
    features = []
    for category, ways in (
        ("road", osm.roads),
        ("building", osm.buildings),
        ("water", osm.water),
        ("protected", osm.protected),
        ("residential", osm.residential),
    ):
        for way in ways:
            features.append({
                "type": "Feature",
                "geometry": _way_geometry(way),
                "properties": {"category": category, "id": way.id, "tags": way.tags},
            })
    return {"type": "FeatureCollection", "features": features}


@router.post("/analyse", response_model=SiteAnalyseResponse)
def analyse(
    req: SiteAnalyseRequest,
    overpass: OverpassClient = Depends(get_overpass_client),
    elevation: ElevationClient = Depends(get_elevation_client),
):
    try:
        osm = overpass.fetch_features(req.lat, req.lon, req.radius_m)
        grid = elevation.fetch_grid(req.lat, req.lon, req.radius_m, n=DEFAULT_ELEVATION_GRID_N)
    except GisUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

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

    bearing_rad = _bearing_rad(req)
    fp = place_footprint(req.alternative_name, req.lat, req.lon, bearing_rad)

    try:
        osm = overpass.fetch_features(req.lat, req.lon, req.radius_m)
    except GisUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

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
