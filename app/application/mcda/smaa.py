"""
SMAA-2 — Stochastic Multicriteria Acceptability Analysis.

Criterion values and weights are treated as random variables. For each Monte Carlo draw k the
decision matrix X_k and weight vector w_k are sampled and the chosen MCDA method ranks the
alternatives. From N draws:

    b_i^r = P(rank(i) = r)                         rank acceptability index
    a_i^h = Σ_r α_r b_i^r,  α_r = (m − r)/(m − 1)  holistic acceptability (linear meta-weights)
    w_i^c = E[w | rank(i) = 1]                     central weight vector
    p_i^c = P(rank(i) = 1 | w = w_i^c)             confidence factor

All methods in one call share the same draws (common random numbers), so differences between
methods are not sampling noise.

Lahdelma, R., Salminen, P. (2001). SMAA-2: Stochastic multicriteria acceptability analysis for
    group decision making. Operations Research, 49(3), 444–454.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal, Mapping

import numpy as np

from app.application.mcda.matrix import DecisionMatrix
from app.application.mcda.methods.base import MethodResult

Method = Callable[[DecisionMatrix, np.ndarray], MethodResult]
Distribution = Literal["triangular", "uniform"]
WeightModel = Literal["fixed", "perturbed", "uniform"]

# Keeps Dirichlet parameters positive when a weight is exactly zero.
_DIRICHLET_FLOOR = 1e-3


@dataclass(frozen=True)
class ValueUncertainty:
    """
    Multiplicative uncertainty of one criterion: the true value lies in [low·x, high·x].

    ``triangular`` has its mode at x (the expert estimate); ``uniform`` is flat on the interval.
    ``low = high = 1`` means the value is certain.
    """

    low: float = 1.0
    high: float = 1.0
    distribution: Distribution = "triangular"

    def __post_init__(self) -> None:
        if not 0 < self.low <= 1.0 <= self.high:
            raise ValueError(f"need 0 < low ≤ 1 ≤ high, got low={self.low}, high={self.high}")

    @property
    def is_certain(self) -> bool:
        return self.low == self.high == 1.0


@dataclass(frozen=True)
class WeightUncertainty:
    """
    ``fixed``     — the given weights, no uncertainty.
    ``perturbed`` — Dirichlet(κ·w): mean w, spread shrinking as the concentration κ grows.
    ``uniform``   — uniform on the weight simplex (no preference information at all).
    """

    model: WeightModel = "perturbed"
    concentration: float = 100.0

    def __post_init__(self) -> None:
        if self.concentration <= 0:
            raise ValueError("concentration must be positive")


@dataclass
class SMAAResult:
    method: str
    alternatives: tuple[str, ...]
    iterations: int
    rank_acceptability: np.ndarray                 # m × m, row i = alternative, column r = rank r+1
    holistic_acceptability: np.ndarray             # m
    central_weights: list[np.ndarray | None]       # per alternative; None if never ranked first
    confidence: np.ndarray                          # m, NaN if never ranked first
    first_rank_share: np.ndarray = field(init=False)

    def __post_init__(self) -> None:
        self.first_rank_share = self.rank_acceptability[:, 0]


@dataclass
class SMAAAnalysis:
    iterations: int
    seed: int
    results: dict[str, SMAAResult]
    # P(sampled value exceeds its limit) per alternative, keyed by criterion name.
    exceedance: dict[str, np.ndarray]


def sample_values(
    matrix: DecisionMatrix,
    uncertainty: Mapping[str, ValueUncertainty],
    n: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Draw n decision matrices, shape (n, m, c)."""
    base = matrix.values
    out = np.broadcast_to(base, (n, *base.shape)).copy()
    for j, criterion in enumerate(matrix.criteria):
        u = uncertainty.get(criterion.name)
        if u is None or u.is_certain:
            continue
        x = base[:, j]
        lo, hi = u.low * x, u.high * x
        size = (n, len(x))
        if u.distribution == "uniform":
            out[:, :, j] = rng.uniform(lo, hi, size=size)
        else:
            out[:, :, j] = rng.triangular(lo, x, hi, size=size)
    return out


def sample_weights(
    weights: np.ndarray, model: WeightUncertainty, n: int, rng: np.random.Generator
) -> np.ndarray:
    """Draw n weight vectors, shape (n, c); every row sums to 1."""
    c = len(weights)
    if model.model == "fixed":
        return np.broadcast_to(weights, (n, c)).copy()
    if model.model == "uniform":
        return rng.dirichlet(np.ones(c), size=n)
    return rng.dirichlet(np.maximum(model.concentration * weights, _DIRICHLET_FLOOR), size=n)


def _with_values(matrix: DecisionMatrix, values: np.ndarray) -> DecisionMatrix:
    return DecisionMatrix(matrix.alternatives, matrix.criteria, values)


def run_smaa(
    matrix: DecisionMatrix,
    weights: np.ndarray,
    methods: Mapping[str, Method],
    *,
    values: Mapping[str, ValueUncertainty] | None = None,
    weight_model: WeightUncertainty | None = None,
    iterations: int = 1000,
    seed: int = 42,
    limits: Mapping[str, float] | None = None,
) -> SMAAAnalysis:
    """
    Run SMAA-2 for every method in *methods* on shared draws.

    *limits* maps a criterion name to an upper bound (e.g. budget for cost); the result reports
    how often each alternative's sampled value exceeds it.
    """
    if iterations < 1:
        raise ValueError("iterations must be at least 1")
    weight_model = weight_model or WeightUncertainty()
    rng = np.random.default_rng(seed)
    m, c = matrix.shape
    xs = sample_values(matrix, values or {}, iterations, rng)
    ws = sample_weights(weights, weight_model, iterations, rng)
    matrices = [_with_values(matrix, x) for x in xs]

    results: dict[str, SMAAResult] = {}
    for name, method in methods.items():
        ranks = np.empty((iterations, m), dtype=int)
        for k in range(iterations):
            ranks[k] = method(matrices[k], ws[k]).ranks

        acceptability = np.stack([(ranks == r).mean(axis=0) for r in range(1, m + 1)], axis=1)
        meta = np.linspace(1.0, 0.0, m) if m > 1 else np.ones(1)
        holistic = acceptability @ meta

        central: list[np.ndarray | None] = []
        confidence = np.full(m, np.nan)
        for i in range(m):
            first = ranks[:, i] == 1
            if not first.any():
                central.append(None)
                continue
            wc = ws[first].mean(axis=0)
            central.append(wc)
            confidence[i] = np.mean([method(mk, wc).ranks[i] == 1 for mk in matrices])

        results[name] = SMAAResult(
            method=name,
            alternatives=matrix.alternatives,
            iterations=iterations,
            rank_acceptability=acceptability,
            holistic_acceptability=holistic,
            central_weights=central,
            confidence=confidence,
        )

    exceedance = {}
    for crit, limit in (limits or {}).items():
        j = matrix.criterion_names.index(crit)
        exceedance[crit] = (xs[:, :, j] > limit).mean(axis=0)

    return SMAAAnalysis(iterations=iterations, seed=seed, results=results, exceedance=exceedance)
