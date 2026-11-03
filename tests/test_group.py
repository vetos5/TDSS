"""Group decision with several stakeholders (app/application/mcda/group.py, /api/group)."""

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.application.mcda.group import WEIGHT_FLOOR, aggregate_weights
from backend.main import app

client = TestClient(app)
CTX = "System (Highway + Highway)"


def w(cost, land, q, safety):
    return {"construction_cost_mln": cost, "land_area_hectares": land,
            "throughput_vph": q, "safety_index": safety}


def body(stakeholders, methods=("wsm",)):
    return {"context": CTX, "weights": {}, "params": {}, "methods": list(methods),
            "stakeholders": stakeholders}


def test_aggregation_is_the_weighted_geometric_mean():
    a, b = np.array([0.4, 0.6]), np.array([0.1, 0.9])
    g = aggregate_weights([a, b], [1, 1])
    expected = np.sqrt(a * b) / np.sqrt(a * b).sum()
    assert g == pytest.approx(expected)
    assert aggregate_weights([a, b], [1, 0.000001]) == pytest.approx(a, abs=1e-4)


def test_a_zero_weight_does_not_veto():
    g = aggregate_weights([np.array([0.0, 1.0]), np.array([0.5, 0.5])], [1, 1])
    assert g[0] > WEIGHT_FLOOR / 2


def test_identical_stakeholders_agree_with_the_group():
    s = {"name": "A", "weights": w(0.3, 0.2, 0.25, 0.25)}
    data = client.post("/api/group", json=body([s, {**s, "name": "B"}])).json()
    assert all(x["kendall"] == 1.0 for x in data["stakeholders"])
    assert data["winner_share"] == {data["group_winner"]: pytest.approx(1.0)}
    solo = client.post("/api/evaluate", json={
        "context": CTX, "weights": w(0.3, 0.2, 0.25, 0.25), "params": {}}).json()
    assert data["group_ranking"][0] == solo["results"][0]["alternative_name"]


def test_group_with_several_methods_uses_the_consensus():
    data = client.post("/api/group", json=body([
        {"name": "Agency", "influence": 3, "weights": w(0.7, 0.1, 0.1, 0.1)},
        {"name": "Safety", "weights": w(0.05, 0.05, 0.1, 0.8)},
    ], methods=["wsm", "topsis", "vikor"])).json()
    assert data["basis"] == "consensus"
    assert sum(data["group_weights"].values()) == pytest.approx(1.0)
    assert data["group_weights"]["construction_cost_mln"] > data["group_weights"]["safety_index"]
    assert sum(data["winner_share"].values()) == pytest.approx(1.0)
    assert {s["name"] for s in data["stakeholders"]} == {"Agency", "Safety"}


def test_group_validation():
    one = [{"name": "A", "weights": w(1, 0, 0, 0)}]
    assert client.post("/api/group", json=body(one)).status_code == 422
    nine = [{"name": f"S{i}", "weights": w(1, 0, 0, 0)} for i in range(9)]
    assert client.post("/api/group", json=body(nine)).status_code == 422
    long = [{"name": "x" * 41, "weights": w(1, 0, 0, 0)}] * 2
    assert client.post("/api/group", json=body(long)).status_code == 422
