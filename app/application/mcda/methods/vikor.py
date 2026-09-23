"""
VIKOR — VIšekriterijumsko KOmpromisno Rangiranje (multi-criteria compromise ranking).

    f*_j = best value, f⁻_j = worst value of criterion j
    S_i = Σ_j w_j (f*_j − f_ij) / (f*_j − f⁻_j)          group utility (regret-sum)
    R_i = max_j w_j (f*_j − f_ij) / (f*_j − f⁻_j)        individual regret
    Q_i = v (S_i − S*) / (S⁻ − S*) + (1 − v)(R_i − R*) / (R⁻ − R*)

Lower Q is better. The leader a₁ is a stable compromise when
    C1 (acceptable advantage): Q(a₂) − Q(a₁) ≥ 1 / (m − 1), and
    C2 (acceptable stability): a₁ is also best by S or by R.
Otherwise a compromise set is proposed.

Opricovic, S., Tzeng, G.-H. (2004). Compromise solution by MCDM methods. EJOR 156(2).
"""

from __future__ import annotations

import numpy as np

from app.application.mcda.matrix import DecisionMatrix
from app.application.mcda.methods.base import MethodResult, rank_scores


def _scaled(x: np.ndarray) -> np.ndarray:
    span = x.max() - x.min()
    return np.zeros_like(x) if span == 0 else (x - x.min()) / span


def run(matrix: DecisionMatrix, weights: np.ndarray, v: float = 0.5) -> MethodResult:
    if not 0.0 <= v <= 1.0:
        raise ValueError("VIKOR v must lie in [0, 1]")
    values, benefit = matrix.values, matrix.benefit
    m = values.shape[0]

    best = np.where(benefit, values.max(axis=0), values.min(axis=0))
    worst = np.where(benefit, values.min(axis=0), values.max(axis=0))
    span = best - worst
    gap = np.where(span == 0, 0.0, (best - values) / np.where(span == 0, 1.0, span))
    regret = weights * gap
    s = regret.sum(axis=1)
    r = regret.max(axis=1)
    q = v * _scaled(s) + (1.0 - v) * _scaled(r)

    order = np.lexsort((np.arange(m), q))  # by Q, ties by input order
    compromise = [int(order[0])]
    advantage = stability = True
    if m > 1:
        dq = 1.0 / (m - 1)
        a1, a2 = order[0], order[1]
        advantage = bool(q[a2] - q[a1] >= dq - 1e-12)
        stability = bool(s[a1] <= s.min() + 1e-12 or r[a1] <= r.min() + 1e-12)
        if not advantage:
            compromise = [int(i) for i in order if q[i] - q[a1] < dq - 1e-12]
        elif not stability:
            compromise = [int(a1), int(a2)]

    return MethodResult(
        method="vikor",
        scores=q,
        ranks=rank_scores(q, higher_is_better=False),
        higher_is_better=False,
        details={
            "S": s,
            "R": r,
            "Q": q,
            "v": v,
            "acceptable_advantage": advantage,
            "acceptable_stability": stability,
            "compromise_set": [matrix.alternatives[i] for i in compromise],
        },
    )
