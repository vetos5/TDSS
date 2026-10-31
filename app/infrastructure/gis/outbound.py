"""
Limits on outbound calls to the public GIS APIs: a per-request deadline, per-attempt timeouts, a
response-size cap and a process-wide call budget.

Overpass and Open Topo Data are free shared services with fair-use limits. A public deployment
must not let one visitor (or a script) tie up the API's worker threads waiting on them, nor get
the server's IP rate-limited or banned by them. Every outbound call therefore goes through an
:class:`OutboundBudget` and is bounded in time and size.
"""

from __future__ import annotations

import json
import math
import threading
import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator

import httpx

from app.infrastructure.gis import retry
from app.infrastructure.gis.errors import (
    BUSY_MESSAGE,
    CLIENT_QUOTA_MESSAGE,
    QUOTA_MESSAGE,
    TOO_MUCH_DATA_MESSAGE,
    GisUnavailableError,
)

# Connecting, sending the small request and waiting for a pooled connection are quick when the
# service is healthy, so they get short limits. The read timeout is per socket read and is set
# per client; the per-request deadline bounds the total.
CONNECT_TIMEOUT_S = 5.0
WRITE_TIMEOUT_S = 5.0
POOL_TIMEOUT_S = 2.0

_DAY_S = 86400.0
# Expired per-client entries are dropped once more clients than this are being tracked.
_MAX_TRACKED_CLIENTS = 10_000


def default_timeout(read_s: float) -> httpx.Timeout:
    return httpx.Timeout(
        read_s, connect=CONNECT_TIMEOUT_S, write=WRITE_TIMEOUT_S, pool=POOL_TIMEOUT_S
    )


def time_left(deadline: float | None, service: str) -> float | None:
    """Seconds until *deadline* (a ``time.monotonic()`` value); raises once it has passed.

    ``None`` means no deadline (direct use of a client, e.g. in tests) and returns ``None``.
    """
    if deadline is None:
        return None
    left = deadline - time.monotonic()
    if left <= 0:
        raise GisUnavailableError(f"{service}: the request deadline passed before the call")
    return left


def attempt_timeout(read_s: float, deadline: float | None, service: str) -> httpx.Timeout:
    """The client's timeouts, each cut down to the time left before *deadline*."""
    left = time_left(deadline, service)
    if left is None:
        return default_timeout(read_s)
    return httpx.Timeout(
        min(read_s, left),
        connect=min(CONNECT_TIMEOUT_S, left),
        write=min(WRITE_TIMEOUT_S, left),
        pool=min(POOL_TIMEOUT_S, left),
    )


def can_back_off(delay_s: float, deadline: float | None) -> bool:
    """Whether sleeping *delay_s* before a retry still leaves time before *deadline*."""
    return deadline is None or time.monotonic() + delay_s < deadline


def read_json(
    response: httpx.Response, max_bytes: int, deadline: float | None, service: str
) -> Any:
    """Read a streamed response body and parse it as JSON, refusing bodies over *max_bytes*.

    The body is counted after decompression, as it arrives, so an oversized answer is dropped
    before it is held in memory. The deadline is checked between chunks: the read timeout only
    bounds each socket read, so a slow trickle could otherwise run far past it.
    """
    declared = response.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > max_bytes:
        raise GisUnavailableError(
            f"{service}: response of {declared} bytes is over the {max_bytes}-byte cap",
            public_message=TOO_MUCH_DATA_MESSAGE,
        )
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_bytes():
        size += len(chunk)
        if size > max_bytes:
            raise GisUnavailableError(
                f"{service}: response is over the {max_bytes}-byte cap",
                public_message=TOO_MUCH_DATA_MESSAGE,
            )
        time_left(deadline, service)
        chunks.append(chunk)
    return json.loads(b"".join(chunks))


class OutboundBudget:
    """Process-wide limits on calls to one public API: concurrency, spacing and daily totals.

    Every HTTP attempt counts, retries included. A call that cannot get a slot before its deadline
    (or *max_wait_s* without one) is refused as busy; once *per_day* calls have been made in the
    current 24-hour window, calls are refused until the window ends. With *per_client_per_day*,
    each client (as the caller names it) also gets its own smaller daily share, so one visitor
    cannot spend the whole budget. Refusals raise :class:`GisUnavailableError`, which the API
    answers with 503, and a refused call is never charged. Cache hits never reach here.
    """

    def __init__(
        self,
        service: str,
        *,
        max_concurrent: int,
        per_day: int,
        per_client_per_day: int | None = None,
        min_interval_s: float = 0.0,
        max_wait_s: float = 20.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._service = service
        self._slots = threading.BoundedSemaphore(max_concurrent)
        self._per_day = per_day
        self._per_client_per_day = per_client_per_day
        self._min_interval_s = min_interval_s
        self._max_wait_s = max_wait_s
        self._clock = clock
        self._lock = threading.Lock()
        self._window_start = clock()
        self._used = 0
        self._clients: dict[str, tuple[float, int]] = {}  # client -> (window start, calls)
        self._next_start = 0.0

    @contextmanager
    def call(self, deadline: float | None = None, client: str | None = None) -> Iterator[None]:
        left = time_left(deadline, self._service)
        wait_s = self._max_wait_s if left is None else min(self._max_wait_s, left)
        if not self._slots.acquire(timeout=wait_s):
            raise GisUnavailableError(
                f"{self._service}: no free outbound slot within {wait_s:.1f} s",
                public_message=BUSY_MESSAGE,
                retry_after_s=5,
            )
        try:
            delay = self._admit(deadline, client)
            if delay > 0:
                retry.sleep(delay)
            yield
        finally:
            self._slots.release()

    def _admit(self, deadline: float | None, client: str | None) -> float:
        """Check spacing, the daily total and the client's share; charge only if all pass.

        Returns how long to wait before the call to keep *min_interval_s* between starts.
        """
        with self._lock:
            now = self._clock()
            start = max(now, self._next_start)
            delay = start - now
            if delay > 0 and not can_back_off(delay, deadline):
                raise GisUnavailableError(
                    f"{self._service}: next call slot is {delay:.1f} s away, past the deadline",
                    public_message=BUSY_MESSAGE,
                    retry_after_s=5,
                )
            if now - self._window_start >= _DAY_S:
                self._window_start, self._used = now, 0
            if self._used >= self._per_day:
                raise GisUnavailableError(
                    f"{self._service}: daily budget of {self._per_day} calls is used up",
                    public_message=QUOTA_MESSAGE,
                    retry_after_s=_seconds_until(self._window_start + _DAY_S, now),
                )
            if client is not None and self._per_client_per_day is not None:
                self._charge_client(client, now)
            self._used += 1
            self._next_start = start + self._min_interval_s
            return delay

    def _charge_client(self, client: str, now: float) -> None:
        if len(self._clients) > _MAX_TRACKED_CLIENTS:
            self._clients = {
                c: entry for c, entry in self._clients.items() if now - entry[0] < _DAY_S
            }
        window_start, used = self._clients.get(client, (now, 0))
        if now - window_start >= _DAY_S:
            window_start, used = now, 0
        if used >= self._per_client_per_day:
            raise GisUnavailableError(
                f"{self._service}: client {client} used its {self._per_client_per_day} daily calls",
                public_message=CLIENT_QUOTA_MESSAGE,
                retry_after_s=_seconds_until(window_start + _DAY_S, now),
            )
        self._clients[client] = (window_start, used + 1)


def _seconds_until(when: float, now: float) -> int:
    return max(1, math.ceil(when - now))
