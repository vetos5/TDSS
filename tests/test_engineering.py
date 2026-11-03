"""Design-life traffic and safety analysis (app/application/engineering.py, /api/engineering)."""

import math

import pytest
from fastapi.testclient import TestClient

from app.application.engineering import (
    Study,
    analyse_alternative,
    heavy_vehicle_factor,
    lane_capacity,
)
from app.data.engineering_defaults import TRAFFIC_ELEMENTS
from app.data.interchange_data import INTERCHANGE_DATA
from backend.main import app

client = TestClient(app)


class P:
    design_speed = 100
    aadt = 45000
    peak_factor = 10
    num_lanes = 2
    terrain = "Flat"


def test_every_alternative_has_traffic_elements():
    names = {n for ctx in INTERCHANGE_DATA.values() for n in ctx}
    assert names == set(TRAFFIC_ELEMENTS)


def test_lane_capacity_follows_hcm_and_is_clamped():
    assert lane_capacity(50 * 1.609344) == pytest.approx(2200)
    assert lane_capacity(200) == 2400
    assert lane_capacity(20) == 1900


def test_heavy_vehicle_factor():
    assert heavy_vehicle_factor(10, "Flat") == pytest.approx(1.05)
    assert heavy_vehicle_factor(0, "Mountainous") == 1.0


def test_vc_grows_with_compound_growth():
    study = Study(growth_pct=3.0, design_years=10)
    a = analyse_alternative("Cloverleaf", P, study)
    assert len(a.vc_series) == 11
    assert a.vc_series[-1] == pytest.approx(a.vc_series[0] * 1.03**10, rel=1e-2)


def test_milestone_year_matches_the_growth_law():
    study = Study(growth_pct=4.0, design_years=40, opening_year=2030)
    a = analyse_alternative("Diamond", P, study)
    vc0 = a.vc_series[0]
    expected = 2030 + math.floor(math.log(1.0 / vc0) / math.log(1.04)) + 1
    assert a.year_capacity == expected
    assert a.vc_series[a.year_capacity - 2030] > 1.0 >= a.vc_series[a.year_capacity - 2031]


def test_no_growth_never_reaches_capacity_when_under_it():
    a = analyse_alternative("Stack (4-Level)", P, Study(growth_pct=0))
    assert a.year_capacity is None and a.year_los_e is None


def test_overloaded_from_opening():
    class Busy(P):
        aadt = 200000
    a = analyse_alternative("Diamond", Busy, Study())
    assert a.year_capacity == Study().opening_year


def test_critical_element_ignores_the_shared_mainline():
    class Busy(P):
        aadt = 150000
    a = analyse_alternative("Turbine", Busy, Study())
    assert a.critical_element != "merge"
    assert a.mainline_vc_series[0] > a.vc_series[0]


def test_crashes_scale_with_aadt_and_loop_speed_cmf():
    slow = analyse_alternative("Cloverleaf", P, Study(growth_pct=0))

    class Fast(P):
        design_speed = 120
    fast = analyse_alternative("Cloverleaf", Fast, Study(growth_pct=0))
    assert fast.cmf_speed == pytest.approx(1.2)
    assert fast.crashes[0] > slow.crashes[0]
    assert slow.fi_crashes[0] < slow.crashes[0]
    # Directional ramps have no loops: no speed CMF.
    assert analyse_alternative("Stack (4-Level)", Fast, Study()).cmf_speed == 1.0


def test_directional_designs_are_safer_than_loops():
    clover = analyse_alternative("Cloverleaf", P, Study())
    stack = analyse_alternative("Stack (4-Level)", P, Study())
    assert stack.crashes_total < clover.crashes_total


@pytest.mark.parametrize("lang", ["en", "uk"])
def test_api_engineering(lang):
    r = client.post("/api/engineering", params={"lang": lang},
                    json={"context": "Service (Highway + Urban)", "study": {"design_years": 15}})
    assert r.status_code == 200
    data = r.json()
    assert len(data["years"]) == 16
    names = [a["name"] for a in data["alternatives"]]
    assert names == list(INTERCHANGE_DATA["Service (Highway + Urban)"])
    for a in data["alternatives"]:
        assert len(a["vc_series"]) == len(a["crashes"]) == 16
        assert a["opening"] and all(e["label"] for e in a["opening"])
        assert any(e["shared"] for e in a["opening"])


def test_api_engineering_marks_infeasible():
    data = client.post("/api/engineering", json={
        "context": "System (Highway + Highway)", "params": {"budget": 20}}).json()
    feasible = {a["name"]: a["feasible"] for a in data["alternatives"]}
    assert feasible == {"Cloverleaf": True, "Turbine": False, "Stack (4-Level)": False}


def test_api_engineering_validates():
    assert client.post("/api/engineering", json={"context": "nope"}).status_code == 404
    r = client.post("/api/engineering", json={
        "context": "T-Type (3 Directions)", "study": {"design_years": 500}})
    assert r.status_code == 422
