"""Common result type and ranking helper for all MCDA methods."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy.stats import rankdata

# Scores closer than this are treated as tied when ranking.
TIE_DECIMALS = 10


@dataclass(frozen=True)
class MethodResult:
    """
    Outcome of one MCDA method.

    Attributes
    ----------
    method :
        Registry id, e.g. ``"topsis"``.
    scores :
        The method's own score per alternative (row order of the decision matrix).
    ranks :
        1 = best; tied scores share the lower rank ("competition" ranking: 1, 1, 3).
    higher_is_better :
        False for methods whose score is a loss (VIKOR's Q).
    details :
        Method-specific intermediate values (arrays keyed by name) for display and teaching.
    """

    method: str
    scores: np.ndarray
    ranks: np.ndarray
    higher_is_better: bool = True
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def utility(self) -> np.ndarray:
        """Scores rescaled to [0, 1] with 1 = best, comparable across methods."""
        s = self.scores if self.higher_is_better else -self.scores
        span = s.max() - s.min()
        if span == 0:
            return np.ones_like(s)
        return (s - s.min()) / span


def rank_scores(scores: np.ndarray, higher_is_better: bool = True) -> np.ndarray:
    """Competition ranking of *scores* (1 = best)."""
    s = np.round(np.asarray(scores, dtype=float), TIE_DECIMALS)
    return rankdata(-s if higher_is_better else s, method="min").astype(int)
