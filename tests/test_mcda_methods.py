"""Ranking methods: hand-computed examples and properties every method must satisfy."""

import numpy as np
import pytest

from app.application.dss_engine import Criterion
from app.application.mcda import METHODS, DecisionMatrix, evaluate, rank_agreement
from app.application.mcda.methods import ahp, promethee, rank_scores, topsis, vikor, wsm
from app.application.mcda.methods.promethee import PreferenceFunction
from app.application.mcda.normalisation import sum_


def make(values, directions, names=None):
    values = np.asarray(values, dtype=float)
    names = names or tuple("ABCDEFGHIJ"[: values.shape[0]])
    crit = tuple(Criterion(f"c{j}", d) for j, d in enumerate(directions))
    return DecisionMatrix(tuple(names), crit, values)


def random_matrix(seed, m=5, n=4):
    rng = np.random.default_rng(seed)
    values = rng.uniform(1, 100, size=(m, n))
    directions = rng.choice(["maximize", "minimize"], size=n)
    weights = rng.dirichlet(np.ones(n))
    return make(values, directions), weights


# ── Ranking helper ────────────────────────────────────────────────────────────

def test_rank_scores_competition_ranking():
    np.testing.assert_array_equal(rank_scores(np.array([0.2, 0.9, 0.9, 0.1])), [3, 1, 1, 4])
    np.testing.assert_array_equal(rank_scores(np.array([0.2, 0.9]), False), [1, 2])


# ── Hand-computed examples ────────────────────────────────────────────────────

def test_wsm_hand_example():
    m = make([[10, 1], [20, 3], [40, 2]], ["minimize", "maximize"])
    r = wsm.run(m, np.array([0.5, 0.5]))
    # cost: (1, 2/3, 0); benefit: (0, 1, 0.5)
    np.testing.assert_allclose(r.scores, [0.5, 5 / 6, 0.25])
    np.testing.assert_array_equal(r.ranks, [2, 1, 3])


def test_topsis_single_criterion_extremes():
    r = topsis.run(make([[1], [2], [3]], ["maximize"]), np.array([1.0]))
    np.testing.assert_allclose(r.scores, [0, 0.5, 1])


def test_topsis_hand_example():
    m = make([[3, 4], [4, 3]], ["maximize", "minimize"])
    r = topsis.run(m, np.array([0.5, 0.5]))
    # vector norm = 5 in both columns → v = [[.3, .4], [.4, .3]]; A+ = (.4, .3), A- = (.3, .4)
    np.testing.assert_allclose(r.details["ideal"], [0.4, 0.3])
    np.testing.assert_allclose(r.scores, [0, 1])


def test_ahp_ratio_matrix_eigenvector_equals_sum_normalisation():
    col = np.array([15.0, 45.0, 80.0])
    for benefit in (True, False):
        a = ahp.ratio_matrix(col, benefit)
        vals, vecs = np.linalg.eig(a)
        v = np.abs(vecs[:, np.argmax(vals.real)].real)
        expected = sum_(col[:, None], np.array([benefit]))[:, 0]
        np.testing.assert_allclose(v / v.sum(), expected)


def test_ahp_scores_are_weighted_local_priorities():
    m = make([[1, 4], [3, 2]], ["maximize", "minimize"])
    r = ahp.run(m, np.array([0.6, 0.4]))
    # benefit: (.25, .75); cost: (1/4, 1/2)/(3/4) = (1/3, 2/3)
    np.testing.assert_allclose(r.scores, [0.6 * 0.25 + 0.4 / 3, 0.6 * 0.75 + 0.4 * 2 / 3])


def test_promethee_usual_single_criterion():
    m = make([[1], [2], [3]], ["maximize"])
    r = promethee.run(m, np.array([1.0]), {"c0": PreferenceFunction("usual")})
    np.testing.assert_allclose(r.scores, [-1, 0, 1])


def test_promethee_linear_preference_function():
    fn = PreferenceFunction("linear", q=1, p=3)
    np.testing.assert_allclose(fn(np.array([-1, 0, 1, 2, 3, 5]), 99), [0, 0, 0, 0.5, 1, 1])


def test_promethee_net_flows_sum_to_zero():
    m, w = random_matrix(7)
    assert promethee.run(m, w).scores.sum() == pytest.approx(0.0, abs=1e-12)


def test_vikor_hand_example():
    # Two benefit criteria, equal weights.
    m = make([[1, 3], [2, 2], [3, 1]], ["maximize", "maximize"])
    r = vikor.run(m, np.array([0.5, 0.5]))
    np.testing.assert_allclose(r.details["S"], [0.5, 0.5, 0.5])
    np.testing.assert_allclose(r.details["R"], [0.5, 0.25, 0.5])
    np.testing.assert_allclose(r.scores, [0.5, 0.0, 0.5])
    assert r.ranks[1] == 1
    assert not r.higher_is_better


def test_vikor_compromise_set_when_advantage_is_small():
    m = make([[10, 10], [9.9, 10], [1, 1]], ["maximize", "maximize"])
    r = vikor.run(m, np.array([0.5, 0.5]))
    assert not r.details["acceptable_advantage"]
    assert r.details["compromise_set"] == ["A", "B"]


# ── Properties for every method ───────────────────────────────────────────────

@pytest.mark.parametrize("method", sorted(METHODS))
@pytest.mark.parametrize("seed", range(30))
def test_dominating_alternative_ranks_first(method, seed):
    m, w = random_matrix(seed)
    values = m.values.copy()
    best = np.where(m.benefit, values.max(axis=0) * 1.1, values.min(axis=0) * 0.9)
    values[seed % len(values)] = best
    dominated = make(values, [c.direction for c in m.criteria])
    r = METHODS[method](dominated, w)
    assert r.ranks[seed % len(values)] == 1


@pytest.mark.parametrize("method", sorted(METHODS))
@pytest.mark.parametrize("seed", range(10))
def test_ranking_invariant_to_units(method, seed):
    """Rescaling a criterion (e.g. M USD → USD) must not change any ranking."""
    m, w = random_matrix(seed)
    scaled = make(m.values * np.array([1e6, 0.001, 3.7, 1.0]), [c.direction for c in m.criteria])
    np.testing.assert_array_equal(METHODS[method](m, w).ranks, METHODS[method](scaled, w).ranks)


@pytest.mark.parametrize("method", sorted(METHODS))
def test_identical_alternatives_tie(method):
    m = make([[5, 5], [5, 5], [1, 9]], ["maximize", "minimize"])
    r = METHODS[method](m, np.array([0.5, 0.5]))
    assert r.ranks[0] == r.ranks[1]


@pytest.mark.parametrize("method", sorted(METHODS))
def test_utility_is_unit_interval_with_best_at_one(method):
    m, w = random_matrix(3)
    r = METHODS[method](m, w)
    u = r.utility
    assert u.min() == pytest.approx(0) and u.max() == pytest.approx(1)
    assert u[r.ranks == 1].max() == pytest.approx(1)


# ── Registry and agreement ────────────────────────────────────────────────────

def test_evaluate_rejects_unknown_method():
    m, w = random_matrix(0)
    with pytest.raises(ValueError, match="unknown MCDA method"):
        evaluate(m, w, ["electre"])


def test_evaluate_passes_options():
    m, w = random_matrix(0)
    r = evaluate(m, w, ["vikor"], {"vikor": {"v": 1.0}})
    assert r["vikor"].details["v"] == 1.0


def test_rank_agreement_identical_and_reversed():
    m = make([[1], [2], [3]], ["maximize"])
    results = evaluate(m, np.array([1.0]), ["wsm", "topsis"])
    agree = rank_agreement(results)
    np.testing.assert_allclose(agree.spearman, 1.0)
    assert agree.unanimous_winner
    np.testing.assert_array_equal(agree.consensus_ranks, [3, 2, 1])

    flipped = make([[1], [2], [3]], ["minimize"])
    results["reversed"] = wsm.run(flipped, np.array([1.0]))
    agree = rank_agreement(results)
    assert agree.spearman[0, 2] == pytest.approx(-1.0)
    assert agree.kendall[0, 2] == pytest.approx(-1.0)
    assert not agree.unanimous_winner
