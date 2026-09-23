"""
TOPSIS — Technique for Order Preference by Similarity to Ideal Solution.

    r_ij = x_ij / ‖x_j‖₂,   v_ij = w_j r_ij
    A⁺_j = best v_ij,   A⁻_j = worst v_ij   (max/min by criterion direction)
    D⁺_i = ‖v_i − A⁺‖₂,   D⁻_i = ‖v_i − A⁻‖₂,   C_i = D⁻_i / (D⁺_i + D⁻_i)

Hwang, C. L., Yoon, K. (1981). Multiple Attribute Decision Making. Springer.
"""

from __future__ import annotations

import numpy as np

from app.application.mcda.matrix import DecisionMatrix
from app.application.mcda.methods.base import MethodResult, rank_scores
from app.application.mcda.normalisation import NEUTRAL, vector


def run(matrix: DecisionMatrix, weights: np.ndarray) -> MethodResult:
    benefit = matrix.benefit
    v = vector(matrix.values) * weights
    ideal = np.where(benefit, v.max(axis=0), v.min(axis=0))
    anti_ideal = np.where(benefit, v.min(axis=0), v.max(axis=0))
    d_plus = np.sqrt(((v - ideal) ** 2).sum(axis=1))
    d_minus = np.sqrt(((v - anti_ideal) ** 2).sum(axis=1))
    total = d_plus + d_minus
    closeness = np.where(total == 0, NEUTRAL, d_minus / np.where(total == 0, 1.0, total))
    return MethodResult(
        method="topsis",
        scores=closeness,
        ranks=rank_scores(closeness),
        details={
            "weighted_normalised": v,
            "ideal": ideal,
            "anti_ideal": anti_ideal,
            "d_plus": d_plus,
            "d_minus": d_minus,
        },
    )
