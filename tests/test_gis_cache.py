"""Disk cache: hits, misses, TTL expiry, tolerance of a broken cache, single-flight, pruning."""

import json
import os
import threading
import time

import pytest

from app.infrastructure.gis import cache
from app.infrastructure.gis.cache import cached_get, prune, snap_site


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


# ── Snapping ──────────────────────────────────────────────────────────────────

def test_snap_site_rounds_to_the_grid_and_the_radius_up_to_50_m():
    assert snap_site(50.45012, 30.52049, 520) == (50.45, 30.52, 550.0)
    assert snap_site(50.4501, 30.5234, 500.0) == (50.45, 30.523, 500.0)
    assert snap_site(0.0, 0.0, 1.0)[2] == 50.0


# ── Writes ────────────────────────────────────────────────────────────────────

def test_write_leaves_no_temp_files(tmp_path):
    cached_get("k", 30, lambda: {"v": 1}, cache_dir=tmp_path)
    assert [p.suffix for p in tmp_path.iterdir()] == [".json"]


def test_oversized_entry_is_returned_but_not_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "MAX_ENTRY_BYTES", 100)
    calls = []

    def fetch():
        calls.append(1)
        return "x" * 200

    assert cached_get("k", 30, fetch, cache_dir=tmp_path) == "x" * 200
    assert cached_get("k", 30, fetch, cache_dir=tmp_path) == "x" * 200
    assert len(calls) == 2 and list(tmp_path.iterdir()) == []


# ── Single-flight ─────────────────────────────────────────────────────────────

def _run_threads(n, target):
    threads = [threading.Thread(target=target) for _ in range(n)]
    for t in threads:
        t.start()
    return threads


def test_concurrent_misses_for_one_key_fetch_once(tmp_path):
    calls, results = [], []
    release = threading.Event()

    def fetch():
        calls.append(1)
        release.wait(5)
        return {"value": 42}

    threads = _run_threads(
        8, lambda: results.append(cached_get("k", 30, fetch, cache_dir=tmp_path))
    )
    time.sleep(0.05)
    release.set()
    for t in threads:
        t.join(5)
    assert len(calls) == 1
    assert results == [{"value": 42}] * 8


def test_waiters_fetch_themselves_when_the_leader_fails(tmp_path):
    calls, results = [], []
    release = threading.Event()

    def fetch():
        calls.append(1)
        if len(calls) == 1:
            release.wait(5)
            raise RuntimeError("upstream down")
        return "ok"

    def leader():
        with pytest.raises(RuntimeError):
            cached_get("k", 30, fetch, cache_dir=tmp_path)

    (lead,) = _run_threads(1, leader)
    while not cache._flights:
        time.sleep(0.001)
    (waiter,) = _run_threads(1, lambda: results.append(cached_get("k", 30, fetch,
                                                                  cache_dir=tmp_path)))
    time.sleep(0.05)
    release.set()
    lead.join(5)
    waiter.join(5)
    assert results == ["ok"] and len(calls) == 2
    assert cache._flights == {}


# ── Pruning ───────────────────────────────────────────────────────────────────

def _entry(cache_dir, name, size, age_s):
    path = cache_dir / name
    path.write_bytes(b"x" * size)
    stamp = time.time() - age_s
    os.utime(path, (stamp, stamp))
    return path


def test_prune_removes_expired_entries_and_stale_temp_files(tmp_path):
    expired = _entry(tmp_path, "old.json", 10, age_s=31 * 86400)
    fresh = _entry(tmp_path, "new.json", 10, age_s=60)
    stale_tmp = _entry(tmp_path, "dead.tmp", 10, age_s=2 * 3600)
    live_tmp = _entry(tmp_path, "writing.tmp", 10, age_s=1)
    prune(tmp_path, max_age_s=30 * 86400)
    assert not expired.exists() and not stale_tmp.exists()
    assert fresh.exists() and live_tmp.exists()


def test_prune_caps_total_size_oldest_first(tmp_path):
    oldest = _entry(tmp_path, "a.json", 100, age_s=300)
    middle = _entry(tmp_path, "b.json", 100, age_s=200)
    newest = _entry(tmp_path, "c.json", 100, age_s=100)
    prune(tmp_path, max_age_s=86400, max_bytes=250)
    assert not oldest.exists()
    assert middle.exists() and newest.exists()


def test_prune_runs_on_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "PRUNE_EVERY_N_WRITES", 1)
    expired = _entry(tmp_path, "old.json", 10, age_s=31 * 86400)
    cached_get("k", 30, lambda: "v", cache_dir=tmp_path)
    assert not expired.exists()
    assert cached_get("k", 30, lambda: "refetched", cache_dir=tmp_path) == "v"
