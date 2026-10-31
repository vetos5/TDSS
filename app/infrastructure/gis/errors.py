"""Shared error type for GIS clients."""

from __future__ import annotations

# Fixed texts the API returns with a 503. The upstream URL and httpx/OS error text stay in
# ``str(exc)``, which is only logged server-side. BUSY_MESSAGE starts like backend.limits' busy
# text, which the frontend (api.js) replaces with its own localised wording.
UNAVAILABLE_MESSAGE = "The map data service is unavailable right now. Try again in a minute."
BUSY_MESSAGE = "The server is busy with other map data requests. Try again in a few seconds."
QUOTA_MESSAGE = (
    "Today's quota of map data requests is used up. Points analysed before still work; "
    "try new points tomorrow."
)
CLIENT_QUOTA_MESSAGE = (
    "You have used today's share of new map data requests. Points analysed before still work; "
    "try new points tomorrow."
)
TOO_MUCH_DATA_MESSAGE = "There is too much map data around this point. Choose a smaller radius."
QUERY_FAILED_MESSAGE = (
    "The map data service could not finish this query. Try a smaller radius or try again later."
)


class GisUnavailableError(RuntimeError):
    """An external GIS service (Overpass, elevation) could not be reached or timed out.

    The only failure mode the API layer needs to handle for GIS calls — see
    ``backend/site_routes.py``, which maps this to HTTP 503. Site analysis is an assist feature;
    every project parameter it would fill in can still be set manually, so this is never fatal to
    using the app.

    ``str(exc)`` is the internal detail for the server log. ``public_message`` is the fixed text
    for the client, and ``retry_after_s`` (when set) becomes the 503's Retry-After header.
    """

    def __init__(
        self,
        detail: str,
        *,
        public_message: str = UNAVAILABLE_MESSAGE,
        retry_after_s: int | None = None,
    ) -> None:
        super().__init__(detail)
        self.public_message = public_message
        self.retry_after_s = retry_after_s
