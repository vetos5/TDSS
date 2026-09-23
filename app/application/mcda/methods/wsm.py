"""
Weighted Sum Model (Simple Additive Weighting).

    S_i = Σ_j w_j · x̄_ij,   x̄ = min-max normalised matrix (1 = best)

Fishburn, P. C. (1967). Additive utilities with incomplete product sets. Operations Research 15(3).
"""

from __future__ import annotations

import numpy as np

from app.application.mcda.matrix import DecisionMatrix
from app.application.mcda.methods.base import MethodResult, rank_scores
from app.application.mcda.normalisation import minmax


def run(matrix: DecisionMatrix, weights: np.ndarray) -> MethodResult:
    normalised = minmax(matrix.values, matrix.benefit)
    weighted = normalised * weights
    scores = weighted.sum(axis=1)
    return MethodResult(
        method="wsm",
        scores=scores,
        ranks=rank_scores(scores),
        details={"normalised": normalised, "weighted": weighted},
    )
