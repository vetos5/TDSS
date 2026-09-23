"""Disk cache: hits, misses, TTL expiry, and tolerance of a broken cache."""

import json
import time

import pytest

from app.infrastructure.gis.cache import cached_get


def test_disabled_cache_always_calls_fetch(tmp_path):
    calls = []

    def fetch():
        calls.append(1)
        return {"n": len(calls)}

    assert cached_get("k", 30, fetch, cache_dir=None) == {"n": 1}
    assert cached_get("k", 30, fetch, cache_dir=None) == {"n": 2}


def test_second_call_is_a_cache_hit(tmp_path):
    calls = []

    def fetch():
        calls.append(1)
        return {"value": 42}

    first = cached_get("site", 30, fetch, cache_dir=tmp_path)
    second = cached_get("site", 30, fetch, cache_dir=tmp_path)
    assert first == second == {"value": 42}
    assert len(calls) == 1


def test_different_keys_do_not_collide(tmp_path):
    assert cached_get("a", 30, lambda: "A", cache_dir=tmp_path) == "A"
    assert cached_get("b", 30, lambda: "B", cache_dir=tmp_path) == "B"


def test_expired_entry_is_refetched(tmp_path):
    calls = []

    def fetch():
        calls.append(len(calls) + 1)
        return calls[-1]

    cached_get("k", ttl_days=30, fetch=fetch, cache_dir=tmp_path)
    # Backdate the cache file past its TTL.
    path = next(tmp_path.iterdir())
    payload = json.loads(path.read_text())
    payload["cached_at"] = time.time() - 31 * 86400
    path.write_text(json.dumps(payload))

    result = cached_get("k", ttl_days=30, fetch=fetch, cache_dir=tmp_path)
    assert result == 2 and len(calls) == 2


def test_corrupt_cache_file_is_treated_as_a_miss(tmp_path):
    cached_get("k", 30, lambda: "first", cache_dir=tmp_path)
    path = next(tmp_path.iterdir())
    path.write_text("{not json")

    assert cached_get("k", 30, lambda: "second", cache_dir=tmp_path) == "second"


def test_fetch_error_is_not_cached(tmp_path):
    attempts = []

    def flaky():
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("boom")
        return "ok"

    with pytest.raises(RuntimeError):
        cached_get("k", 30, flaky, cache_dir=tmp_path)
    assert cached_get("k", 30, flaky, cache_dir=tmp_path) == "ok"
    assert len(attempts) == 2


def test_unwritable_cache_dir_still_returns_the_fetched_value(tmp_path):
    blocked = tmp_path / "not_a_dir"
    blocked.write_text("i am a file, not a directory")
    assert cached_get("k", 30, lambda: "value", cache_dir=blocked / "sub") == "value"
