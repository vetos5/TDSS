"""
Overpass API client: roads, buildings, water and environmentally sensitive land near a point.

One Overpass QL query covers all five feature classes in a single request (`out geom` inlines
each way's coordinates, avoiding a second lookup pass). See ``app.application.site_analysis`` for
how these features are turned into an inferred context/terrain/environment/land classification,
and ``app.application.footprint`` for how buildings feed a right-of-way estimate.

The cache holds the classified ways with only the tags the analysis reads, not Overpass's raw
answer, so a cache hit parses a fraction of the original body.

Queries are made around the cache-grid point, with a margin, so nearby clicks share one cache
entry; :func:`within_radius` then keeps exactly the ways an ``around`` query at the requested
point and radius would have returned, so the analysis sees the same features as before.
"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

import httpx

from app.data.site_analysis_defaults import MIN_MAJOR_ROAD_RANK, ROAD_CLASS_RANK
from app.infrastructure.gis import outbound, retry
from app.infrastructure.gis.cache import DEFAULT_CACHE_DIR, cached_get, snap_site
from app.infrastructure.gis.errors import QUERY_FAILED_MESSAGE, GisUnavailableError
from app.infrastructure.gis.outbound import OutboundBudget
from app.infrastructure.gis.projection import LocalOrigin, to_local

OVERPASS_ENDPOINT = "https://overpass-api.de/api/interpreter"
# The public Overpass server is shared infrastructure and can return a transient 502/503/504
# under load (observed directly: a real request during development hit a 504 that succeeded on
# retry). A second, independently-run mirror plus a short retry-with-backoff on each smooths
# this over instead of surfacing it to the planner as a hard failure.
OVERPASS_MIRROR_ENDPOINTS = (OVERPASS_ENDPOINT, "https://overpass.kumi.systems/api/interpreter")
RETRIES_PER_ENDPOINT = 2
RETRY_BACKOFF_S = 1.5  # doubles each retry: 1.5s, 3s
DEFAULT_TIMEOUT_S = 20.0  # read timeout per socket read; see outbound.py for the others
# Overpass's own [timeout:] for the query, kept under the read timeout so a heavy query ends with
# Overpass's error remark rather than our read timing out. A busy server is also more likely to
# accept a query with a lower value.
QUERY_TIMEOUT_S = 15
# A body above this (a dense city centre at a large radius) is too much to parse, analyse and draw
# on a phone. It is dropped unread and uncached, and the planner is asked for a smaller radius.
MAX_RESPONSE_BYTES = 15 * 1024 * 1024
# Overpass (or a filter in front of it) returns 406 Not Acceptable for httpx's default
# "python-httpx/x.y" User-Agent -- confirmed directly against the live server. Overpass's own
# fair-use policy also asks clients to identify themselves, so this is correct etiquette, not
# just a workaround.
USER_AGENT = "TDSS-diploma-thesis/1.0 (+https://github.com/vetos5/TDSS)"
CACHE_TTL_DAYS = 30.0

# Only the road classes the corridor analysis ranks (tertiary and above, see
# site_analysis_defaults.py). Service roads, footways and the like were most of the roads in a
# dense cell and never counted towards anything.
MAJOR_HIGHWAY_CLASSES = tuple(
    sorted(cls for cls, rank in ROAD_CLASS_RANK.items() if rank >= MIN_MAJOR_ROAD_RANK)
)
# Tags kept in the cache and on the returned ways: site_analysis only reads `highway`.
_KEPT_TAGS = ("highway",)
# Added to the snapped radius of the query. Snapping moves the point at most half a grid cell on
# each axis (under 80 m diagonally), so the query circle always contains the requested circle.
QUERY_MARGIN_M = 100.0


@dataclass(frozen=True)
class OsmWay:
    """One OSM way: its tags and (lat, lon) geometry, in the order OSM returned it.

    Ways from :class:`OverpassClient` carry only the tags in :data:`_KEPT_TAGS`.
    """

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
    lat: float, lon: float, radius_m: float, timeout_s: float = QUERY_TIMEOUT_S
) -> str:
    """Overpass QL for every feature class this client knows, within radius_m of (lat, lon)."""
    around = f"around:{radius_m},{lat},{lon}"
    filters = [
        f'[highway~"^({"|".join(MAJOR_HIGHWAY_CLASSES)})$"]',
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


def _compact(features: OsmFeatures) -> dict[str, list]:
    """JSON-ready form of *features* for the cache, keeping only :data:`_KEPT_TAGS`."""
    return {
        f.name: [
            [way.id, {k: way.tags[k] for k in _KEPT_TAGS if k in way.tags}, way.coords]
            for way in getattr(features, f.name)
        ]
        for f in fields(OsmFeatures)
    }


def _expand(compact: dict[str, list]) -> OsmFeatures:
    return OsmFeatures(**{
        name: [OsmWay(id=i, tags=tags, coords=[(lat, lon) for lat, lon in coords])
               for i, tags, coords in ways]
        for name, ways in compact.items()
    })


def _reaches(way: OsmWay, origin: LocalOrigin, radius_m: float) -> bool:
    """Whether any node or segment of *way* comes within *radius_m* of *origin*.

    The same rule as Overpass's ``around`` filter for ways, measured in the local plane around
    *origin* (sub-metre agreement with the great-circle distance at these radii).
    """
    r2 = radius_m * radius_m
    pts = [to_local(lat, lon, origin) for lat, lon in way.coords]
    if any(x * x + y * y <= r2 for x, y in pts):
        return True
    for (x1, y1), (x2, y2) in zip(pts, pts[1:], strict=False):
        dx, dy = x2 - x1, y2 - y1
        length2 = dx * dx + dy * dy
        if length2 == 0:
            continue
        # Closest point of the segment to the origin, clamped to the segment.
        t = min(max(-(x1 * dx + y1 * dy) / length2, 0.0), 1.0)
        cx, cy = x1 + t * dx, y1 + t * dy
        if cx * cx + cy * cy <= r2:
            return True
    return False


def within_radius(features: OsmFeatures, lat: float, lon: float, radius_m: float) -> OsmFeatures:
    """Only the ways an ``around:radius_m,lat,lon`` query would have returned, in their order."""
    origin = LocalOrigin(lat=lat, lon=lon)
    return OsmFeatures(**{
        f.name: [w for w in getattr(features, f.name) if _reaches(w, origin, radius_m)]
        for f in fields(OsmFeatures)
    })


def _check_remark(raw: Any) -> None:
    """Overpass answers a query that hit its time or memory limit with HTTP 200, partial (often
    empty) data and a ``remark`` like "runtime error: Query timed out ...". That is a failure, and
    must never be cached as the site's data."""
    if not isinstance(raw, dict):
        raise GisUnavailableError(f"Overpass returned {type(raw).__name__}, not a JSON object")
    remark = raw.get("remark")
    if isinstance(remark, str) and "error" in remark.lower():
        raise GisUnavailableError(
            f"Overpass reported an error: {remark}", public_message=QUERY_FAILED_MESSAGE
        )


class OverpassClient:
    """Fetches and caches OSM features around a point. Pass a fake ``httpx.Client`` in tests.

    *budget* (shared by every request in the process) limits the outbound calls; ``None`` means
    no limit, which only tests and scripts use.
    """

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        cache_dir: Path | None = DEFAULT_CACHE_DIR,
        cache_ttl_days: float = CACHE_TTL_DAYS,
        budget: OutboundBudget | None = None,
    ) -> None:
        self._client = client or httpx.Client(
            timeout=outbound.default_timeout(DEFAULT_TIMEOUT_S),
            headers={"User-Agent": USER_AGENT},
        )
        self._owns_client = client is None
        self._cache_dir = cache_dir
        self._cache_ttl_days = cache_ttl_days
        self._budget = budget

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def fetch_features(
        self,
        lat: float,
        lon: float,
        radius_m: float = 500.0,
        *,
        deadline: float | None = None,
        client: str | None = None,
    ) -> OsmFeatures:
        """OSM features within *radius_m* of (lat, lon), as an exact ``around`` query finds them.

        The query is made around the snapped point (see ``cache.snap_site``) with a radius
        widened by QUERY_MARGIN_M, and the cache key is built from those same values; the result
        is then cut back to the requested circle. *deadline* is a ``time.monotonic()`` value; once
        it passes, no further attempt or retry starts. *client* identifies the visitor for the
        budget's per-client share.
        """
        q_lat, q_lon, q_radius = snap_site(lat, lon, radius_m)
        q_radius += QUERY_MARGIN_M
        # v2: entries hold the compact form (see _compact), not Overpass's raw answer.
        key = f"overpass-v2:{q_lat}:{q_lon}:{int(q_radius)}"

        def _fetch() -> dict[str, list]:
            query = build_query(q_lat, q_lon, q_radius)
            last_exc: httpx.HTTPError | None = None
            for endpoint in OVERPASS_MIRROR_ENDPOINTS:
                for attempt in range(RETRIES_PER_ENDPOINT):
                    timeout = outbound.attempt_timeout(DEFAULT_TIMEOUT_S, deadline, "Overpass")
                    try:
                        raw = self._post(endpoint, query, timeout, deadline, client)
                    except (httpx.HTTPError, ValueError) as exc:
                        # A read timeout is not retried: a query heavy enough to time out once
                        # times out again, on the mirror too, and only holds the request longer.
                        if (isinstance(exc, (ValueError, httpx.ReadTimeout))
                                or not retry.is_transient(exc)):
                            raise GisUnavailableError(
                                f"Overpass API request to {endpoint} failed: {exc!r}"
                            ) from exc
                        last_exc = exc
                        if attempt + 1 < RETRIES_PER_ENDPOINT:
                            backoff = RETRY_BACKOFF_S * (2**attempt)
                            if not outbound.can_back_off(backoff, deadline):
                                break  # no time left to back off here; try the mirror once
                            retry.sleep(backoff)
                        continue
                    _check_remark(raw)
                    return _compact(parse_features(raw))
            raise GisUnavailableError(
                f"Overpass API is unavailable after retrying {len(OVERPASS_MIRROR_ENDPOINTS)} "
                f"endpoints; it can be briefly busy -- try again shortly. Last error: {last_exc}"
            ) from last_exc

        compact = cached_get(key, self._cache_ttl_days, _fetch, cache_dir=self._cache_dir)
        return within_radius(_expand(compact), lat, lon, radius_m)

    def _post(
        self,
        endpoint: str,
        query: str,
        timeout: httpx.Timeout,
        deadline: float | None,
        client: str | None,
    ) -> Any:
        with self._budget.call(deadline, client) if self._budget else nullcontext():
            with self._client.stream(
                "POST", endpoint, data={"data": query}, timeout=timeout
            ) as response:
                response.raise_for_status()
                return outbound.read_json(response, MAX_RESPONSE_BYTES, deadline, "Overpass")
