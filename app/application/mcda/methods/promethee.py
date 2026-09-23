"""
PROMETHEE II — Preference Ranking Organization METHod for Enrichment Evaluations.

For each ordered pair (a, b) and criterion j, d_j(a, b) = g_j(a) − g_j(b) (sign flipped for cost
criteria) is mapped to a preference degree P_j ∈ [0, 1] by a preference function. Then

    π(a, b) = Σ_j w_j P_j(a, b)
    φ⁺(a) = Σ_b π(a, b) / (m − 1),   φ⁻(a) = Σ_b π(b, a) / (m − 1),   φ(a) = φ⁺(a) − φ⁻(a)

and alternatives are ranked by the net flow φ.

Brans, J. P., Vincke, Ph. (1985). A preference ranking organisation method.
    Management Science 31(6).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

from app.application.mcda.matrix import DecisionMatrix
from app.application.mcda.methods.base import MethodResult, rank_scores

PreferenceKind = Literal["usual", "vshape", "linear"]


@dataclass(frozen=True)
class PreferenceFunction:
    """
    ``usual``  — P = 1 if d > 0 (type I).
    ``vshape`` — P = d / p, capped at 1 (type III).
    ``linear`` — 0 up to q, linear from q to p, 1 beyond (type V).

    ``p = None`` means "the criterion's range" (max − min), a scale-free default.
    """

    kind: PreferenceKind = "vshape"
    q: float = 0.0
    p: float | None = None

    def __call__(self, d: np.ndarray, spread: float) -> np.ndarray:
        if self.kind == "usual":
            return (d > 0).astype(float)
        p = spread if self.p is None else self.p
        q = 0.0 if self.kind == "vshape" else self.q
        if p <= q:
            return (d > q).astype(float)
        return np.clip((d - q) / (p - q), 0.0, 1.0)


DEFAULT_PREFERENCE = PreferenceFunction()


def run(
    matrix: DecisionMatrix,
    weights: np.ndarray,
    preferences: dict[str, PreferenceFunction] | None = None,
) -> MethodResult:
    m, n = matrix.shape
    values, benefit = matrix.values, matrix.benefit
    preferences = preferences or {}

    pi = np.zeros((m, m))
    for j, criterion in enumerate(matrix.criteria):
        col = values[:, j]
        d = col[:, None] - col[None, :]
        if not benefit[j]:
            d = -d
        spread = float(col.max() - col.min())
        fn = preferences.get(criterion.name, DEFAULT_PREFERENCE)
        pi += weights[j] * fn(d, spread)
    np.fill_diagonal(pi, 0.0)

    denom = max(m - 1, 1)
    phi_plus = pi.sum(axis=1) / denom
    phi_minus = pi.sum(axis=0) / denom
    phi = phi_plus - phi_minus
    return MethodResult(
        method="promethee",
        scores=phi,
        ranks=rank_scores(phi),
        details={"preference_matrix": pi, "phi_plus": phi_plus, "phi_minus": phi_minus},
    )
