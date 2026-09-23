"""API tests for the multi-method evaluation endpoints."""

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)
ALL_METHODS = ["wsm", "topsis", "ahp", "promethee", "vikor"]
CRITERIA = ["construction_cost_mln", "land_area_hectares", "throughput_vph", "safety_index"]


def body(context="System (Highway + Highway)", **extra):
    return {"context": context, "weights": {}, "params": {}, **extra}


def consistent_ahp(w):
    w = np.asarray(w, dtype=float)
    return (w[:, None] / w[None, :]).tolist()


def test_contexts():
    r = client.get("/api/contexts")
    assert r.status_code == 200 and len(r.json()["contexts"]) == 3


@pytest.mark.parametrize("lang", ["en", "uk"])
def test_methods_lists_every_method(lang):
    r = client.get("/api/methods", params={"lang": lang})
    assert [m["id"] for m in r.json()] == ALL_METHODS
    assert all(m["label"] and m["description"] for m in r.json())


def test_default_request_returns_wsm_only():
    data = client.post("/api/evaluate", json=body()).json()
    assert list(data["method_results"]) == ["wsm"]
    assert data["rank_agreement"] is None
    assert data["weighting"]["mode"] == "manual"
    wsm = data["method_results"]["wsm"]["scores"]
    assert [s["alternative_name"] for s in wsm] == [r["alternative_name"] for r in data["results"]]


@pytest.mark.parametrize(
    "context",
    ["System (Highway + Highway)", "Service (Highway + Urban)", "T-Type (3 Directions)"],
)
def test_all_methods(context):
    data = client.post("/api/evaluate", json=body(context, methods=ALL_METHODS)).json()
    assert list(data["method_results"]) == ALL_METHODS
    for m in data["method_results"].values():
        ranks = [s["rank"] for s in m["scores"]]
        assert ranks == sorted(ranks) and ranks[0] == 1
        assert max(s["utility"] for s in m["scores"]) == pytest.approx(1.0)
    agreement = data["rank_agreement"]
    assert agreement["methods"] == ALL_METHODS
    assert len(agreement["spearman"]) == 5 and agreement["spearman"][0][0] == 1.0
    assert agreement["consensus"][0]["rank"] == 1
    vikor = data["method_results"]["vikor"]
    assert vikor["higher_is_better"] is False
    assert set(vikor["details"]["S"]) == {s["alternative_name"] for s in vikor["scores"]}
    assert set(data["method_results"]["topsis"]["details"]["ideal"]) == set(CRITERIA)


def test_duplicate_methods_are_collapsed():
    data = client.post("/api/evaluate", json=body(methods=["topsis", "topsis", "wsm"])).json()
    assert list(data["method_results"]) == ["topsis", "wsm"]


def test_unknown_method_is_rejected():
    assert client.post("/api/evaluate", json=body(methods=["electre"])).status_code == 422


@pytest.mark.parametrize("mode", ["entropy", "critic"])
def test_objective_weighting(mode):
    data = client.post("/api/evaluate", json=body(weighting={"mode": mode})).json()
    w = data["normalised_weights"]
    assert sum(w.values()) == pytest.approx(1.0)
    assert w != {"construction_cost_mln": 0.3, "land_area_hectares": 0.2,
                 "throughput_vph": 0.25, "safety_index": 0.25}
    assert data["weighting"]["mode"] == mode
    detail_key = "entropy" if mode == "entropy" else "information"
    assert set(data["weighting"]["details"][detail_key]) == set(CRITERIA)


def test_ahp_weighting_recovers_consistent_weights():
    target = [0.1, 0.2, 0.3, 0.4]
    data = client.post(
        "/api/evaluate",
        json=body(weighting={"mode": "ahp", "ahp_matrix": consistent_ahp(target)}),
    ).json()
    assert list(data["normalised_weights"].values()) == pytest.approx(target)
    assert data["weighting"]["details"]["consistency_ratio"] == pytest.approx(0, abs=1e-9)
    assert not any(n["kind"] == "weighting" for n in data["adjustments"])


def test_inconsistent_ahp_adds_warning_note():
    a = np.ones((4, 4))
    a[0, 1], a[1, 0] = 9, 1 / 9
    a[1, 2], a[2, 1] = 9, 1 / 9
    a[2, 0], a[0, 2] = 9, 1 / 9
    data = client.post(
        "/api/evaluate", json=body(weighting={"mode": "ahp", "ahp_matrix": a.tolist()})
    ).json()
    assert any(n["kind"] == "weighting" and "CR" in n["message"] for n in data["adjustments"])


@pytest.mark.parametrize(
    "weighting",
    [
        {"mode": "ahp"},
        {"mode": "ahp", "ahp_matrix": [[1, 2], [0.5, 1]]},
        {"mode": "ahp", "ahp_matrix": (np.ones((4, 4)) * 2).tolist()},
    ],
)
def test_bad_ahp_input_is_400(weighting):
    assert client.post("/api/evaluate", json=body(weighting=weighting)).status_code == 400


def test_combined_weighting_is_convex_mix():
    manual = {"construction_cost_mln": 1, "land_area_hectares": 0,
              "throughput_vph": 0, "safety_index": 0}
    entropy = client.post("/api/evaluate", json=body(weighting={"mode": "entropy"})).json()
    combined = client.post(
        "/api/evaluate",
        json={**body(weighting={"mode": "combined", "alpha": 0.25}), "weights": manual},
    ).json()
    for i, c in enumerate(CRITERIA):
        expected = 0.25 * (i == 0) + 0.75 * entropy["normalised_weights"][c]
        assert combined["normalised_weights"][c] == pytest.approx(expected)


def test_objective_weighting_with_single_feasible_alternative_falls_back():
    # Only Diamond (10 M USD, 5 ha) fits this budget in the Service context.
    params = {"budget": 12.0, "land_limit": 30.0, "env_sensitivity": "Low"}
    data = client.post(
        "/api/evaluate",
        json={**body("Service (Highway + Urban)", weighting={"mode": "entropy"}), "params": params},
    ).json()
    assert len(data["results"]) == 1
    assert data["weighting"]["mode"] == "manual"
    assert any(n["kind"] == "weighting" for n in data["adjustments"])


def test_all_infeasible_is_422():
    params = {"budget": 1.0}
    r = client.post("/api/evaluate", json={**body(methods=ALL_METHODS), "params": params})
    assert r.status_code == 422
