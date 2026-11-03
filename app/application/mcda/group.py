"""
Group decision: several stakeholders, each with their own criterion weights (DOCUMENTATION.md
§3.17).

Each stakeholder's weights rank the alternatives (one method, or the Borda consensus of several).
The group weights are the influence-weighted geometric mean of the stakeholders' weights,
renormalised: the aggregation of individual priorities (AIP) recommended for AHP group decisions
(Forman & Peniwati 1998), which keeps the weights' ratio scale. Each weight is floored at
``WEIGHT_FLOOR`` first, so one stakeholder's zero does not veto a criterion for everyone.
Agreement is Kendall's τ between each stakeholder's ranking and the group's.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

import numpy as np
from scipy.stats import kendalltau

from app.application.mcda import evaluate, rank_agreement
from app.application.mcda.matrix import DecisionMatrix

WEIGHT_FLOOR = 0.01


@dataclass
class Stakeholder:
    name: str
    influence: float
    weights: np.ndarray            # normalised, criterion order


@dataclass
class Ranking:
    ranks: np.ndarray              # 1 = best, per alternative (row order)
    utility: np.ndarray            # 0…1, 1 = best

    @property
    def winner(self) -> int:
        return int(np.argmin(self.ranks))


@dataclass
class StakeholderResult:
    stakeholder: Stakeholder
    ranking: Ranking
    kendall: float | None          # τ against the group ranking (None if undefined)


@dataclass
class GroupAnalysis:
    group_weights: np.ndarray
    group: Ranking
    stakeholders: list[StakeholderResult]
    winner_counts: dict[int, float]   # alternative → influence share of stakeholders it wins for


def aggregate_weights(weights: Sequence[np.ndarray], influence: Sequence[float]) -> np.ndarray:
    """Influence-weighted geometric mean of normalised weight vectors, renormalised."""
    w = np.maximum(np.asarray(weights, dtype=float), WEIGHT_FLOOR)
    lam = np.asarray(influence, dtype=float)
    lam = lam / lam.sum()
    g = np.exp((lam[:, None] * np.log(w)).sum(axis=0))
    return g / g.sum()


def rank_with(
    matrix: DecisionMatrix, weights: np.ndarray, methods: Sequence[str],
    run: Callable = evaluate,
) -> Ranking:
    """One method's ranking, or the Borda consensus of several."""
    results = run(matrix, weights, methods)
    if len(results) == 1:
        r = next(iter(results.values()))
        return Ranking(np.asarray(r.ranks), np.asarray(r.utility))
    a = rank_agreement(results)
    borda = a.consensus_scores
    span = borda.max() - borda.min()
    utility = np.ones_like(borda) if span == 0 else (borda - borda.min()) / span
    return Ranking(np.asarray(a.consensus_ranks), utility)


def _tau(a: np.ndarray, b: np.ndarray) -> float | None:
    if np.array_equal(a, b):
        return 1.0
    tau = kendalltau(a, b).statistic
    return None if np.isnan(tau) else float(tau)


def analyse_group(
    matrix: DecisionMatrix, stakeholders: Sequence[Stakeholder], methods: Sequence[str]
) -> GroupAnalysis:
    gw = aggregate_weights([s.weights for s in stakeholders], [s.influence for s in stakeholders])
    group = rank_with(matrix, gw, methods)
    total = sum(s.influence for s in stakeholders)
    results, counts = [], {}
    for s in stakeholders:
        r = rank_with(matrix, s.weights, methods)
        results.append(StakeholderResult(s, r, _tau(r.ranks, group.ranks)))
        counts[r.winner] = counts.get(r.winner, 0.0) + s.influence / total
    return GroupAnalysis(gw, group, results, counts)
