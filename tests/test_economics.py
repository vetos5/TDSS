"""Life-cycle cost appraisal and break-even analysis (Phase 2 professional features)."""

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.application.economics import appraise
from app.application.engineering import AlternativeEngineering, Study
from app.application.mcda import METHODS, DecisionMatrix
from app.application.mcda.breakeven import analyse_breakeven
from app.application.mcda.matrix import Criterion
from backend.main import app

client = TestClient(app)


def eng(name, delay, crashes, years):
    return AlternativeEngineering(
        name=name, opening=[], design=[], critical_element="x",
        vc_series=[0.5] * years, mainline_vc_series=[0.5] * years,
        delay_vehh=[delay] * years, crashes=[crashes] * years,
        fi_crashes=[crashes * 0.3] * years, year_los_e=None, year_capacity=None, cmf_speed=1.0,
    )


def test_present_values_without_discounting():
    study = Study(design_years=9, discount_pct=0, maintenance_pct=1, value_of_time=10)
    a = appraise({"A": 10.0}, [eng("A", 100_000, 0, 10)], study).alternatives[0]
    assert a.pv_maintenance == pytest.approx(10 * 0.1)
    assert a.pv_delay == pytest.approx(10 * 1.0)          # 1e5 veh·h × $10 = $1 M a year
    assert a.pv_residual == pytest.approx(10 * (1 - 10 / 50))
    assert a.pv_total == pytest.approx(a.pv_agency + a.pv_user)
    assert a.cumulative_total[0] == 10.0
    assert a.cumulative_total[-1] == pytest.approx(a.pv_total)


def test_discounting_lowers_future_costs():
    e = [eng("A", 100_000, 5, 21)]
    flat = appraise({"A": 10.0}, e, Study(discount_pct=0)).alternatives[0]
    disc = appraise({"A": 10.0}, e, Study(discount_pct=6)).alternatives[0]
    assert disc.pv_user < flat.pv_user


def test_bcr_npv_and_payback_against_the_base():
    study = Study(design_years=19, discount_pct=0, maintenance_pct=0, value_of_time=10)
    res = appraise(
        {"cheap": 10.0, "better": 20.0},
        [eng("cheap", 200_000, 0, 20), eng("better", 100_000, 0, 20)],   # saves $1 M a year
        study,
    )
    cheap, better = res.alternatives
    assert res.base == "cheap" and cheap.is_base and cheap.bcr is None
    assert better.benefits == pytest.approx(20.0)
    assert better.incremental_cost == pytest.approx(10.0 - (20 - 10) * (1 - 20 / 50))
    assert better.npv == pytest.approx(better.benefits - better.incremental_cost)
    assert better.payback_year == study.opening_year - 1 + 10   # $10 M back at $1 M a year


def test_base_is_taken_among_feasible_alternatives():
    e = [eng("A", 1, 0, 21), eng("B", 1, 0, 21)]
    res = appraise({"A": 5.0, "B": 50.0}, e, Study(), feasible={"B"})
    assert res.base == "B"


def _matrix():
    crit = [Criterion("cost", "minimize", 0.5, "M"), Criterion("q", "maximize", 0.5, "x")]
    return DecisionMatrix(("A", "B", "C"), tuple(crit), np.array([[10., 5.], [20., 9.], [15., 6.]]))


@pytest.mark.parametrize("method", list(METHODS))
def test_breakeven_values_flip_the_winner(method):
    m = _matrix()
    w = np.array([0.5, 0.5])
    fn = METHODS[method]
    res = analyse_breakeven(m, w, fn)
    winner = res.winner
    for item in res.items:
        if item.value is None:
            continue
        i = m.alternatives.index(item.alternative)
        j = m.criterion_names.index(item.criterion)
        values = m.values.copy()
        # Just past the break-even value, the outcome has flipped.
        step = 1e-6 * max(1.0, abs(item.value))
        direction = np.sign(item.value - item.current)
        values[i, j] = item.value + direction * step
        ranks = fn(DecisionMatrix(m.alternatives, m.criteria, values), w).ranks
        if item.kind == "overtake":
            assert item.alternative != winner and ranks[i] == 1
        else:
            assert item.alternative == winner and ranks[i] != 1 or (ranks == 1).sum() > 1


def test_breakeven_respects_bounds():
    crit = [Criterion("safety_index", "maximize", 1.0, "/10")]
    m = DecisionMatrix(("A", "B"), tuple(crit), np.array([[9.0], [2.0]]))
    res = analyse_breakeven(m, np.array([1.0]), METHODS["wsm"], {"safety_index": (0, 10)})
    b = next(i for i in res.items if i.alternative == "B")
    assert b.value == pytest.approx(9.0, abs=1e-4)


def test_api_economics():
    data = client.post("/api/economics", json={
        "context": "Service (Highway + Urban)", "params": {"aadt": 80000}}).json()
    assert data["base"] == "Diamond"
    assert len(data["years"]) == 22
    ddi = next(a for a in data["alternatives"] if a["name"] == "DDI")
    assert ddi["bcr"] > 1 and ddi["npv"] > 0 and ddi["payback_year"]
    assert len(ddi["cumulative_total"]) == 22


def test_api_breakeven():
    r = client.post("/api/breakeven", json={
        "context": "System (Highway + Highway)", "weights": {}, "params": {},
        "methods": ["wsm", "topsis"]})
    assert r.status_code == 200
    data = r.json()
    assert set(data["methods"]) == {"wsm", "topsis"}
    items = data["methods"]["wsm"]["items"]
    assert len(items) == 3 * 4
    assert {i["kind"] for i in items} == {"overtake", "hold"}
