"""
Elevation client (Open Topo Data / SRTM 90 m, falling back to Open-Meteo / Copernicus GLO-90) for a
grid of sample points around a site.

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
from app.infrastructure.gis.errors import CLIENT_QUOTA_MESSAGE, GisUnavailableError
from app.infrastructure.gis.outbound import OutboundBudget
from app.infrastructure.gis.projection import LocalOrigin, to_latlon

ELEVATION_ENDPOINT = "https://api.opentopodata.org/v1/srtm90m"
# Used when Open Topo Data fails or its daily quota is spent: Open-Meteo serves the Copernicus
# GLO-90 DEM, the same 90 m resolution as SRTM 90 m, takes up to 100 points per call and allows
# 10,000 calls a day for non-commercial use. The terrain class comes from grades over 250 m grid
# spacing, where the two models agree far closer than the 3 % / 8 % class bounds.
FALLBACK_ENDPOINT = "https://api.open-meteo.com/v1/elevation"
# A short retry on Open Topo Data smooths over a transient blip before falling back.
RETRIES = 2
RETRY_BACKOFF_S = 1.5
DEFAULT_TIMEOUT_S = 15.0  # read timeout per socket read; see outbound.py for the others
# Same courtesy as overpass.py: identify the application rather than sending httpx's default UA.
USER_AGENT = "TDSS-diploma-thesis/1.0 (+https://github.com/vetos5/TDSS)"
CACHE_TTL_DAYS = 30.0
STALE_TTL_DAYS = 365.0  # served when both services fail; terrain does not change
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

    Pass a fake ``httpx.Client`` in tests. *budget* and *fallback_budget* (each shared by every
    request in the process) limit the calls to Open Topo Data and to Open-Meteo; ``None`` means no
    limit, which only tests and scripts use.
    """

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        cache_dir: Path | None = DEFAULT_CACHE_DIR,
        cache_ttl_days: float = CACHE_TTL_DAYS,
        budget: OutboundBudget | None = None,
        fallback_budget: OutboundBudget | None = None,
    ) -> None:
        self._client = client or httpx.Client(
            timeout=outbound.default_timeout(DEFAULT_TIMEOUT_S),
            headers={"User-Agent": USER_AGENT},
        )
        self._owns_client = client is None
        self._cache_dir = cache_dir
        self._cache_ttl_days = cache_ttl_days
        self._budget = budget
        self._fallback_budget = fallback_budget

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
            try:
                return self._fetch_open_topo_data(points, deadline, client)
            except GisUnavailableError as primary:
                if primary.public_message == CLIENT_QUOTA_MESSAGE:
                    raise  # the visitor's share is spent; the fallback is no way round it
                try:
                    # Not charged to the visitor again: it is the same lookup.
                    return self._fetch_open_meteo(points, deadline)
                except GisUnavailableError as fallback:
                    raise GisUnavailableError(
                        f"{primary}; fallback: {fallback}",
                        public_message=primary.public_message,
                        retry_after_s=primary.retry_after_s,
                    ) from fallback

        payload = cached_get(
            key, self._cache_ttl_days, _fetch,
            cache_dir=self._cache_dir, stale_ttl_days=STALE_TTL_DAYS,
        )
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

    def _fetch_open_topo_data(
        self, points: list[tuple[float, float]], deadline: float | None, client: str | None
    ) -> dict[str, Any]:
        locations = "|".join(f"{plat:.6f},{plon:.6f}" for plat, plon in points)
        last_exc: httpx.HTTPError | None = None
        for attempt in range(RETRIES):
            timeout = outbound.attempt_timeout(DEFAULT_TIMEOUT_S, deadline, "Elevation API")
            try:
                payload = self._get(
                    ELEVATION_ENDPOINT, {"locations": locations}, timeout, deadline, client,
                    self._budget,
                )
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

    def _fetch_open_meteo(
        self, points: list[tuple[float, float]], deadline: float | None
    ) -> dict[str, Any]:
        """Open-Meteo's answer, in Open Topo Data's shape so the cache and parser stay one."""
        params = {
            "latitude": ",".join(f"{plat:.6f}" for plat, _ in points),
            "longitude": ",".join(f"{plon:.6f}" for _, plon in points),
        }
        timeout = outbound.attempt_timeout(DEFAULT_TIMEOUT_S, deadline, "Open-Meteo")
        try:
            payload = self._get(
                FALLBACK_ENDPOINT, params, timeout, deadline, None, self._fallback_budget
            )
            elevations = payload["elevation"]
            if not isinstance(elevations, list):
                raise ValueError("elevation is not a list")
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise GisUnavailableError(f"Open-Meteo elevation request failed: {exc!r}") from exc
        return {"status": "OK", "results": [{"elevation": e} for e in elevations]}

    def _get(
        self,
        endpoint: str,
        params: dict[str, str],
        timeout: httpx.Timeout,
        deadline: float | None,
        client: str | None,
        budget: OutboundBudget | None,
    ) -> Any:
        with budget.call(deadline, client) if budget else nullcontext():
            with self._client.stream(
                "GET", endpoint, params=params, timeout=timeout
            ) as response:
                response.raise_for_status()
                return outbound.read_json(
                    response, MAX_RESPONSE_BYTES, deadline, "Elevation API"
                )
