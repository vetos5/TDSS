"""Overpass client: query shape, response parsing, error mapping, caching -- no real network."""

import re
import threading
import time
from urllib.parse import unquote

import httpx
import pytest

from app.data.site_analysis_defaults import MIN_MAJOR_ROAD_RANK, ROAD_CLASS_RANK
from app.infrastructure.gis import overpass
from app.infrastructure.gis.errors import (
    QUERY_FAILED_MESSAGE,
    QUOTA_MESSAGE,
    TOO_MUCH_DATA_MESSAGE,
    GisUnavailableError,
)
from app.infrastructure.gis.outbound import OutboundBudget
from app.infrastructure.gis.overpass import (
    OVERPASS_ENDPOINT,
    OVERPASS_MIRROR_ENDPOINTS,
    RETRIES_PER_ENDPOINT,
    OverpassClient,
    build_query,
    parse_features,
)
from app.infrastructure.gis.projection import LocalOrigin, to_latlon

KYIV = {"lat": 50.4501, "lon": 30.5234}


def _element(way_id, tags, n_pts=2):
    return {
        "type": "way", "id": way_id, "tags": tags,
        "geometry": [{"lat": 50.45 + i * 0.001, "lon": 30.52 + i * 0.001} for i in range(n_pts)],
    }


SAMPLE_RAW = {
    "elements": [
        _element(1, {"highway": "motorway"}),
        _element(2, {"highway": "primary", "lanes": "2"}),
        _element(3, {"building": "yes"}),
        _element(4, {"natural": "water"}),
        _element(5, {"waterway": "river"}),
        _element(6, {"leisure": "nature_reserve"}),
        _element(7, {"boundary": "protected_area"}),
        _element(8, {"landuse": "residential"}),
        {"type": "node", "id": 9, "tags": {"highway": "traffic_signals"}},  # not a way -> ignored
        {"type": "way", "id": 10, "tags": {"highway": "unclassified"}},     # no geometry -> ignored
    ]
}


def make_client(handler, **kwargs):
    transport = httpx.MockTransport(handler)
    return OverpassClient(httpx.Client(transport=transport), cache_dir=None, **kwargs)


# ── Query construction ───────────────────────────────────────────────────────

def test_query_contains_point_radius_and_all_feature_filters():
    q = build_query(50.45, 30.52, 400.0)
    assert "around:400.0,50.45,30.52" in q
    for tag in ["[building]", "[natural=water]", "[waterway]",
                "[leisure=nature_reserve]", "[boundary=protected_area]", "[landuse=residential]"]:
        assert tag in q
    assert "out geom;" in q


def test_query_asks_only_for_the_road_classes_the_analysis_ranks():
    q = build_query(50.45, 30.52, 400.0)
    classes = set(re.search(r'\[highway~"\^\((.*?)\)\$"\]', q).group(1).split("|"))
    ranked = {cls for cls, rank in ROAD_CLASS_RANK.items() if rank >= MIN_MAJOR_ROAD_RANK}
    assert classes == ranked
    assert "service" not in classes and "footway" not in classes


# ── Parsing ───────────────────────────────────────────────────────────────────

def test_parse_features_classifies_every_bucket():
    f = parse_features(SAMPLE_RAW)
    assert [w.id for w in f.roads] == [1, 2]
    assert [w.id for w in f.buildings] == [3]
    assert [w.id for w in f.water] == [4, 5]
    assert [w.id for w in f.protected] == [6, 7]
    assert [w.id for w in f.residential] == [8]


def test_parse_features_preserves_tags_and_coords():
    f = parse_features(SAMPLE_RAW)
    road = f.roads[1]
    assert road.tags == {"highway": "primary", "lanes": "2"}
    assert road.coords[0] == (50.45, 30.52)


def test_parse_features_ignores_non_way_and_geometryless_elements():
    f = parse_features(SAMPLE_RAW)
    buckets = (f.roads, f.buildings, f.water, f.protected, f.residential)
    all_ids = {w.id for bucket in buckets for w in bucket}
    assert 9 not in all_ids and 10 not in all_ids


def test_parse_features_empty_response():
    f = parse_features({"elements": []})
    assert f.roads == f.buildings == f.water == f.protected == f.residential == []


# ── Client / HTTP ─────────────────────────────────────────────────────────────

def test_fetch_features_posts_query_and_parses_response():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = unquote(request.read().decode())
        return httpx.Response(200, json=SAMPLE_RAW)

    client = make_client(handler)
    features = client.fetch_features(**KYIV, radius_m=300)
    assert seen["url"] == OVERPASS_ENDPOINT
    # Around the snapped point, widened by the margin (see QUERY_MARGIN_M).
    assert "around:400.0,50.45,30.523" in seen["body"]
    assert len(features.roads) == 2


def test_timeout_raises_gis_unavailable():
    def handler(request):
        raise httpx.TimeoutException("timed out", request=request)

    client = make_client(handler)
    with pytest.raises(GisUnavailableError, match="timed out"):
        client.fetch_features(**KYIV)


def test_server_error_raises_gis_unavailable():
    def handler(request):
        return httpx.Response(503, text="server busy")

    client = make_client(handler)
    with pytest.raises(GisUnavailableError):
        client.fetch_features(**KYIV)


def test_malformed_json_raises_gis_unavailable():
    def handler(request):
        return httpx.Response(200, text="<html>not json</html>")

    client = make_client(handler)
    with pytest.raises(GisUnavailableError):
        client.fetch_features(**KYIV)


def test_default_self_constructed_client_sends_a_descriptive_user_agent():
    # Confirmed live: Overpass rejects httpx's default "python-httpx/x.y" User-Agent with 406.
    # Only OverpassClient's own default-constructed httpx.Client needs this (an injected client,
    # as in every other test here, is the caller's responsibility).
    client = OverpassClient(cache_dir=None)
    try:
        ua = client._client.headers["user-agent"]
        assert "python-httpx" not in ua
        assert "TDSS" in ua
    finally:
        client.close()


# ── Retry and mirror fallback ─────────────────────────────────────────────────

def test_retries_a_transient_error_before_succeeding():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(504, text="gateway timeout")
        return httpx.Response(200, json=SAMPLE_RAW)

    client = make_client(handler)
    features = client.fetch_features(**KYIV)
    assert len(calls) == 2
    assert len(features.roads) == 2


def test_does_not_retry_a_non_transient_error():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(400, text="bad query")

    client = make_client(handler)
    with pytest.raises(GisUnavailableError):
        client.fetch_features(**KYIV)
    assert len(calls) == 1  # no retry, no mirror fallback -- a 400 will fail the same way again


def test_falls_back_to_the_mirror_after_primary_endpoint_exhausts_retries():
    seen_urls = []

    def handler(request):
        seen_urls.append(str(request.url))
        if request.url.host == "overpass-api.de":
            return httpx.Response(504, text="gateway timeout")
        return httpx.Response(200, json=SAMPLE_RAW)

    client = make_client(handler)
    features = client.fetch_features(**KYIV)
    assert len(features.roads) == 2
    # RETRIES_PER_ENDPOINT attempts against the primary, then the mirror succeeds.
    assert sum("overpass-api.de" in u for u in seen_urls) == RETRIES_PER_ENDPOINT
    assert any("kumi.systems" in u for u in seen_urls)


def test_raises_after_all_endpoints_and_retries_are_exhausted():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503, text="busy")

    client = make_client(handler)
    with pytest.raises(GisUnavailableError, match="unavailable after retrying"):
        client.fetch_features(**KYIV)
    assert len(calls) == len(OVERPASS_MIRROR_ENDPOINTS) * RETRIES_PER_ENDPOINT


def test_timeout_is_retried_then_can_still_succeed():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) < 2:
            raise httpx.TimeoutException("timed out", request=request)
        return httpx.Response(200, json=SAMPLE_RAW)

    client = make_client(handler)
    features = client.fetch_features(**KYIV)
    assert len(features.roads) == 2
    assert len(calls) == 2


def test_caching_avoids_a_second_request(tmp_path):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json=SAMPLE_RAW)

    client = OverpassClient(
        httpx.Client(transport=httpx.MockTransport(handler)), cache_dir=tmp_path
    )
    client.fetch_features(**KYIV, radius_m=500)
    client.fetch_features(**KYIV, radius_m=500)
    assert len(calls) == 1


def test_different_points_are_not_cache_collisions(tmp_path):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json=SAMPLE_RAW)

    client = OverpassClient(
        httpx.Client(transport=httpx.MockTransport(handler)), cache_dir=tmp_path
    )
    client.fetch_features(lat=50.45, lon=30.52)
    client.fetch_features(lat=49.0, lon=25.0)
    assert len(calls) == 2


def test_nearby_points_and_radii_share_one_snapped_request(tmp_path):
    bodies = []

    def handler(request):
        bodies.append(unquote(request.read().decode()))
        return httpx.Response(200, json=SAMPLE_RAW)

    client = OverpassClient(
        httpx.Client(transport=httpx.MockTransport(handler)), cache_dir=tmp_path
    )
    client.fetch_features(lat=50.45012, lon=30.52041, radius_m=520)
    client.fetch_features(lat=50.44996, lon=30.51963, radius_m=550)
    assert len(bodies) == 1
    # The query is built from the snapped values (plus the margin), so it matches its cache key.
    assert "around:650.0,50.45,30.52" in bodies[0]


# ── Outbound limits ───────────────────────────────────────────────────────────

def test_a_read_timeout_is_not_retried():
    calls = []

    def handler(request):
        calls.append(1)
        raise httpx.ReadTimeout("read timed out", request=request)

    with pytest.raises(GisUnavailableError):
        make_client(handler).fetch_features(**KYIV)
    assert len(calls) == 1  # a query heavy enough to time out would only time out again


def test_no_request_once_the_deadline_has_passed():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json=SAMPLE_RAW)

    with pytest.raises(GisUnavailableError, match="deadline"):
        make_client(handler).fetch_features(**KYIV, deadline=time.monotonic() - 1)
    assert calls == []


def test_retries_stop_at_the_deadline():
    calls = []

    def handler(request):
        calls.append(1)
        time.sleep(0.06)  # the attempt outlives the deadline below
        return httpx.Response(504, text="gateway timeout")

    with pytest.raises(GisUnavailableError, match="deadline"):
        make_client(handler).fetch_features(**KYIV, deadline=time.monotonic() + 0.05)
    assert len(calls) == 1  # not len(OVERPASS_MIRROR_ENDPOINTS) * RETRIES_PER_ENDPOINT


def test_oversized_response_is_refused_and_not_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(overpass, "MAX_RESPONSE_BYTES", 200)
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json=SAMPLE_RAW)  # well over 200 bytes

    client = OverpassClient(
        httpx.Client(transport=httpx.MockTransport(handler)), cache_dir=tmp_path
    )
    with pytest.raises(GisUnavailableError) as info:
        client.fetch_features(**KYIV)
    assert info.value.public_message == TOO_MUCH_DATA_MESSAGE
    assert len(calls) == 1  # not retried: the same cell is just as big on the mirror
    assert list(tmp_path.iterdir()) == []


def test_runtime_error_remark_is_a_failure_and_never_cached(tmp_path):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json={
            "elements": [],
            "remark": 'runtime error: Query timed out in "query" at line 3 after 16 seconds.',
        })

    client = OverpassClient(
        httpx.Client(transport=httpx.MockTransport(handler)), cache_dir=tmp_path
    )
    for _ in range(2):
        with pytest.raises(GisUnavailableError) as info:
            client.fetch_features(**KYIV)
        assert info.value.public_message == QUERY_FAILED_MESSAGE
    assert len(calls) == 2  # the second call asked again: nothing was cached
    assert list(tmp_path.iterdir()) == []


def test_an_informational_remark_is_not_an_error():
    def handler(request):
        return httpx.Response(200, json={**SAMPLE_RAW, "remark": "data may be stale"})

    assert len(make_client(handler).fetch_features(**KYIV).roads) == 2


def test_daily_budget_refuses_further_calls():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json=SAMPLE_RAW)

    budget = OutboundBudget("Overpass", max_concurrent=2, per_day=1)
    client = make_client(handler, budget=budget)
    client.fetch_features(lat=50.45, lon=30.52)
    with pytest.raises(GisUnavailableError) as info:
        client.fetch_features(lat=49.0, lon=25.0)
    assert info.value.public_message == QUOTA_MESSAGE
    assert len(calls) == 1


def test_concurrent_identical_requests_make_one_call(tmp_path):
    calls = []
    release = threading.Event()

    def handler(request):
        calls.append(1)
        release.wait(5)
        return httpx.Response(200, json=SAMPLE_RAW)

    client = OverpassClient(
        httpx.Client(transport=httpx.MockTransport(handler)), cache_dir=tmp_path
    )
    results = []
    threads = [
        threading.Thread(target=lambda: results.append(client.fetch_features(**KYIV)))
        for _ in range(10)
    ]
    for t in threads:
        t.start()
    time.sleep(0.05)
    release.set()
    for t in threads:
        t.join(5)
    assert len(calls) == 1
    assert len(results) == 10 and all(len(r.roads) == 2 for r in results)


def test_cached_ways_keep_only_the_tags_the_analysis_reads(tmp_path):
    def handler(request):
        return httpx.Response(200, json=SAMPLE_RAW)

    client = OverpassClient(
        httpx.Client(transport=httpx.MockTransport(handler)), cache_dir=tmp_path
    )
    fresh = client.fetch_features(**KYIV)
    cached = client.fetch_features(**KYIV)
    assert fresh == cached
    assert cached.roads[1].tags == {"highway": "primary"}  # "lanes" dropped
    assert cached.buildings[0].tags == {}
    assert "lanes" not in next(tmp_path.iterdir()).read_text()


def test_off_grid_point_gets_exactly_the_ways_an_exact_around_query_would():
    # A click 40 m north and 30 m east of its grid point: the query goes to the grid point, but
    # the ways kept must be those within 500 m of the click itself, by node or by segment.
    click = LocalOrigin(lat=50.45036, lon=30.52042)

    def way(way_id, tags, *local_pts):
        coords = [to_latlon(x, y, click) for x, y in local_pts]
        return {"type": "way", "id": way_id, "tags": tags,
                "geometry": [{"lat": la, "lon": lo} for la, lo in coords]}

    road = {"highway": "primary"}
    elements = [
        way(1, road, (499, 0), (520, 0)),            # a node just inside
        way(2, road, (501, 0), (520, 0)),            # nearest node just outside
        way(3, road, (-100, 499), (100, 499)),       # only the segment comes inside
        way(4, road, (-100, 501), (100, 501)),       # the segment stays just outside
        way(5, {"building": "yes"}, (0, -540), (5, -540), (5, -545), (0, -540)),
        # 5 is inside the snapped query circle (around the grid point) but not the click's.
    ]

    def handler(request):
        return httpx.Response(200, json={"elements": elements})

    features = make_client(handler).fetch_features(click.lat, click.lon, radius_m=500)
    assert [w.id for w in features.roads] == [1, 3]
    assert features.buildings == []
