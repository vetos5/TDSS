"""
Small disk cache for external GIS responses.

Overpass and Open Topo Data are public, rate-limited services (Overpass in particular can be
slow or briefly refuse requests when busy — observed directly against the live server during
development). Caching means a repeated demo, or a thesis defense, doesn't depend on either
service being fast or even reachable at that exact moment, and doesn't hammer them needlessly.

Not a general-purpose cache: single JSON file per key, written atomically, and any read/write
failure is treated as a cache miss rather than an error — a broken cache should never be the
reason a request fails. Concurrent misses for one key share a single fetch (see
:func:`cached_get`), and every :data:`PRUNE_EVERY_N_WRITES` writes the directory is pruned of
expired files and capped at :data:`MAX_CACHE_BYTES`, oldest first.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

# app/infrastructure/gis/cache.py -> repo root is three levels up.
DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[3] / ".cache" / "gis"

# Overpass requests are snapped to this grid before both the cache key and the upstream query are
# built, so the cached data always matches its key, and nearby map clicks share one entry and one
# upstream call. 3 decimals is about 110 m north-south; the UI's radius slider moves in 50 m steps.
GRID_DECIMALS = 3
RADIUS_STEP_M = 50.0

MAX_CACHE_BYTES = 500 * 1024 * 1024
# One entry above this is not written. The Overpass client already refuses bodies over 15 MB, so
# this only guards against a future caller caching something unexpectedly large.
MAX_ENTRY_BYTES = 16 * 1024 * 1024
PRUNE_EVERY_N_WRITES = 50
# A leftover temp file older than this is from a write that died midway.
_STALE_TMP_S = 3600.0

_MISS = object()
_write_count = itertools.count()


def snap_site(lat: float, lon: float, radius_m: float) -> tuple[float, float, float]:
    """(lat, lon) rounded to the cache grid and the radius rounded up to the next 50 m step."""
    radius = max(RADIUS_STEP_M, math.ceil(radius_m / RADIUS_STEP_M) * RADIUS_STEP_M)
    return round(lat, GRID_DECIMALS), round(lon, GRID_DECIMALS), radius


def _path_for(key: str, cache_dir: Path) -> Path:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return cache_dir / f"{digest}.json"


class _Flight:
    """One in-progress fetch that concurrent misses for the same key wait on."""

    def __init__(self) -> None:
        self.done = threading.Event()
        self.ok = False
        self.value: Any = None


_flights: dict[Path, _Flight] = {}  # keyed by cache file, so two cache dirs never share
_flights_lock = threading.Lock()


def cached_get(
    key: str,
    ttl_days: float,
    fetch: Callable[[], Any],
    *,
    cache_dir: Path | None = DEFAULT_CACHE_DIR,
) -> Any:
    """
    Return the cached value for *key* if present and younger than *ttl_days*, else call *fetch*
    and cache its result. ``cache_dir=None`` disables caching entirely (every call hits *fetch*).

    *fetch* raising is never caught here — a failed fetch propagates to the caller and nothing is
    written to the cache, so the next call retries instead of caching a failure.

    Single-flight: while one caller fetches a key, other callers for that key wait and get its
    result instead of fetching again. If that fetch fails, each waiter then tries its own fetch
    (in turn), which runs under that waiter's own deadline and outbound budget.
    """
    if cache_dir is None:
        return fetch()

    path = _path_for(key, cache_dir)
    while True:
        hit = _read(path, ttl_days)
        if hit is not _MISS:
            return hit
        with _flights_lock:
            flight = _flights.get(path)
            leading = flight is None
            if leading:
                flight = _flights[path] = _Flight()
        if leading:
            break
        flight.done.wait()
        if flight.ok:
            return flight.value

    written = False
    try:
        # Another caller may have finished and written the entry between our read and taking
        # the lead.
        data = _read(path, ttl_days)
        if data is _MISS:
            data = fetch()
            written = _write(path, cache_dir, data)
        flight.ok, flight.value = True, data
    finally:
        with _flights_lock:
            del _flights[path]
        flight.done.set()
    if written and next(_write_count) % PRUNE_EVERY_N_WRITES == 0:
        prune(cache_dir, max_age_s=ttl_days * 86400)
    return data


def _read(path: Path, ttl_days: float) -> Any:
    try:
        payload = json.loads(path.read_bytes())
        if time.time() - payload["cached_at"] < ttl_days * 86400:
            return payload["data"]
    except (OSError, ValueError, KeyError, TypeError):
        pass  # missing, corrupt, or expired -- fall through to a fresh fetch
    return _MISS


def _write(path: Path, cache_dir: Path, data: Any) -> bool:
    """Write via a temp file and an atomic rename, so a reader never sees a half-written file."""
    blob = json.dumps({"cached_at": time.time(), "data": data}).encode("utf-8")
    if len(blob) > MAX_ENTRY_BYTES:
        return False
    tmp = None
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=cache_dir, suffix=".tmp")
        with os.fdopen(fd, "wb") as f:
            f.write(blob)
        os.replace(tmp, path)
    except OSError:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        return False  # caching is an optimisation, never a requirement
    return True


def prune(cache_dir: Path, max_age_s: float, max_bytes: int = MAX_CACHE_BYTES) -> None:
    """Delete expired entries and stale temp files, then the oldest entries above *max_bytes*.

    Age is the file's modification time, which is when it was written. Runs on the first write
    after start-up and every :data:`PRUNE_EVERY_N_WRITES` writes after that, so its directory
    scan is not paid on every request.
    """
    now = time.time()
    entries: list[tuple[float, int, Path]] = []
    try:
        paths = list(cache_dir.iterdir())
    except OSError:
        return
    for path in paths:
        try:
            st = path.stat()
            if path.suffix == ".tmp":
                if now - st.st_mtime > _STALE_TMP_S:
                    path.unlink()
            elif path.suffix == ".json":
                if now - st.st_mtime > max_age_s:
                    path.unlink()
                else:
                    entries.append((st.st_mtime, st.st_size, path))
        except OSError:
            continue
    total = sum(size for _, size, _ in entries)
    for _, size, path in sorted(entries):
        if total <= max_bytes:
            break
        try:
            path.unlink()
            total -= size
        except OSError:
            continue
