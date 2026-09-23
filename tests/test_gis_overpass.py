"""Overpass client: query shape, response parsing, error mapping, caching -- no real network."""

from urllib.parse import unquote

import httpx
import pytest

from app.infrastructure.gis.errors import GisUnavailableError
from app.infrastructure.gis.overpass import (
    OVERPASS_ENDPOINT,
    OverpassClient,
    build_query,
    parse_features,
)

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
    for tag in ["[highway]", "[building]", "[natural=water]", "[waterway]",
                "[leisure=nature_reserve]", "[boundary=protected_area]", "[landuse=residential]"]:
        assert tag in q
    assert "out geom;" in q


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
    assert "around:300" in seen["body"]
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
