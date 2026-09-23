"""
Evaluation service: turns a weighting choice into a weight vector and runs the MCDA methods.

Kept free of web-framework types so it can be reused by the copilot and batch experiments.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Sequence

import numpy as np

from app.application.adjustments import AdjustmentNote
from app.application.mcda import DecisionMatrix, MethodResult, RankAgreement, evaluate, weighting
from app.application.mcda import rank_agreement as _rank_agreement

WeightingMode = Literal["manual", "entropy", "critic", "ahp", "combined"]


@dataclass
class WeightSelection:
    weights: np.ndarray
    mode: str
    details: dict[str, Any] = field(default_factory=dict)
    notes: list[AdjustmentNote] = field(default_factory=list)


def _objective(matrix: DecisionMatrix, kind: str) -> tuple[np.ndarray, dict[str, Any]]:
    if kind == "entropy":
        res = weighting.entropy(matrix.values)
        return res.weights, {"entropy": res.entropy, "divergence": res.divergence}
    res = weighting.critic(matrix.values, matrix.benefit)
    return res.weights, {
        "std": res.std,
        "information": res.information,
        "correlation": res.correlation,
    }


def _ahp(ahp_matrix: Sequence[Sequence[float]] | None, n: int):
    if ahp_matrix is None:
        raise ValueError("AHP weighting requires a pairwise comparison matrix")
    a = np.asarray(ahp_matrix, dtype=float)
    if a.shape != (n, n):
        raise ValueError(f"AHP matrix must be {n}×{n}, got {a.shape}")
    return weighting.ahp(a)


def select_weights(
    matrix: DecisionMatrix,
    manual: np.ndarray,
    mode: WeightingMode = "manual",
    *,
    ahp_matrix: Sequence[Sequence[float]] | None = None,
    subjective: Literal["manual", "ahp"] = "manual",
    objective: Literal["entropy", "critic"] = "entropy",
    alpha: float = 0.5,
) -> WeightSelection:
    """
    Resolve the criterion weights for *matrix*.

    Raises ``ValueError`` for an invalid AHP matrix. Objective weights need at least two
    alternatives; with fewer, the manual weights are used and a note explains why.
    """
    n = matrix.shape[1]
    manual = weighting.normalise(manual)
    notes: list[AdjustmentNote] = []
    details: dict[str, Any] = {}

    needs_objective = mode in ("entropy", "critic") or mode == "combined"
    if needs_objective and matrix.shape[0] < 2:
        notes.append(AdjustmentNote(
            kind="weighting",
            message="Objective weighting needs at least two feasible alternatives; "
                    "manual weights were used instead.",
        ))
        return WeightSelection(manual, "manual", details, notes)

    def ahp_weights() -> np.ndarray:
        res = _ahp(ahp_matrix, n)
        details.update(
            ahp_weights=res.weights,
            lambda_max=res.lambda_max,
            consistency_index=res.consistency_index,
            consistency_ratio=res.consistency_ratio,
        )
        if not res.is_consistent:
            notes.append(AdjustmentNote(
                kind="weighting",
                message=f"AHP consistency ratio CR = {res.consistency_ratio:.3f} ≥ "
                        f"{weighting.CONSISTENCY_THRESHOLD:.2f}: the pairwise judgements are "
                        "inconsistent and should be revised.",
            ))
        return res.weights

    if mode == "manual":
        w = manual
    elif mode in ("entropy", "critic"):
        w, extra = _objective(matrix, mode)
        details.update(extra)
    elif mode == "ahp":
        w = ahp_weights()
    elif mode == "combined":
        subj = ahp_weights() if subjective == "ahp" else manual
        obj, extra = _objective(matrix, objective)
        details.update(extra, subjective=subj, objective=obj, alpha=alpha,
                       subjective_mode=subjective, objective_mode=objective)
        w = weighting.combine(subj, obj, alpha)
    else:
        raise ValueError(f"unknown weighting mode {mode!r}")

    return WeightSelection(w, mode, details, notes)


@dataclass
class MultiMethodEvaluation:
    matrix: DecisionMatrix
    weights: WeightSelection
    results: dict[str, MethodResult]
    agreement: RankAgreement | None


def run_methods(
    matrix: DecisionMatrix, weights: WeightSelection, methods: Sequence[str]
) -> MultiMethodEvaluation:
    results = evaluate(matrix, weights.weights, methods)
    agreement = _rank_agreement(results) if len(results) >= 2 else None
    return MultiMethodEvaluation(matrix, weights, results, agreement)
