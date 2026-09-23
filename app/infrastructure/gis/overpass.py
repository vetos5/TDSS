"""
Overpass API client: roads, buildings, water and environmentally sensitive land near a point.

One Overpass QL query covers all five feature classes in a single request (`out geom` inlines
each way's coordinates, avoiding a second lookup pass). See ``app.application.site_analysis`` for
how these features are turned into an inferred context/terrain/environment/land classification,
and ``app.application.footprint`` for how buildings feed a right-of-way estimate.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.infrastructure.gis.cache import DEFAULT_CACHE_DIR, cached_get
from app.infrastructure.gis.errors import GisUnavailableError

OVERPASS_ENDPOINT = "https://overpass-api.de/api/interpreter"
DEFAULT_TIMEOUT_S = 25.0
CACHE_TTL_DAYS = 30.0

# Rounds a request's cache key to roughly a 100 m grid so nearby map clicks share a cache entry.
# This is a cache-hit heuristic, not a coordinate transform -- it never touches the real request.
_CACHE_GRID_DECIMALS = 3


@dataclass(frozen=True)
class OsmWay:
    """One OSM way: its tags and (lat, lon) geometry, in the order OSM returned it."""

    id: int
    tags: dict[str, str]
    coords: list[tuple[float, float]]


@dataclass(frozen=True)
class OsmFeatures:
    roads: list[OsmWay]
    buildings: list[OsmWay]
    water: list[OsmWay]
    protected: list[OsmWay]      # nature reserves / protected-area boundaries
    residential: list[OsmWay]    # landuse=residential polygons


def build_query(
    lat: float, lon: float, radius_m: float, timeout_s: float = DEFAULT_TIMEOUT_S
) -> str:
    """Overpass QL for every feature class this client knows, within radius_m of (lat, lon)."""
    around = f"around:{radius_m},{lat},{lon}"
    filters = [
        "[highway]",
        "[building]",
        "[natural=water]",
        "[waterway]",
        "[leisure=nature_reserve]",
        "[boundary=protected_area]",
        "[landuse=residential]",
    ]
    clauses = "\n  ".join(f"way({around}){f};" for f in filters)
    return f"[out:json][timeout:{int(timeout_s)}];\n(\n  {clauses}\n);\nout geom;"


def _tag_matches(tags: dict[str, str], want: str) -> bool:
    """``want`` is either ``"key"`` (present, any value) or ``"key=value"`` (exact match)."""
    key, _, value = want.partition("=")
    return key in tags if not value else tags.get(key) == value


# (predicate on tags) -> which OsmFeatures list a way belongs to. A way can match more than one
# (e.g. a park that is also a nature reserve); it is only added to the first list that matches so
# every way is classified exactly once, keeping counts (used for env-sensitivity scoring) sane.
_CLASSIFIERS: list[tuple[str, str]] = [
    ("roads", "highway"),
    ("buildings", "building"),
    ("water", "natural=water"),
    ("water", "waterway"),
    ("protected", "leisure=nature_reserve"),
    ("protected", "boundary=protected_area"),
    ("residential", "landuse=residential"),
]


def parse_features(raw: dict[str, Any]) -> OsmFeatures:
    """Turn a raw Overpass JSON response into classified :class:`OsmWay` lists."""
    buckets: dict[str, list[OsmWay]] = {
        "roads": [], "buildings": [], "water": [], "protected": [], "residential": [],
    }
    for el in raw.get("elements", []):
        if el.get("type") != "way" or "geometry" not in el:
            continue
        tags = el.get("tags", {})
        way = OsmWay(
            id=el["id"],
            tags=tags,
            coords=[(pt["lat"], pt["lon"]) for pt in el["geometry"]],
        )
        for bucket, want in _CLASSIFIERS:
            if _tag_matches(tags, want):
                buckets[bucket].append(way)
                break
    return OsmFeatures(**buckets)


class OverpassClient:
    """Fetches and caches OSM features around a point. Pass a fake ``httpx.Client`` in tests."""

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        cache_dir: Path | None = DEFAULT_CACHE_DIR,
        cache_ttl_days: float = CACHE_TTL_DAYS,
    ) -> None:
        self._client = client or httpx.Client(timeout=DEFAULT_TIMEOUT_S)
        self._owns_client = client is None
        self._cache_dir = cache_dir
        self._cache_ttl_days = cache_ttl_days

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def fetch_features(self, lat: float, lon: float, radius_m: float = 500.0) -> OsmFeatures:
        lat_key, lon_key = round(lat, _CACHE_GRID_DECIMALS), round(lon, _CACHE_GRID_DECIMALS)
        key = f"overpass:{lat_key}:{lon_key}:{int(radius_m)}"

        def _fetch() -> dict[str, Any]:
            query = build_query(lat, lon, radius_m)
            try:
                response = self._client.post(OVERPASS_ENDPOINT, data={"data": query})
                response.raise_for_status()
                return response.json()
            except httpx.TimeoutException as exc:
                raise GisUnavailableError(
                    "Overpass API timed out; it can be briefly busy -- try again shortly."
                ) from exc
            except (httpx.HTTPError, ValueError) as exc:
                raise GisUnavailableError(f"Overpass API request failed: {exc}") from exc

        raw = cached_get(key, self._cache_ttl_days, _fetch, cache_dir=self._cache_dir)
        return parse_features(raw)
