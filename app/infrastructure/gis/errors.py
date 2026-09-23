"""Shared error type for GIS clients."""

from __future__ import annotations


class GisUnavailableError(RuntimeError):
    """An external GIS service (Overpass, elevation) could not be reached or timed out.

    The only failure mode the API layer needs to handle for GIS calls — see
    ``backend/site_routes.py``, which maps this to HTTP 503. Site analysis is an assist feature;
    every project parameter it would fill in can still be set manually, so this is never fatal to
    using the app.
    """
