"""
Admin token for the endpoints that change the server's data (corpus uploads, deletes, retrains).

Everything else stays public. The token is the ``TDSS_ADMIN_TOKEN`` environment variable, read on
every request so that tests and restarts pick up a change, and clients send it as
``Authorization: Bearer <token>``. Without the variable, corpus editing is switched off rather than
open: a server that was deployed without a token must not accept anonymous writes.
"""

from __future__ import annotations

import hmac
import os
from typing import Annotated, Optional

from fastapi import Header, HTTPException

TOKEN_ENV = "TDSS_ADMIN_TOKEN"
# A token shorter than this is a password someone could guess, not a generated secret.
MIN_TOKEN_LENGTH = 16


def configured_token() -> Optional[str]:
    token = os.environ.get(TOKEN_ENV, "").strip()
    return token if len(token) >= MIN_TOKEN_LENGTH else None


def editing_enabled() -> bool:
    return configured_token() is not None


def require_admin(authorization: Annotated[Optional[str], Header()] = None) -> None:
    """FastAPI dependency: 403 when editing is off, 401 unless the bearer token matches."""
    token = configured_token()
    if token is None:
        raise HTTPException(status_code=403, detail="Corpus editing is disabled on this server.")
    scheme, _, supplied = (authorization or "").partition(" ")
    # compare_digest takes the same time wherever the strings differ, so timing gives nothing away.
    if scheme.lower() != "bearer" or not hmac.compare_digest(
        supplied.strip().encode(), token.encode()
    ):
        raise HTTPException(
            status_code=401,
            detail="A valid admin token is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
