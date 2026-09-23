"""
Multi-method MCDA engine (pure NumPy, no I/O).

Usage
-----
>>> matrix = DecisionMatrix.from_alternatives(alternatives, criteria)
>>> w = matrix.weights_vector({"cost": 0.4, ...})
>>> results = evaluate(matrix, w, ["wsm", "topsis", "vikor"])
>>> agreement = rank_agreement(results)
"""

from __future__ import annotations

from typing import Any, Callable, Iterable

import numpy as np

from app.application.mcda import weighting
from app.application.mcda.comparison import RankAgreement, rank_agreement
from app.application.mcda.matrix import DecisionMatrix
from app.application.mcda.methods import ahp, promethee, topsis, vikor, wsm
from app.application.mcda.methods.base import MethodResult

METHODS: dict[str, Callable[..., MethodResult]] = {
    "wsm": wsm.run,
    "topsis": topsis.run,
    "ahp": ahp.run,
    "promethee": promethee.run,
    "vikor": vikor.run,
}


def evaluate(
    matrix: DecisionMatrix,
    weights: np.ndarray,
    methods: Iterable[str] = ("wsm",),
    options: dict[str, dict[str, Any]] | None = None,
) -> dict[str, MethodResult]:
    """Run each named method; *options* maps a method id to extra keyword arguments."""
    options = options or {}
    results: dict[str, MethodResult] = {}
    for name in methods:
        if name not in METHODS:
            raise ValueError(f"unknown MCDA method {name!r}; available: {sorted(METHODS)}")
        results[name] = METHODS[name](matrix, weights, **options.get(name, {}))
    return results


__all__ = [
    "METHODS",
    "DecisionMatrix",
    "MethodResult",
    "RankAgreement",
    "evaluate",
    "rank_agreement",
    "weighting",
]
