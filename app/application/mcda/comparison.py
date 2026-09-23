"""
Agreement between the rankings produced by different MCDA methods.

Spearman's ρ and Kendall's τ-b are computed for every pair of methods. A Borda count over all
methods gives a consensus ranking: alternative i collects (m − rank_k(i)) points from method k.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.stats import kendalltau, spearmanr

from app.application.mcda.methods.base import MethodResult, rank_scores


@dataclass(frozen=True)
class RankAgreement:
    methods: list[str]
    spearman: np.ndarray        # k × k, NaN where undefined
    kendall: np.ndarray         # k × k, NaN where undefined
    winners: dict[str, list[int]]   # method → row indices ranked 1st (ties possible)
    consensus_scores: np.ndarray    # Borda points per alternative
    consensus_ranks: np.ndarray
    unanimous_winner: bool


def _correlation(a: np.ndarray, b: np.ndarray, fn) -> float:
    if np.array_equal(a, b):
        return 1.0
    if np.all(a == a[0]) or np.all(b == b[0]):
        return float("nan")
    return float(fn(a, b)[0])


def rank_agreement(results: dict[str, MethodResult]) -> RankAgreement:
    methods = list(results)
    k = len(methods)
    rho = np.eye(k)
    tau = np.eye(k)
    for i in range(k):
        for j in range(i + 1, k):
            a, b = results[methods[i]].ranks, results[methods[j]].ranks
            rho[i, j] = rho[j, i] = _correlation(a, b, spearmanr)
            tau[i, j] = tau[j, i] = _correlation(a, b, kendalltau)

    m = len(next(iter(results.values())).ranks) if results else 0
    borda = sum((m - r.ranks for r in results.values()), start=np.zeros(m))
    winners = {name: np.flatnonzero(r.ranks == 1).tolist() for name, r in results.items()}
    first_choices = {tuple(w) for w in winners.values()}
    return RankAgreement(
        methods=methods,
        spearman=rho,
        kendall=tau,
        winners=winners,
        consensus_scores=borda,
        consensus_ranks=rank_scores(borda),
        unanimous_winner=len(first_choices) == 1,
    )
