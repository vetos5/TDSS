"""
Column normalisation schemes. Each takes the raw matrix X (m × n) and a benefit mask and
returns a matrix in which higher is always better, unless stated otherwise.
"""

from __future__ import annotations

import numpy as np

NEUTRAL = 0.5  # score for a column with no spread (min = max)


def minmax(values: np.ndarray, benefit: np.ndarray) -> np.ndarray:
    """(x − min)/(max − min) for benefit criteria, (max − x)/(max − min) for cost criteria.

    A constant column gets ``NEUTRAL`` so it neither helps nor hurts any alternative.
    """
    lo = values.min(axis=0)
    hi = values.max(axis=0)
    span = hi - lo
    safe = np.where(span == 0, 1.0, span)
    out = np.where(benefit, (values - lo) / safe, (hi - values) / safe)
    return np.where(span == 0, NEUTRAL, out)


def vector(values: np.ndarray) -> np.ndarray:
    """x / ‖x‖₂ per column (direction-neutral; used by TOPSIS). A zero column stays zero."""
    norm = np.sqrt((values**2).sum(axis=0))
    return values / np.where(norm == 0, 1.0, norm)


def _require_positive(values: np.ndarray, scheme: str) -> None:
    if np.any(values <= 0):
        raise ValueError(f"{scheme} normalisation requires strictly positive values")


def sum_(values: np.ndarray, benefit: np.ndarray) -> np.ndarray:
    """x / Σx for benefit criteria, (1/x) / Σ(1/x) for cost criteria. Columns sum to 1."""
    _require_positive(values, "sum")
    oriented = np.where(benefit, values, 1.0 / values)
    return oriented / oriented.sum(axis=0)


def max_(values: np.ndarray, benefit: np.ndarray) -> np.ndarray:
    """x / max for benefit criteria, min / x for cost criteria. Best value maps to 1."""
    _require_positive(values, "max")
    return np.where(benefit, values / values.max(axis=0), values.min(axis=0) / values)
