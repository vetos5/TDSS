"""
Elevation client (Open Topo Data / SRTM 90 m) for a grid of sample points around a site.

An n×n grid spanning [-radius_m, +radius_m] on each axis is fetched in a single batched request
(Open Topo Data accepts up to 100 locations per call; the default 5×5 = 25 points stays well
under that). ``app.application.site_analysis`` turns the grid into slope statistics for the
terrain classification.
"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.infrastructure.gis import outbound, retry
from app.infrastructure.gis.cache import DEFAULT_CACHE_DIR, cached_get
from app.infrastructure.gis.errors import GisUnavailableError
from app.infrastructure.gis.outbound import OutboundBudget
from app.infrastructure.gis.projection import LocalOrigin, to_latlon

ELEVATION_ENDPOINT = "https://api.opentopodata.org/v1/srtm90m"
# No known public mirror, unlike Overpass -- but a short retry still smooths over a transient
# blip without needing one.
RETRIES = 2
RETRY_BACKOFF_S = 1.5
DEFAULT_TIMEOUT_S = 15.0  # read timeout per socket read; see outbound.py for the others
# Same courtesy as overpass.py: identify the application rather than sending httpx's default UA.
USER_AGENT = "TDSS-diploma-thesis/1.0 (+https://github.com/vetos5/TDSS)"
CACHE_TTL_DAYS = 30.0
MAX_LOCATIONS_PER_REQUEST = 100
# 100 points of JSON is a few kB; anything near this is not an Open Topo Data answer.
MAX_RESPONSE_BYTES = 1024 * 1024


@dataclass(frozen=True)
class ElevationPoint:
    lat: float
    lon: float
    elevation_m: float | None  # None where the dataset has no value (e.g. open ocean)


@dataclass(frozen=True)
class ElevationGrid:
    origin: LocalOrigin
    radius_m: float
    n: int
    points: list[ElevationPoint]  # row-major, length n*n

    def elevations(self) -> list[float]:
        """Known elevations only, in grid order (skips any point the dataset couldn't answer)."""
        return [p.elevation_m for p in self.points if p.elevation_m is not None]


def grid_points(origin: LocalOrigin, radius_m: float, n: int) -> list[tuple[float, float]]:
    """(lat, lon) of an n×n grid spanning [-radius_m, radius_m] on each local axis, row-major."""
    if n < 1:
        raise ValueError("n must be at least 1")
    offsets = [0.0] if n == 1 else [-radius_m + 2 * radius_m * i / (n - 1) for i in range(n)]
    return [to_latlon(x, y, origin) for y in offsets for x in offsets]


class ElevationClient:
    """Fetches and caches an elevation grid around a point.

    Pass a fake ``httpx.Client`` in tests. *budget* (shared by every request in the process)
    limits the outbound calls; ``None`` means no limit, which only tests and scripts use.
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

    def fetch_grid(
        self,
        lat: float,
        lon: float,
        radius_m: float = 500.0,
        n: int = 5,
        *,
        deadline: float | None = None,
        client: str | None = None,
    ) -> ElevationGrid:
        """An n×n elevation grid around (lat, lon).

        Not snapped to the cache grid, unlike the Overpass query: the steepest grade depends on
        exactly where the grid points fall, so only an identical request is a cache hit.
        *deadline* is a ``time.monotonic()`` value; *client* is as in ``fetch_features``.
        """
        if n * n > MAX_LOCATIONS_PER_REQUEST:
            raise ValueError(
                f"{n}x{n} grid exceeds the {MAX_LOCATIONS_PER_REQUEST}-location batch limit"
            )

        origin = LocalOrigin(lat=lat, lon=lon)
        points = grid_points(origin, radius_m, n)
        # Full float reprs, so the key determines the grid points exactly.
        key = f"elevation:{lat!r}:{lon!r}:{radius_m!r}:{n}"

        def _fetch() -> dict[str, Any]:
            locations = "|".join(f"{plat:.6f},{plon:.6f}" for plat, plon in points)
            last_exc: httpx.HTTPError | None = None
            for attempt in range(RETRIES):
                timeout = outbound.attempt_timeout(DEFAULT_TIMEOUT_S, deadline, "Elevation API")
                try:
                    payload = self._get(locations, timeout, deadline, client)
                    if payload.get("status") != "OK":
                        detail = payload.get("error", "unknown status")
                        raise GisUnavailableError(f"Elevation API error: {detail}")
                    return payload
                except (httpx.HTTPError, ValueError) as exc:
                    if isinstance(exc, ValueError) or not retry.is_transient(exc):
                        raise GisUnavailableError(f"Elevation API request failed: {exc}") from exc
                    last_exc = exc
                    if attempt + 1 < RETRIES:
                        backoff = RETRY_BACKOFF_S * (2**attempt)
                        if not outbound.can_back_off(backoff, deadline):
                            break
                        retry.sleep(backoff)
            raise GisUnavailableError(
                f"Elevation API timed out after {RETRIES} attempts; try again shortly. "
                f"Last error: {last_exc!r}"
            ) from last_exc

        payload = cached_get(key, self._cache_ttl_days, _fetch, cache_dir=self._cache_dir)
        results = payload["results"]
        if len(results) != len(points):
            raise GisUnavailableError(
                f"Elevation API returned {len(results)} results for {len(points)} requested points"
            )
        grid = [
            ElevationPoint(lat=plat, lon=plon, elevation_m=r.get("elevation"))
            for (plat, plon), r in zip(points, results, strict=True)
        ]
        return ElevationGrid(origin=origin, radius_m=radius_m, n=n, points=grid)

    def _get(
        self,
        locations: str,
        timeout: httpx.Timeout,
        deadline: float | None,
        client: str | None,
    ) -> Any:
        with self._budget.call(deadline, client) if self._budget else nullcontext():
            with self._client.stream(
                "GET", ELEVATION_ENDPOINT, params={"locations": locations}, timeout=timeout
            ) as response:
                response.raise_for_status()
                return outbound.read_json(
                    response, MAX_RESPONSE_BYTES, deadline, "Elevation API"
                )
