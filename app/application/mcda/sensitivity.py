"""
Deterministic weight sensitivity analysis.

One criterion's weight w_j is moved to t ∈ [0, 1] while the other weights keep their relative
proportions:

    w_k(t) = w_k · (1 − t) / (1 − w_j)   for k ≠ j

(if w_j = 1 the remaining weight is shared equally). For each criterion this yields

* a sweep — every alternative's utility and rank as a function of t, and
* a stability interval [t⁻, t⁺] ∋ w_j inside which the current winner stays first. Its ends are
  the rank-reversal thresholds, located by grid search and refined by bisection.

The narrowest interval identifies the criterion whose weight the recommendation depends on most.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.application.mcda.matrix import DecisionMatrix
from app.application.mcda.smaa import Method


def reweight(weights: np.ndarray, j: int, t: float) -> np.ndarray:
    """Set weight j to t and rescale the others proportionally so the vector sums to 1."""
    w = np.asarray(weights, dtype=float)
    rest = 1.0 - w[j]
    out = np.full_like(w, (1.0 - t) / (len(w) - 1)) if rest <= 1e-12 else w * (1.0 - t) / rest
    out[j] = t
    return out


@dataclass
class CriterionSensitivity:
    criterion: str
    weight: float
    grid: np.ndarray                 # t values
    scores: np.ndarray               # len(grid) × m, the method's own score at each t
    utility: np.ndarray              # len(grid) × m, scores rescaled to [0, 1] at each t
    ranks: np.ndarray                # len(grid) × m
    lower: float | None              # t⁻: winner changes just below this weight (None: never)
    upper: float | None              # t⁺: winner changes just above this weight (None: never)
    winner_below: int | None         # who wins just past t⁻
    winner_above: int | None         # who wins just past t⁺

    @property
    def width(self) -> float:
        """Width of the stability interval (1.0 when the winner never changes)."""
        hi = 1.0 if self.upper is None else self.upper
        lo = 0.0 if self.lower is None else self.lower
        return hi - lo

    @property
    def min_change(self) -> float | None:
        """Smallest |Δw_j| that changes the winner, or None if no change of w_j does."""
        d = [abs(self.weight - b) for b in (self.lower, self.upper) if b is not None]
        return min(d) if d else None


@dataclass
class SensitivityAnalysis:
    method: str
    winner: int
    higher_is_better: bool
    criteria: list[CriterionSensitivity]

    @property
    def critical(self) -> CriterionSensitivity | None:
        """The criterion needing the smallest weight change to change the winner."""
        changing = [c for c in self.criteria if c.min_change is not None]
        return min(changing, key=lambda c: c.min_change) if changing else None


def _winner(method: Method, matrix: DecisionMatrix, w: np.ndarray, current: int) -> int:
    ranks = method(matrix, w).ranks
    # Keep the current winner while it still shares first place (ties do not count as reversal).
    return current if ranks[current] == 1 else int(np.argmin(ranks))


def _bisect(method, matrix, weights, j, inside, outside, current, tol) -> float:
    """Boundary between t = inside (current winner first) and t = outside (it is not)."""
    for _ in range(60):
        if abs(outside - inside) <= tol:
            break
        mid = 0.5 * (inside + outside)
        if _winner(method, matrix, reweight(weights, j, mid), current) == current:
            inside = mid
        else:
            outside = mid
    return 0.5 * (inside + outside)


def analyse_sensitivity(
    matrix: DecisionMatrix,
    weights: np.ndarray,
    method: Method,
    method_name: str,
    *,
    steps: int = 51,
    tol: float = 1e-4,
) -> SensitivityAnalysis:
    grid = np.linspace(0.0, 1.0, steps)
    base = method(matrix, weights)
    winner = int(np.argmin(base.ranks))

    out: list[CriterionSensitivity] = []
    for j, criterion in enumerate(matrix.criteria):
        results = [method(matrix, reweight(weights, j, t)) for t in grid]
        scores = np.array([r.scores for r in results])
        utility = np.array([r.utility for r in results])
        ranks = np.array([r.ranks for r in results])
        w0 = float(weights[j])

        # Walk outward from the current weight; the first grid point with another winner
        # brackets the nearest threshold together with the last point that kept the winner.
        bounds: dict[int, tuple[float | None, int | None]] = {}
        for direction, candidates in ((-1, grid[grid < w0][::-1]), (1, grid[grid > w0])):
            inside = w0
            bounds[direction] = (None, None)
            for t in candidates:
                w = reweight(weights, j, t)
                if _winner(method, matrix, w, winner) == winner:
                    inside = t
                    continue
                edge = _bisect(method, matrix, weights, j, inside, t, winner, tol)
                past = min(max(edge + direction * tol, 0.0), 1.0)
                new = _winner(method, matrix, reweight(weights, j, past), winner)
                bounds[direction] = (edge, new)
                break
        lower, below = bounds[-1]
        upper, above = bounds[1]

        out.append(CriterionSensitivity(
            criterion=criterion.name,
            weight=w0,
            grid=grid,
            scores=scores,
            utility=utility,
            ranks=ranks,
            lower=lower,
            upper=upper,
            winner_below=below,
            winner_above=above,
        ))
    return SensitivityAnalysis(
        method=method_name, winner=winner, higher_is_better=base.higher_is_better, criteria=out
    )
