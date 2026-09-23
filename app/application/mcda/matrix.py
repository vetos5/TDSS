"""Decision matrix: m alternatives × n criteria with optimisation directions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from app.application.dss_engine import Alternative, Criterion


@dataclass(frozen=True)
class DecisionMatrix:
    """
    Immutable m × n performance table.

    Attributes
    ----------
    alternatives :
        Alternative names, one per row.
    criteria :
        Criteria, one per column, in the same order as ``values`` columns.
    values :
        Raw performance values x_ij, shape (m, n), all finite.
    """

    alternatives: tuple[str, ...]
    criteria: tuple[Criterion, ...]
    values: np.ndarray

    def __post_init__(self) -> None:
        values = np.asarray(self.values, dtype=float)
        if values.ndim != 2:
            raise ValueError(f"values must be 2-D, got shape {values.shape}")
        if values.shape != (len(self.alternatives), len(self.criteria)):
            raise ValueError(
                f"values shape {values.shape} does not match "
                f"{len(self.alternatives)} alternatives × {len(self.criteria)} criteria"
            )
        if not np.all(np.isfinite(values)):
            raise ValueError("values must be finite")
        values.setflags(write=False)
        object.__setattr__(self, "values", values)

    @classmethod
    def from_alternatives(
        cls, alternatives: Sequence[Alternative], criteria: Sequence[Criterion]
    ) -> DecisionMatrix:
        """Build from engine dataclasses; a missing criterion value counts as 0.0."""
        return cls(
            alternatives=tuple(a.name for a in alternatives),
            criteria=tuple(criteria),
            values=np.array(
                [[a.raw_values.get(c.name, 0.0) for c in criteria] for a in alternatives],
                dtype=float,
            ).reshape(len(alternatives), len(criteria)),
        )

    @property
    def shape(self) -> tuple[int, int]:
        return self.values.shape

    @property
    def benefit(self) -> np.ndarray:
        """Boolean mask, True where the criterion is maximised."""
        return np.array([c.direction == "maximize" for c in self.criteria], dtype=bool)

    @property
    def criterion_names(self) -> list[str]:
        return [c.name for c in self.criteria]

    def weights_vector(
        self, weights: dict[str, float] | Sequence[float] | np.ndarray
    ) -> np.ndarray:
        """Align *weights* with the criteria order and normalise them to sum to 1."""
        if isinstance(weights, dict):
            missing = [c.name for c in self.criteria if c.name not in weights]
            if missing:
                raise ValueError(f"weights missing for criteria: {missing}")
            w = np.array([weights[c.name] for c in self.criteria], dtype=float)
        else:
            w = np.asarray(weights, dtype=float)
        if w.shape != (len(self.criteria),):
            raise ValueError(f"expected {len(self.criteria)} weights, got shape {w.shape}")
        if np.any(w < 0) or not np.all(np.isfinite(w)):
            raise ValueError("weights must be finite and non-negative")
        total = w.sum()
        if total <= 0:
            raise ValueError("sum of criterion weights must be positive")
        return w / total
