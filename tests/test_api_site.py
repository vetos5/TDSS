"""API tests for /api/site/analyse and /api/site/footprint -- fakes only, never the real network."""

import pytest
from fastapi.testclient import TestClient

from app.infrastructure.gis.elevation import ElevationGrid, ElevationPoint
from app.infrastructure.gis.errors import GisUnavailableError
from app.infrastructure.gis.overpass import OsmFeatures, OsmWay
from app.infrastructure.gis.projection import LocalOrigin, to_latlon
from backend.main import app
from backend.site_routes import get_elevation_client, get_overpass_client

KYIV = {"lat": 50.4501, "lon": 30.5234}
ORIGIN = LocalOrigin(**KYIV)


def crossing_features():
    motorway = OsmWay(
        1, {"highway": "motorway"}, [to_latlon(-300, 0, ORIGIN), to_latlon(300, 0, ORIGIN)]
    )
    primary = OsmWay(
        2, {"highway": "primary"}, [to_latlon(0, -300, ORIGIN), to_latlon(0, 300, ORIGIN)]
    )
    return OsmFeatures(
        roads=[motorway, primary], buildings=[], water=[], protected=[], residential=[]
    )


def flat_grid(n=5, radius_m=500.0):
    return ElevationGrid(ORIGIN, radius_m, n, [ElevationPoint(0, 0, 100.0) for _ in range(n * n)])


class FakeOverpass:
    def __init__(self, features=None, error=None):
        self._features = features if features is not None else crossing_features()
        self._error = error

    def fetch_features(self, lat, lon, radius_m=500.0):
        if self._error:
            raise self._error
        return self._features


class FakeElevation:
    def __init__(self, grid=None, error=None):
        self._grid = grid or flat_grid()
        self._error = error

    def fetch_grid(self, lat, lon, radius_m=500.0, n=5):
        if self._error:
            raise self._error
        return self._grid


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


def override(overpass=None, elevation=None):
    if overpass is not None:
        app.dependency_overrides[get_overpass_client] = lambda: overpass
    if elevation is not None:
        app.dependency_overrides[get_elevation_client] = lambda: elevation


# ── /api/site/analyse ─────────────────────────────────────────────────────────

@pytest.mark.skip(
    reason="crossing_features() fixture is motorway+primary (Service), assertion expects System "
    "-- fixture or assertion needs reconciling, skipped rather than reworked per user request"
)
def test_analyse_returns_inferred_parameters(client):
    override(FakeOverpass(), FakeElevation())
    r = client.post("/api/site/analyse", json={**KYIV, "radius_m": 500})
    assert r.status_code == 200
    data = r.json()
    assert data["context"] == "System (Highway + Highway)"
    assert data["context_confident"] is True
    assert data["terrain"] == "Flat"
    assert data["env_sensitivity"] == "Low"
    assert data["land_limit_ha"] > 0
    assert data["osm_features"]["type"] == "FeatureCollection"
    all_features = data["osm_features"]["features"]
    road_features = [f for f in all_features if f["properties"]["category"] == "road"]
    assert len(road_features) == 2
    assert road_features[0]["geometry"]["type"] == "LineString"


def test_analyse_geojson_uses_lon_lat_order(client):
    override(FakeOverpass(), FakeElevation())
    r = client.post("/api/site/analyse", json={**KYIV, "radius_m": 500})
    feature = r.json()["osm_features"]["features"][0]
    lon, lat = feature["geometry"]["coordinates"][0]
    # Kyiv: longitude ~30.5, latitude ~50.4 -- unambiguous which is which.
    assert 29 < lon < 32
    assert 49 < lat < 52


def test_analyse_building_polygon_is_closed_geometry(client):
    ring = [(-5, -5), (5, -5), (5, 5), (-5, 5), (-5, -5)]
    building = OsmWay(9, {"building": "yes"}, [to_latlon(x, y, ORIGIN) for x, y in ring])
    features = crossing_features()
    features.buildings.append(building)
    override(FakeOverpass(features), FakeElevation())
    r = client.post("/api/site/analyse", json={**KYIV, "radius_m": 500})
    all_features = r.json()["osm_features"]["features"]
    buildings = [f for f in all_features if f["properties"]["category"] == "building"]
    assert buildings[0]["geometry"]["type"] == "Polygon"


def test_analyse_overpass_unavailable_is_503(client):
    override(FakeOverpass(error=GisUnavailableError("Overpass API timed out")), FakeElevation())
    r = client.post("/api/site/analyse", json={**KYIV, "radius_m": 500})
    assert r.status_code == 503
    assert "timed out" in r.json()["detail"]


def test_analyse_elevation_unavailable_is_503(client):
    override(FakeOverpass(), FakeElevation(error=GisUnavailableError("Elevation API timed out")))
    r = client.post("/api/site/analyse", json={**KYIV, "radius_m": 500})
    assert r.status_code == 503


def test_analyse_sparse_data_reports_low_confidence(client):
    override(FakeOverpass(OsmFeatures([], [], [], [], [])), FakeElevation())
    r = client.post("/api/site/analyse", json={**KYIV, "radius_m": 500})
    data = r.json()
    assert data["context_confident"] is False
    assert len(data["notes"]) > 0


@pytest.mark.parametrize(
    "body",
    [{"lat": 91, "lon": 30}, {"lat": 50, "lon": 200}, {"lat": 50, "lon": 30, "radius_m": -1}],
)
def test_analyse_validates_input(client, body):
    assert client.post("/api/site/analyse", json=body).status_code == 422


# ── /api/site/footprint ────────────────────────────────────────────────────────

def test_footprint_available_alternative(client):
    override(FakeOverpass(), FakeElevation())
    r = client.post("/api/site/footprint", json={"alternative_name": "Cloverleaf", **KYIV})
    assert r.status_code == 200
    data = r.json()
    assert data["available"] is True
    assert len(data["segments"]) > 0
    assert all(len(pt) == 2 for pt in data["segments"][0]["coords"])
    assert data["right_of_way"]["buildings_affected"] == 0


@pytest.mark.parametrize("name", ["Stack (4-Level)", "Diamond", "Trumpet", "Directional T"])
def test_footprint_unavailable_alternative(client, name):
    override(FakeOverpass(), FakeElevation())
    r = client.post("/api/site/footprint", json={"alternative_name": name, **KYIV})
    assert r.status_code == 200
    data = r.json()
    assert data["available"] is False
    assert data["segments"] == []
    assert data["right_of_way"] is None
    assert "generator" in data["message"]


def test_footprint_unknown_alternative_name(client):
    override(FakeOverpass(), FakeElevation())
    r = client.post("/api/site/footprint", json={"alternative_name": "Nonsense", **KYIV})
    assert r.json()["available"] is False


def test_footprint_counts_overlapping_buildings(client):
    ring = [(-5, -5), (5, -5), (5, 5), (-5, 5), (-5, -5)]
    building = OsmWay(1, {"building": "yes"}, [to_latlon(x, y, ORIGIN) for x, y in ring])
    override(FakeOverpass(OsmFeatures([], [building], [], [], [])), FakeElevation())
    r = client.post("/api/site/footprint", json={"alternative_name": "Cloverleaf", **KYIV})
    row = r.json()["right_of_way"]
    assert row["buildings_affected"] == 1
    assert row["demolished_area_m2"] > 0
    assert row["estimated_cost_usd"] > 0


def test_footprint_custom_demolition_cost(client):
    ring = [(-5, -5), (5, -5), (5, 5), (-5, 5), (-5, -5)]
    building = OsmWay(1, {"building": "yes"}, [to_latlon(x, y, ORIGIN) for x, y in ring])
    override(FakeOverpass(OsmFeatures([], [building], [], [], [])), FakeElevation())
    r1 = client.post("/api/site/footprint", json={
        "alternative_name": "Cloverleaf", **KYIV, "demolition_cost_per_sqm": 100.0
    })
    r2 = client.post("/api/site/footprint", json={
        "alternative_name": "Cloverleaf", **KYIV, "demolition_cost_per_sqm": 200.0
    })
    assert r2.json()["right_of_way"]["estimated_cost_usd"] == pytest.approx(
        2 * r1.json()["right_of_way"]["estimated_cost_usd"]
    )


def test_footprint_uses_bearing_point_to_rotate(client):
    override(FakeOverpass(), FakeElevation())
    r0 = client.post("/api/site/footprint", json={"alternative_name": "Cloverleaf", **KYIV})
    r90 = client.post("/api/site/footprint", json={
        "alternative_name": "Cloverleaf", **KYIV,
        "bearing_lat": KYIV["lat"], "bearing_lon": KYIV["lon"] + 0.01,
    })
    assert r0.json()["segments"][0]["coords"] != r90.json()["segments"][0]["coords"]


def test_footprint_does_not_need_elevation_client(client, monkeypatch):
    # Footprint placement is pure geometry -- it should not depend on the elevation client at all.
    override(FakeOverpass())

    class ExplodingElevation:
        def fetch_grid(self, *a, **k):
            raise AssertionError("footprint should not call the elevation client")

    app.dependency_overrides[get_elevation_client] = lambda: ExplodingElevation()
    r = client.post("/api/site/footprint", json={"alternative_name": "Cloverleaf", **KYIV})
    assert r.status_code == 200


def test_footprint_overpass_unavailable_is_503(client):
    override(FakeOverpass(error=GisUnavailableError("busy")), FakeElevation())
    r = client.post("/api/site/footprint", json={"alternative_name": "Cloverleaf", **KYIV})
    assert r.status_code == 503


def test_footprint_unavailable_alternative_skips_network_entirely(client):
    # An unsupported alternative should return immediately, without calling Overpass at all.
    class ExplodingOverpass:
        def fetch_features(self, *a, **k):
            raise AssertionError("should not fetch OSM data for an unsupported alternative")

    app.dependency_overrides[get_overpass_client] = lambda: ExplodingOverpass()
    r = client.post("/api/site/footprint", json={"alternative_name": "Diamond", **KYIV})
    assert r.status_code == 200 and r.json()["available"] is False
