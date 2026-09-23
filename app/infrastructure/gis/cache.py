"""
Small disk cache for external GIS responses.

Overpass and Open Topo Data are public, rate-limited services (Overpass in particular can be
slow or briefly refuse requests when busy — observed directly against the live server during
development). Caching means a repeated demo, or a thesis defense, doesn't depend on either
service being fast or even reachable at that exact moment, and doesn't hammer them needlessly.

Not a general-purpose cache: single JSON file per key, no eviction beyond the TTL check on read,
and any read/write failure is treated as a cache miss rather than an error — a broken cache
should never be the reason a request fails.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable

# app/infrastructure/gis/cache.py -> repo root is three levels up.
DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[3] / ".cache" / "gis"


def _path_for(key: str, cache_dir: Path) -> Path:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return cache_dir / f"{digest}.json"


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
    """
    if cache_dir is None:
        return fetch()

    path = _path_for(key, cache_dir)
    try:
        payload = json.loads(path.read_text())
        if time.time() - payload["cached_at"] < ttl_days * 86400:
            return payload["data"]
    except (OSError, ValueError, KeyError):
        pass  # missing, corrupt, or expired -- fall through to a fresh fetch

    data = fetch()

    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"cached_at": time.time(), "data": data}))
    except OSError:
        pass  # caching is an optimisation, never a requirement

    return data
