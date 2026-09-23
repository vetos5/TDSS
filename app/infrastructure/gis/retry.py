"""Shared retry helpers for the Overpass and elevation HTTP clients."""

from __future__ import annotations

import time

import httpx

# Referenced via the module (not `from ... import sleep`) so tests can monkeypatch
# `retry.sleep` and have every caller pick up the patched version.
sleep = time.sleep


def is_transient(exc: httpx.HTTPError) -> bool:
    """Worth retrying: a timeout, or a 5xx (server-side/gateway) response.

    Not a 4xx -- retrying a malformed or rejected request just wastes the same amount of time
    failing again the same way.
    """
    if isinstance(exc, httpx.TimeoutException):
        return True
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code >= 500
