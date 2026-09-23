"""SMAA-2 and weight sensitivity analysis."""

import numpy as np
import pytest

from app.application.dss_engine import Criterion
from app.application.mcda import METHODS, DecisionMatrix
from app.application.mcda.methods import wsm
from app.application.mcda.sensitivity import analyse_sensitivity, reweight
from app.application.mcda.smaa import (
    ValueUncertainty,
    WeightUncertainty,
    run_smaa,
    sample_values,
    sample_weights,
)


def make(values, directions):
    values = np.asarray(values, dtype=float)
    crit = tuple(Criterion(f"c{j}", d) for j, d in enumerate(directions))
    return DecisionMatrix(tuple("ABCDEF"[: values.shape[0]]), crit, values)


def random_problem(seed, m=4, n=3):
    rng = np.random.default_rng(seed)
    return (
        make(rng.uniform(1, 10, size=(m, n)), rng.choice(["maximize", "minimize"], size=n)),
        rng.dirichlet(np.ones(n)),
    )


SPREAD = {f"c{j}": ValueUncertainty(0.8, 1.25) for j in range(4)}


# ── Sampling ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("dist", ["triangular", "uniform"])
def test_value_samples_stay_in_bounds(dist):
    m, _ = random_problem(0)
    u = {"c0": ValueUncertainty(0.5, 2.0, dist)}
    xs = sample_values(m, u, 5000, np.random.default_rng(1))
    assert xs.shape == (5000, 4, 3)
    assert np.all(xs[:, :, 0] >= 0.5 * m.values[:, 0] - 1e-12)
    assert np.all(xs[:, :, 0] <= 2.0 * m.values[:, 0] + 1e-12)
    np.testing.assert_array_equal(xs[:, :, 1], np.broadcast_to(m.values[:, 1], (5000, 4)))


def test_triangular_mode_is_the_estimate():
    m = make([[10.0]], ["maximize"])
    xs = sample_values(m, {"c0": ValueUncertainty(0.5, 1.5)}, 40000, np.random.default_rng(2))
    assert xs.mean() == pytest.approx(10.0, rel=0.01)  # symmetric triangle: mean = mode


@pytest.mark.parametrize("bad", [(0.0, 1.0), (1.1, 1.2), (0.9, 0.95)])
def test_value_uncertainty_validates_bounds(bad):
    with pytest.raises(ValueError):
        ValueUncertainty(*bad)


def test_weight_samples():
    w = np.array([0.5, 0.3, 0.2])
    rng = np.random.default_rng(3)
    fixed = sample_weights(w, WeightUncertainty("fixed"), 10, rng)
    np.testing.assert_array_equal(fixed, np.broadcast_to(w, (10, 3)))
    uniform = sample_weights(w, WeightUncertainty("uniform"), 20000, rng)
    np.testing.assert_allclose(uniform.sum(axis=1), 1.0)
    np.testing.assert_allclose(uniform.mean(axis=0), 1 / 3, atol=0.01)
    tight = sample_weights(w, WeightUncertainty("perturbed", 1000), 20000, rng)
    loose = sample_weights(w, WeightUncertainty("perturbed", 10), 20000, rng)
    np.testing.assert_allclose(tight.mean(axis=0), w, atol=0.01)
    assert tight.std(axis=0).max() < loose.std(axis=0).min()


def test_perturbed_weights_tolerate_zero_weight():
    s = sample_weights(np.array([1.0, 0.0]), WeightUncertainty("perturbed", 50), 100,
                       np.random.default_rng(4))
    assert np.all(np.isfinite(s)) and np.allclose(s.sum(axis=1), 1.0)


# ── SMAA ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("method", sorted(METHODS))
def test_without_uncertainty_acceptability_is_deterministic_ranking(method):
    m, w = random_problem(5)
    res = run_smaa(m, w, {method: METHODS[method]}, weight_model=WeightUncertainty("fixed"),
                   iterations=20).results[method]
    ranks = METHODS[method](m, w).ranks
    expected = np.zeros((4, 4))
    expected[np.arange(4), ranks - 1] = 1.0
    np.testing.assert_array_equal(res.rank_acceptability, expected)
    winner = int(np.argmin(ranks))
    np.testing.assert_allclose(res.central_weights[winner], w)
    assert res.confidence[winner] == 1.0


@pytest.mark.parametrize("method", sorted(METHODS))
def test_acceptability_rows_and_columns_sum_to_one(method):
    m, w = random_problem(6)
    res = run_smaa(m, w, {method: METHODS[method]}, values=SPREAD,
                   weight_model=WeightUncertainty("uniform"), iterations=300).results[method]
    np.testing.assert_allclose(res.rank_acceptability.sum(axis=1), 1.0)
    np.testing.assert_allclose(res.rank_acceptability.sum(axis=0), 1.0)
    assert np.all((0 <= res.holistic_acceptability) & (res.holistic_acceptability <= 1))


@pytest.mark.parametrize("method", sorted(METHODS))
def test_strongly_dominating_alternative_always_first(method):
    values = [[100, 1], [5, 50], [4, 60], [6, 40]]
    m = make(values, ["maximize", "minimize"])
    res = run_smaa(m, np.array([0.5, 0.5]), {method: METHODS[method]},
                   values={"c0": ValueUncertainty(0.9, 1.1), "c1": ValueUncertainty(0.9, 1.1)},
                   weight_model=WeightUncertainty("uniform"), iterations=300).results[method]
    assert res.rank_acceptability[0, 0] == 1.0
    assert res.central_weights[1] is None and np.isnan(res.confidence[1])


def test_same_seed_same_result_and_shared_draws():
    m, w = random_problem(7)
    a = run_smaa(m, w, METHODS, values=SPREAD, iterations=200, seed=9)
    b = run_smaa(m, w, {"wsm": METHODS["wsm"]}, values=SPREAD, iterations=200, seed=9)
    np.testing.assert_array_equal(a.results["wsm"].rank_acceptability,
                                  b.results["wsm"].rank_acceptability)
    c = run_smaa(m, w, {"wsm": METHODS["wsm"]}, values=SPREAD, iterations=200, seed=10)
    assert not np.array_equal(a.results["wsm"].rank_acceptability,
                              c.results["wsm"].rank_acceptability)


def test_central_weights_favour_the_alternative():
    # A is best on c0, B on c1: A wins when c0 matters more.
    m = make([[10, 1], [1, 10]], ["maximize", "maximize"])
    res = run_smaa(m, np.array([0.5, 0.5]), {"wsm": wsm.run},
                   weight_model=WeightUncertainty("uniform"), iterations=4000).results["wsm"]
    assert res.central_weights[0][0] > 0.6 and res.central_weights[1][1] > 0.6
    np.testing.assert_allclose(res.rank_acceptability[:, 0], [0.5, 0.5], atol=0.03)


def test_exceedance_probability():
    m = make([[80.0], [10.0]], ["minimize"])
    # A ~ uniform(64, 120): P(> 100) = 20 / 56.
    res = run_smaa(m, np.array([1.0]), {"wsm": wsm.run},
                   values={"c0": ValueUncertainty(0.8, 1.5, "uniform")},
                   iterations=20000, limits={"c0": 100.0})
    np.testing.assert_allclose(res.exceedance["c0"], [20 / 56, 0.0], atol=0.01)


def test_invalid_iterations():
    m, w = random_problem(0)
    with pytest.raises(ValueError):
        run_smaa(m, w, METHODS, iterations=0)


# ── Sensitivity ───────────────────────────────────────────────────────────────

def test_reweight_keeps_proportions():
    w = np.array([0.5, 0.3, 0.2])
    out = reweight(w, 0, 0.8)
    np.testing.assert_allclose(out, [0.8, 0.12, 0.08])
    np.testing.assert_allclose(reweight(np.array([1.0, 0.0, 0.0]), 0, 0.4), [0.4, 0.3, 0.3])


def test_wsm_threshold_analytic():
    # Normalised A = (1, 0), B = (0, 1): WSM scores are w0 and w1 → reversal at w0 = 0.5.
    m = make([[10, 1], [1, 10]], ["maximize", "maximize"])
    res = analyse_sensitivity(m, np.array([0.7, 0.3]), wsm.run, "wsm")
    c0, c1 = res.criteria
    assert res.winner == 0
    assert c0.lower == pytest.approx(0.5, abs=1e-3) and c0.upper is None
    assert c0.winner_below == 1
    assert c1.upper == pytest.approx(0.5, abs=1e-3) and c1.lower is None
    assert res.critical.min_change == pytest.approx(0.2, abs=1e-3)


def test_no_reversal_when_one_alternative_dominates():
    m = make([[10, 10], [1, 1]], ["maximize", "maximize"])
    res = analyse_sensitivity(m, np.array([0.5, 0.5]), wsm.run, "wsm")
    assert all(c.lower is None and c.upper is None for c in res.criteria)
    assert res.critical is None
    assert all(c.width == 1.0 for c in res.criteria)


@pytest.mark.parametrize("method", sorted(METHODS))
@pytest.mark.parametrize("seed", range(5))
def test_thresholds_are_real_reversals(method, seed):
    m, w = random_problem(seed)
    fn = METHODS[method]
    res = analyse_sensitivity(m, w, fn, method)
    for j, c in enumerate(res.criteria):
        assert c.utility.shape == (len(c.grid), 4)
        for edge, sign, new in ((c.lower, -1, c.winner_below), (c.upper, 1, c.winner_above)):
            if edge is None:
                continue
            assert (edge - c.weight) * sign > 0
            inside = fn(m, reweight(w, j, edge - sign * 2e-3)).ranks
            outside = fn(m, reweight(w, j, min(max(edge + sign * 2e-3, 0), 1))).ranks
            assert inside[res.winner] == 1
            assert outside[res.winner] != 1 and outside[new] == 1
