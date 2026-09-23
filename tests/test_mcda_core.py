"""Decision matrix, normalisation and weighting."""

import numpy as np
import pytest

from app.application.dss_engine import Alternative, Criterion
from app.application.mcda import DecisionMatrix, weighting
from app.application.mcda.normalisation import NEUTRAL, max_, minmax, sum_, vector

BENEFIT = np.array([True, False])
X = np.array([[1.0, 10.0], [3.0, 20.0], [2.0, 40.0]])


def _criteria(*directions):
    return [Criterion(f"c{i}", d) for i, d in enumerate(directions)]


# ── DecisionMatrix ────────────────────────────────────────────────────────────

def test_matrix_from_alternatives_orders_columns_and_defaults_missing_to_zero():
    crit = _criteria("maximize", "minimize")
    alts = [Alternative("A", {"c1": 5, "c0": 1}), Alternative("B", {"c0": 2})]
    m = DecisionMatrix.from_alternatives(alts, crit)
    assert m.alternatives == ("A", "B")
    np.testing.assert_array_equal(m.values, [[1, 5], [2, 0]])
    np.testing.assert_array_equal(m.benefit, [True, False])


@pytest.mark.parametrize("values", [np.ones((2, 3)), np.array([[1.0, np.nan], [1, 1]])])
def test_matrix_rejects_bad_values(values):
    with pytest.raises(ValueError):
        DecisionMatrix(("A", "B"), tuple(_criteria("maximize", "minimize")), values)


def test_weights_vector_aligns_and_normalises():
    m = DecisionMatrix(("A", "B"), tuple(_criteria("maximize", "minimize")), np.ones((2, 2)))
    np.testing.assert_allclose(m.weights_vector({"c1": 3, "c0": 1}), [0.25, 0.75])
    for bad in ({"c0": 1}, [1, -1], [0, 0], [1, 2, 3]):
        with pytest.raises(ValueError):
            m.weights_vector(bad)


# ── Normalisation ─────────────────────────────────────────────────────────────

def test_minmax_is_direction_aware_and_neutral_on_constant_column():
    out = minmax(X, BENEFIT)
    np.testing.assert_allclose(out[:, 0], [0, 1, 0.5])
    np.testing.assert_allclose(out[:, 1], [1, 2 / 3, 0])
    const = minmax(np.array([[5.0], [5.0]]), np.array([True]))
    np.testing.assert_allclose(const, NEUTRAL)


def test_vector_columns_have_unit_norm():
    np.testing.assert_allclose(np.linalg.norm(vector(X), axis=0), 1.0)


def test_sum_columns_sum_to_one_and_reward_low_cost():
    out = sum_(X, BENEFIT)
    np.testing.assert_allclose(out.sum(axis=0), 1.0)
    assert out[0, 1] > out[1, 1] > out[2, 1]


def test_max_maps_best_to_one():
    out = max_(X, BENEFIT)
    assert out[1, 0] == 1.0 and out[0, 1] == 1.0


@pytest.mark.parametrize("fn", [sum_, max_])
def test_ratio_normalisations_reject_non_positive(fn):
    with pytest.raises(ValueError):
        fn(np.array([[0.0], [1.0]]), np.array([True]))


# ── Entropy ───────────────────────────────────────────────────────────────────

def test_entropy_hand_example():
    # Column A = [1, 3]: p = (.25, .75), e = 0.811278; column B constant: e = 1 → weight 0.
    res = weighting.entropy(np.array([[1.0, 2.0], [3.0, 2.0]]))
    assert res.entropy[0] == pytest.approx(0.811278, abs=1e-6)
    assert res.entropy[1] == pytest.approx(1.0)
    np.testing.assert_allclose(res.weights, [1.0, 0.0])


def test_entropy_all_constant_gives_equal_weights():
    np.testing.assert_allclose(weighting.entropy(np.full((3, 4), 7.0)).weights, 0.25)


# ── CRITIC ────────────────────────────────────────────────────────────────────

def test_critic_matches_direct_formula():
    rng = np.random.default_rng(1)
    values = rng.uniform(1, 10, size=(6, 4))
    benefit = np.array([True, False, True, False])
    res = weighting.critic(values, benefit)
    z = minmax(values, benefit)
    sigma = z.std(axis=0, ddof=1)
    r = np.corrcoef(z, rowvar=False)
    c = sigma * (1 - r).sum(axis=0)
    np.testing.assert_allclose(res.weights, c / c.sum())


def test_critic_penalises_redundant_criteria():
    # c0 and c1 are identical (redundant), c2 is independent and equally spread.
    values = np.array([[1.0, 1.0, 2.0], [2.0, 2.0, 1.0], [3.0, 3.0, 3.0], [4.0, 4.0, 4.0]])
    w = weighting.critic(values, np.array([True, True, True])).weights
    assert w[2] > w[0] == pytest.approx(w[1])


# ── AHP ───────────────────────────────────────────────────────────────────────

def _consistent(w):
    w = np.asarray(w, dtype=float)
    return w[:, None] / w[None, :]


def test_ahp_recovers_weights_from_consistent_matrix():
    res = weighting.ahp(_consistent([0.4, 0.3, 0.2, 0.1]))
    np.testing.assert_allclose(res.weights, [0.4, 0.3, 0.2, 0.1], atol=1e-10)
    assert res.lambda_max == pytest.approx(4.0)
    assert res.consistency_ratio == pytest.approx(0.0, abs=1e-10)
    assert res.is_consistent


def test_ahp_matches_power_iteration_on_inconsistent_matrix():
    a = np.array([[1, 3, 5, 9], [1 / 3, 1, 2, 4], [1 / 5, 1 / 2, 1, 3], [1 / 9, 1 / 4, 1 / 3, 1]])
    res = weighting.ahp(a)
    v = np.ones(4)
    for _ in range(200):
        v = a @ v
        v /= v.sum()
    np.testing.assert_allclose(res.weights, v, atol=1e-9)
    ci = (res.lambda_max - 4) / 3
    assert res.consistency_ratio == pytest.approx(ci / 0.90)


def test_ahp_flags_inconsistent_judgements():
    # a > b (9), b > c (9) but c > a (9): strongly intransitive.
    a = np.array([[1, 9, 1 / 9], [1 / 9, 1, 9], [9, 1 / 9, 1]])
    assert not weighting.ahp(a).is_consistent


@pytest.mark.parametrize(
    "bad",
    [np.ones((2, 3)), [[1, 2], [2, 1]], [[1, -2], [-0.5, 1]], [[2, 1], [1, 2]]],
)
def test_ahp_validates_matrix(bad):
    with pytest.raises(ValueError):
        weighting.ahp(np.asarray(bad, dtype=float))


def test_combine():
    s, o = np.array([1.0, 0.0]), np.array([0.0, 1.0])
    np.testing.assert_allclose(weighting.combine(s, o, 1.0), [1, 0])
    np.testing.assert_allclose(weighting.combine(s, o, 0.25), [0.25, 0.75])
    with pytest.raises(ValueError):
        weighting.combine(s, o, 1.5)
