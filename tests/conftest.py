"""Shared pytest fixtures."""

import pytest

from app.infrastructure.gis import retry


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    """Never actually sleep during retry backoff -- tests exercise the retry *logic*, not timing."""
    monkeypatch.setattr(retry, "sleep", lambda seconds: None)
