"""
Concurrency caps for the costly endpoints.

The server runs one worker, and every sync handler shares AnyIO's thread pool (40 threads). A few
slow requests (SMAA, GIS calls that wait on public APIs) could otherwise occupy all of it and stall
every other route, the health check included. Each costly endpoint therefore gets a fixed number of
slots; a request that finds them all taken is answered 503 at once instead of queueing.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator

from fastapi import HTTPException


@contextmanager
def slot(slots: threading.BoundedSemaphore, retry_after_s: int = 5) -> Iterator[None]:
    if not slots.acquire(blocking=False):
        raise HTTPException(
            status_code=503,
            detail="The server is busy with other analyses. Try again in a few seconds.",
            headers={"Retry-After": str(retry_after_s)},
        )
    try:
        yield
    finally:
        slots.release()
