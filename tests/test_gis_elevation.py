"""Elevation client: grid construction, response parsing, error mapping, caching."""

import httpx
import pytest

from app.infrastructure.gis.elevation import (
    ELEVATION_ENDPOINT,
    FALLBACK_ENDPOINT,
    RETRIES,
    ElevationClient,
    grid_points,
)
from app.infrastructure.gis.errors import (
    CLIENT_QUOTA_MESSAGE,
    QUOTA_MESSAGE,
    GisUnavailableError,
)
from app.infrastructure.gis.outbound import OutboundBudget
from app.infrastructure.gis.projection import LocalOrigin, haversine_m

KYIV = LocalOrigin(lat=50.4501, lon=30.5234)
OTD_HOST = httpx.URL(ELEVATION_ENDPOINT).host
FALLBACK_HOST = httpx.URL(FALLBACK_ENDPOINT).host


def ok_response(n_points):
    results = [{"elevation": 100.0 + i} for i in range(n_points)]
    return httpx.Response(200, json={"status": "OK", "results": results})


def make_client(handler, **kwargs):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return ElevationClient(client, cache_dir=None, **kwargs)


# ── Grid construction ─────────────────────────────────────────────────────────

def test_grid_points_count_and_extent():
    pts = grid_points(KYIV, radius_m=400, n=5)
    assert len(pts) == 25
    # Corner points should sit ~radius_m*sqrt(2) from the origin (a square grid's diagonal).
    corner = pts[0]
    dist = haversine_m(KYIV.lat, KYIV.lon, *corner)
    assert dist == pytest.approx(400 * 2**0.5, rel=0.02)


def test_grid_points_includes_the_origin_for_odd_n():
    pts = grid_points(KYIV, radius_m=500, n=5)
    center = pts[len(pts) // 2]
    assert center == pytest.approx((KYIV.lat, KYIV.lon))


def test_grid_points_single_point_for_n_1():
    assert grid_points(KYIV, radius_m=500, n=1) == [(KYIV.lat, KYIV.lon)]


def test_grid_points_rejects_n_below_1():
    with pytest.raises(ValueError):
        grid_points(KYIV, radius_m=500, n=0)


# ── Client / HTTP ─────────────────────────────────────────────────────────────

def test_fetch_grid_requests_all_points_and_parses_elevations():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return ok_response(25)

    client = make_client(handler)
    grid = client.fetch_grid(KYIV.lat, KYIV.lon, radius_m=400, n=5)
    assert ELEVATION_ENDPOINT in seen["url"]
    assert grid.n == 5 and len(grid.points) == 25
    assert grid.elevations() == [100.0 + i for i in range(25)]


def test_fetch_grid_rejects_batches_over_the_api_limit():
    client = make_client(lambda r: ok_response(0))
    with pytest.raises(ValueError, match="100"):
        client.fetch_grid(KYIV.lat, KYIV.lon, n=11)  # 11*11 = 121 > 100


def test_missing_elevation_values_become_none():
    def handler(request):
        return httpx.Response(200, json={"status": "OK", "results": [{"elevation": None}] * 25})

    grid = make_client(handler).fetch_grid(KYIV.lat, KYIV.lon, n=5)
    assert all(p.elevation_m is None for p in grid.points)
    assert grid.elevations() == []


def test_api_error_status_raises_gis_unavailable():
    def handler(request):
        return httpx.Response(200, json={"status": "INVALID_REQUEST", "error": "bad locations"})

    with pytest.raises(GisUnavailableError, match="bad locations"):
        make_client(handler).fetch_grid(KYIV.lat, KYIV.lon, n=5)


def test_timeout_raises_gis_unavailable():
    def handler(request):
        raise httpx.TimeoutException("timed out", request=request)

    with pytest.raises(GisUnavailableError, match="timed out"):
        make_client(handler).fetch_grid(KYIV.lat, KYIV.lon, n=5)


def test_mismatched_result_count_raises_gis_unavailable():
    def handler(request):
        return ok_response(3)  # asked for 25

    with pytest.raises(GisUnavailableError, match="25"):
        make_client(handler).fetch_grid(KYIV.lat, KYIV.lon, n=5)


def test_default_self_constructed_client_sends_a_descriptive_user_agent():
    client = ElevationClient(cache_dir=None)
    try:
        ua = client._client.headers["user-agent"]
        assert "python-httpx" not in ua
        assert "TDSS" in ua
    finally:
        client.close()


# ── Retry ─────────────────────────────────────────────────────────────────────

def test_retries_a_transient_error_before_succeeding():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(504, text="gateway timeout")
        return ok_response(25)

    grid = make_client(handler).fetch_grid(KYIV.lat, KYIV.lon, n=5)
    assert len(calls) == 2
    assert grid.elevations() == [100.0 + i for i in range(25)]


def test_does_not_retry_a_non_transient_error():
    calls = []

    def handler(request):
        calls.append(request.url.host)
        return httpx.Response(400, text="bad request")

    with pytest.raises(GisUnavailableError):
        make_client(handler).fetch_grid(KYIV.lat, KYIV.lon, n=5)
    # Not retried on Open Topo Data; the fallback is asked once.
    assert calls == [OTD_HOST, FALLBACK_HOST]


def test_raises_after_retries_exhausted():
    calls = []

    def handler(request):
        calls.append(request.url.host)
        return httpx.Response(503, text="busy")

    with pytest.raises(GisUnavailableError, match="after 2 attempts"):
        make_client(handler).fetch_grid(KYIV.lat, KYIV.lon, n=5)
    assert calls == [OTD_HOST] * RETRIES + [FALLBACK_HOST]


def test_falls_back_to_open_meteo_when_open_topo_data_fails():
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.host == OTD_HOST:
            return httpx.Response(429, text="too many requests")
        return httpx.Response(200, json={"elevation": [200.0 + i for i in range(25)]})

    grid = make_client(handler).fetch_grid(KYIV.lat, KYIV.lon, n=5)
    assert grid.elevations() == [200.0 + i for i in range(25)]
    lats = seen[-1].url.params["latitude"].split(",")
    lons = seen[-1].url.params["longitude"].split(",")
    expected = grid_points(KYIV, 500.0, 5)
    assert [float(a) for a in lats] == pytest.approx([a for a, _ in expected], abs=1e-6)
    assert [float(b) for b in lons] == pytest.approx([b for _, b in expected], abs=1e-6)


def test_a_malformed_fallback_answer_is_a_failure():
    def handler(request):
        if request.url.host == OTD_HOST:
            return httpx.Response(503, text="busy")
        return httpx.Response(200, json={"error": True, "reason": "nope"})

    with pytest.raises(GisUnavailableError):
        make_client(handler).fetch_grid(KYIV.lat, KYIV.lon, n=5)


def test_a_spent_client_share_does_not_fall_back():
    calls = []

    def handler(request):
        calls.append(request.url.host)
        return ok_response(25)

    budget = OutboundBudget("Elevation API", max_concurrent=1, per_day=100, per_client_per_day=1)
    client = make_client(handler, budget=budget)
    client.fetch_grid(KYIV.lat, KYIV.lon, n=5, client="1.2.3.4")
    with pytest.raises(GisUnavailableError) as info:
        client.fetch_grid(KYIV.lat + 1, KYIV.lon, n=5, client="1.2.3.4")
    assert info.value.public_message == CLIENT_QUOTA_MESSAGE
    assert calls == [OTD_HOST]


def test_caching_avoids_a_second_request(tmp_path):
    calls = []

    def handler(request):
        calls.append(1)
        return ok_response(25)

    transport = httpx.MockTransport(handler)
    client = ElevationClient(httpx.Client(transport=transport), cache_dir=tmp_path)
    client.fetch_grid(KYIV.lat, KYIV.lon, radius_m=400, n=5)
    client.fetch_grid(KYIV.lat, KYIV.lon, radius_m=400, n=5)
    assert len(calls) == 1


def test_grid_is_built_around_the_requested_point_and_cached_exactly(tmp_path):
    calls = []

    def handler(request):
        calls.append(1)
        return ok_response(25)

    client = ElevationClient(httpx.Client(transport=httpx.MockTransport(handler)),
                             cache_dir=tmp_path)
    grid = client.fetch_grid(50.45012, 30.52041, radius_m=520, n=5)
    assert (grid.origin.lat, grid.origin.lon, grid.radius_m) == (50.45012, 30.52041, 520)
    assert client.fetch_grid(50.45012, 30.52041, radius_m=520, n=5) == grid
    assert len(calls) == 1
    client.fetch_grid(50.45013, 30.52041, radius_m=520, n=5)  # the grade depends on the point
    assert len(calls) == 2


def test_daily_budget_refuses_further_calls():
    calls = []

    def handler(request):
        calls.append(1)
        if request.url.host == FALLBACK_HOST:
            return httpx.Response(200, json={"elevation": [100.0] * 25})
        return ok_response(25)

    budget = OutboundBudget("Elevation API", max_concurrent=1, per_day=1)
    fallback_budget = OutboundBudget("Open-Meteo", max_concurrent=1, per_day=1)
    client = make_client(handler, budget=budget, fallback_budget=fallback_budget)
    client.fetch_grid(KYIV.lat, KYIV.lon, n=5)
    # Open Topo Data's budget is spent, so the second grid comes from the fallback ...
    client.fetch_grid(KYIV.lat + 1, KYIV.lon, n=5)
    # ... and once both are spent, the planner is told so.
    with pytest.raises(GisUnavailableError) as info:
        client.fetch_grid(KYIV.lat + 2, KYIV.lon, n=5)
    assert info.value.public_message == QUOTA_MESSAGE
    assert len(calls) == 2
