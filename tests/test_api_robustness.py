"""API tests for POST /api/robustness."""

import pytest
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)
ALL_METHODS = ["wsm", "topsis", "ahp", "promethee", "vikor"]


def body(context="System (Highway + Highway)", **extra):
    return {"context": context, "weights": {}, "params": {}, **extra}


def post(**kw):
    return client.post("/api/robustness", json=body(**kw))


def test_default_request_runs_all_methods():
    r = post(uncertainty={"iterations": 200})
    assert r.status_code == 200
    data = r.json()
    assert list(data["smaa"]) == ALL_METHODS == list(data["sensitivity"])
    assert data["iterations"] == 200 and data["weight_model"] == "perturbed"
    assert set(data["value_uncertainty"]) == {
        "construction_cost_mln", "land_area_hectares", "throughput_vph", "safety_index"
    }
    m = len(data["alternatives"])
    for method in data["smaa"].values():
        rows = method["alternatives"]
        assert len(rows) == m
        holistic = [a["holistic_acceptability"] for a in rows]
        assert holistic == sorted(holistic, reverse=True)
        for a in rows:
            assert len(a["rank_acceptability"]) == m
            assert sum(a["rank_acceptability"]) == pytest.approx(1.0)
    for alt, probs in data["exceedance"].items():
        assert alt in data["alternatives"]
        assert set(probs) == {"construction_cost_mln", "land_area_hectares"}


def test_fixed_certain_inputs_reproduce_evaluate_ranking():
    certain = {c: {"low": 1, "high": 1} for c in
               ["construction_cost_mln", "land_area_hectares", "throughput_vph", "safety_index"]}
    rob = post(methods=["topsis"], uncertainty={
        "iterations": 100, "weight_model": "fixed", "values": certain}).json()
    ev = client.post("/api/evaluate", json=body(methods=["topsis"])).json()
    winner = ev["method_results"]["topsis"]["scores"][0]["alternative_name"]
    top = rob["smaa"]["topsis"]["alternatives"][0]
    assert top["alternative_name"] == winner
    assert top["rank_acceptability"][0] == 1.0
    assert rob["sensitivity"]["topsis"]["winner"] == winner


def test_same_seed_is_reproducible():
    a = post(uncertainty={"iterations": 150, "seed": 3}).json()
    b = post(uncertainty={"iterations": 150, "seed": 3}).json()
    assert a["smaa"] == b["smaa"]


def test_sensitivity_payload_shape():
    data = post(methods=["wsm"], uncertainty={"iterations": 100}).json()
    s = data["sensitivity"]["wsm"]
    assert s["winner"] in data["alternatives"]
    assert len(s["criteria"]) == 4
    for c in s["criteria"]:
        assert len(c["grid"]) == 51
        assert set(c["utility"]) == set(data["alternatives"])
        if c["lower"] is not None:
            assert c["lower"] < c["weight"] and c["winner_below"] in data["alternatives"]
        if c["upper"] is not None:
            assert c["upper"] > c["weight"] and c["winner_above"] in data["alternatives"]
    if s["critical_criterion"] is not None:
        assert s["critical_change"] == pytest.approx(
            min(c["min_change"] for c in s["criteria"] if c["min_change"] is not None)
        )


def test_custom_range_overrides_default():
    data = post(methods=["wsm"], uncertainty={
        "iterations": 100,
        "values": {"construction_cost_mln": {"low": 0.5, "high": 2.0, "distribution": "uniform"}},
    }).json()
    vu = data["value_uncertainty"]
    assert vu["construction_cost_mln"] == {"low": 0.5, "high": 2.0, "distribution": "uniform"}
    assert vu["land_area_hectares"]["low"] == 0.9  # default kept


def test_budget_exceedance_reflects_budget():
    tight = post(methods=["wsm"], params={"budget": 85.0}, uncertainty={"iterations": 2000}).json()
    loose = post(methods=["wsm"], params={"budget": 500.0}, uncertainty={"iterations": 500}).json()
    # Stack costs 80 M USD; with the right-skewed cost range it often exceeds 85.
    assert tight["exceedance"]["Stack (4-Level)"]["construction_cost_mln"] > 0.3
    assert loose["exceedance"]["Stack (4-Level)"]["construction_cost_mln"] == 0.0


@pytest.mark.parametrize(
    "uncertainty",
    [
        {"iterations": 10},
        {"iterations": 50000},
        {"values": {"construction_cost_mln": {"low": 1.2, "high": 1.5}}},
        {"concentration": 0},
    ],
)
def test_invalid_uncertainty_is_422(uncertainty):
    assert post(uncertainty=uncertainty).status_code == 422


def test_unknown_criterion_is_400():
    r = post(uncertainty={"values": {"noise_db": {"low": 0.9, "high": 1.1}}})
    assert r.status_code == 400


def test_unknown_context_is_404():
    assert post(context="Nope").status_code == 404
