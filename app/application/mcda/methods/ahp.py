"""
AHP synthesis of alternatives from quantitative data (distributive mode).

For each criterion j the alternatives are compared by value ratios, a_ik = x_ij / x_kj for
benefit criteria and x_kj / x_ij for cost criteria. Such a matrix is perfectly consistent, so its
principal eigenvector is exactly the sum-normalised column:

    p_ij = x_ij / Σ_k x_kj   (benefit),   p_ij = (1/x_ij) / Σ_k (1/x_kj)   (cost)

The global priority is P_i = Σ_j w_j p_ij. Criterion weights typically come from an expert
pairwise matrix via ``weighting.ahp``.

Saaty, T. L. (1980). The Analytic Hierarchy Process. McGraw-Hill.
"""

from __future__ import annotations

import numpy as np

from app.application.mcda.matrix import DecisionMatrix
from app.application.mcda.methods.base import MethodResult, rank_scores
from app.application.mcda.normalisation import sum_


def ratio_matrix(column: np.ndarray, benefit: bool) -> np.ndarray:
    """Alternative-vs-alternative comparison matrix for one criterion."""
    col = np.asarray(column, dtype=float)
    a = col[:, None] / col[None, :]
    return a if benefit else a.T


def run(matrix: DecisionMatrix, weights: np.ndarray) -> MethodResult:
    local = sum_(matrix.values, matrix.benefit)
    scores = local @ weights
    return MethodResult(
        method="ahp",
        scores=scores,
        ranks=rank_scores(scores),
        details={"local_priorities": local},
    )
