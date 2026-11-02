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

import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import nullcontext
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

import httpx

from app.data.site_analysis_defaults import MIN_MAJOR_ROAD_RANK, ROAD_CLASS_RANK
from app.infrastructure.gis import outbound, retry
from app.infrastructure.gis.cache import DEFAULT_CACHE_DIR, cached_get, snap_site
from app.infrastructure.gis.errors import (
    BUSY_MESSAGE,
    CLIENT_QUOTA_MESSAGE,
    QUERY_FAILED_MESSAGE,
    QUOTA_MESSAGE,
    TOO_MUCH_DATA_MESSAGE,
    UNAVAILABLE_MESSAGE,
    GisUnavailableError,
)
from app.infrastructure.gis.outbound import OutboundBudget
from app.infrastructure.gis.projection import LocalOrigin, to_local

OVERPASS_ENDPOINT = "https://overpass-api.de/api/interpreter"
# The public Overpass servers are shared infrastructure and are often at capacity: overpass-api.de
# answers "502 ... all query workers are busy and the request queue is full" within 0.1 s, or
# 429/504, much of the day, and any one mirror can hang for minutes. The two independently run
# public instances that serve the whole planet and allow third-party servers are therefore
# overlapped rather than tried one after another (see OverpassClient._race). Left out on purpose:
# overpass.kumi.systems (now an alias of private.coffee), lz4./z.overpass-api.de (the nodes behind
# overpass-api.de, same limits), maps.mail.ru (blocked in Ukraine), and the regional instances
# (overpass.osm.ch has Switzerland only; overpass.openstreetmap.fr is for white-listed users).
OVERPASS_MIRROR_ENDPOINTS = (
    OVERPASS_ENDPOINT,
    "https://overpass.private.coffee/api/interpreter",
)
# A mirror that has not answered after this long gets company: the next mirror is started too,
# and the first good answer wins. A mirror that fails is replaced at once, without waiting. A
# healthy mirror answers a typical query well within this, so a hedge is rare and never doubles
# the load on one operator.
HEDGE_AFTER_S = 8.0
# No new mirror is started with less than this left before the deadline; it could not finish.
MIN_ATTEMPT_S = 2.0
# Passes over the mirrors. The second pass only retries mirrors that failed transiently (a 5xx,
# or this process holding both their slots), after a short backoff.
ROUNDS = 2
RETRY_BACKOFF_S = 1.5
# overpass-api.de gives each client IP 2 query slots and answers 429 beyond them; the mirrors run
# the same software. A mirror with both slots taken by this process is skipped, not waited for.
SLOTS_PER_ENDPOINT = 2
# Circuit breaker. After a 429 the mirror is left alone for its Retry-After (at least the first
# value below); after a refused or timed-out connection (overpass-api.de's firewall blocks
# addresses that keep sending it failing queries) for the second. Asking again sooner only extends
# such a block; meanwhile the other mirror, an expired cache entry or the browser's own fetch serve.
COOLDOWN_AFTER_429_S = 30.0
COOLDOWN_AFTER_REFUSED_S = 120.0
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
# When every mirror fails, an expired entry up to this old is served instead (roads and buildings
# rarely change within a year, and a slightly old answer beats none during a thesis defence).
STALE_TTL_DAYS = 365.0

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


# Attempts run here, not on the request's thread, so several mirrors can be in flight at once.
# Sized for every site request slot (4) racing every mirror; threads start only when needed.
_ATTEMPTS = ThreadPoolExecutor(max_workers=16, thread_name_prefix="overpass")
# Public messages that every mirror would answer the same way: the race stops at once.
_FINAL_MESSAGES = (TOO_MUCH_DATA_MESSAGE, QUOTA_MESSAGE, CLIENT_QUOTA_MESSAGE)


class _AttemptFailed(Exception):
    """One mirror's failure, and whether it is worth asking that mirror again."""

    def __init__(
        self,
        error: GisUnavailableError,
        *,
        retry: bool,
        final: bool = False,
    ):
        super().__init__(str(error))
        self.error = error
        self.retry = retry
        self.final = final or error.public_message in _FINAL_MESSAGES


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
        self._endpoint_slots = {
            endpoint: threading.BoundedSemaphore(SLOTS_PER_ENDPOINT)
            for endpoint in OVERPASS_MIRROR_ENDPOINTS
        }
        self._cooldown_until: dict[str, float] = {}  # endpoint -> time.monotonic() value

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
            return self._race(build_query(q_lat, q_lon, q_radius), deadline, client)

        compact = cached_get(
            key, self._cache_ttl_days, _fetch,
            cache_dir=self._cache_dir, stale_ttl_days=STALE_TTL_DAYS,
        )
        return within_radius(_expand(compact), lat, lon, radius_m)

    def _race(self, query: str, deadline: float | None, client: str | None) -> dict[str, list]:
        """Ask the mirrors, overlapping them, and return the first good answer.

        The first mirror starts at once. Each failure starts the next mirror immediately, and a
        mirror still silent after HEDGE_AFTER_S gets the next one started alongside it. When one
        answers, the others are told to stop reading. A failure every mirror would share (too much
        data, a spent budget, a malformed query) ends the race at once. After a full pass, the
        mirrors that failed transiently are tried once more, after a backoff. A mirror cooling
        down after a 429 or a refused connection is skipped.

        Only the first attempt is charged to *client*: a visitor's daily share counts lookups,
        not how many mirrors this server needed to answer one.
        """
        endpoints = list(OVERPASS_MIRROR_ENDPOINTS)
        charge = [client]
        stop = threading.Event()
        failures: list[GisUnavailableError] = []

        def start(queue: list[str], pending: dict[Future, str]) -> None:
            if queue:
                endpoint = queue.pop(0)
                who = charge.pop() if charge else None
                future = _ATTEMPTS.submit(self._attempt, endpoint, query, deadline, who, stop)
                pending[future] = endpoint

        try:
            for round_no in range(ROUNDS):
                retryable = []
                queue = list(endpoints)
                pending: dict[Future, str] = {}
                start(queue, pending)
                while pending:
                    left = outbound.time_left(deadline, "Overpass")
                    hedge = bool(queue) and (left is None or left > HEDGE_AFTER_S + MIN_ATTEMPT_S)
                    timeout = HEDGE_AFTER_S if hedge else left
                    done, _ = wait(pending, timeout=timeout, return_when=FIRST_COMPLETED)
                    if not done:
                        if hedge:
                            start(queue, pending)
                        continue
                    for future in done:
                        endpoint = pending.pop(future)
                        try:
                            return future.result()
                        except _AttemptFailed as failed:
                            failures.append(failed.error)
                            if failed.final:
                                raise failed.error from failed
                            if failed.retry:
                                retryable.append(endpoint)
                        left = outbound.time_left(deadline, "Overpass")
                        if left is None or left > MIN_ATTEMPT_S:
                            start(queue, pending)
                endpoints = retryable
                if not endpoints or round_no + 1 == ROUNDS:
                    break
                if not outbound.can_back_off(RETRY_BACKOFF_S + MIN_ATTEMPT_S, deadline):
                    break
                retry.sleep(RETRY_BACKOFF_S)
        finally:
            stop.set()

        # Every mirror failed. A query every mirror ran out of time or memory on is the planner's
        # to shrink; anything else is the service being unavailable.
        timed_out = failures and all(f.public_message == QUERY_FAILED_MESSAGE for f in failures)
        raise GisUnavailableError(
            f"Overpass API is unavailable after retrying {len(OVERPASS_MIRROR_ENDPOINTS)} "
            f"endpoints; it can be briefly busy -- try again shortly. Errors: "
            + "; ".join(str(f) for f in failures),
            public_message=QUERY_FAILED_MESSAGE if timed_out else UNAVAILABLE_MESSAGE,
            retry_after_s=10,
        )

    def _attempt(
        self,
        endpoint: str,
        query: str,
        deadline: float | None,
        client: str | None,
        stop: threading.Event,
    ) -> dict[str, list]:
        """One request to one mirror, as the compact cache form. Raises :class:`_AttemptFailed`."""
        if stop.is_set():
            raise _AttemptFailed(GisUnavailableError(f"{endpoint}: race already won"), retry=False)
        if time.monotonic() < self._cooldown_until.get(endpoint, 0.0):
            raise _AttemptFailed(GisUnavailableError(f"{endpoint}: cooling down"), retry=False)
        slots = self._endpoint_slots[endpoint]
        if not slots.acquire(blocking=False):
            raise _AttemptFailed(
                GisUnavailableError(f"{endpoint}: both of this server's query slots are in use"),
                retry=True,
            )
        try:
            timeout = outbound.attempt_timeout(DEFAULT_TIMEOUT_S, deadline, "Overpass")
            raw = self._post(endpoint, query, timeout, deadline, client, stop)
            _check_remark(raw)
            return _compact(parse_features(raw))
        except GisUnavailableError as exc:
            # The budget's refusals and the size cap; a busy budget slot may free up.
            raise _AttemptFailed(exc, retry=exc.public_message == BUSY_MESSAGE) from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            error = GisUnavailableError(f"Overpass API request to {endpoint} failed: {exc!r}")
            # 400: our query is malformed, and every mirror runs the same software. Other 4xx
            # (403, 406, 429) are one mirror's policy, so the race goes on without it.
            if status == 429:
                self._cool_down(
                    endpoint, max(COOLDOWN_AFTER_429_S, _retry_after_s(exc.response))
                )
            raise _AttemptFailed(error, retry=status >= 500, final=status == 400) from exc
        except (httpx.HTTPError, ValueError) as exc:
            if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
                self._cool_down(endpoint, COOLDOWN_AFTER_REFUSED_S)
                raise _AttemptFailed(
                    GisUnavailableError(f"Overpass API request to {endpoint} failed: {exc!r}"),
                    retry=False,
                ) from exc
            # A read timeout is not retried on the same mirror: a query heavy enough to time out
            # once times out again there. Another mirror may still be fast enough.
            raise _AttemptFailed(
                GisUnavailableError(f"Overpass API request to {endpoint} failed: {exc!r}"),
                retry=isinstance(exc, httpx.HTTPError) and not isinstance(exc, httpx.ReadTimeout)
                and retry.is_transient(exc),
            ) from exc
        finally:
            slots.release()

    def _cool_down(self, endpoint: str, seconds: float) -> None:
        self._cooldown_until[endpoint] = time.monotonic() + seconds

    def _post(
        self,
        endpoint: str,
        query: str,
        timeout: httpx.Timeout,
        deadline: float | None,
        client: str | None,
        stop: threading.Event | None = None,
    ) -> Any:
        with self._budget.call(deadline, client) if self._budget else nullcontext():
            with self._client.stream(
                "POST", endpoint, data={"data": query}, timeout=timeout
            ) as response:
                response.raise_for_status()
                return outbound.read_json(
                    response, MAX_RESPONSE_BYTES, deadline, "Overpass", stop
                )


def _retry_after_s(response: httpx.Response) -> float:
    """A Retry-After in seconds (Overpass sends one with 429), or 0 if absent or a date."""
    value = response.headers.get("retry-after", "")
    return float(value) if value.isdigit() else 0.0
