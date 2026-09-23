"""
Criterion weighting: subjective (AHP pairwise comparisons), objective (Shannon entropy, CRITIC)
and a convex combination of the two.

References
----------
Saaty, T. L. (1980). The Analytic Hierarchy Process. McGraw-Hill.
Shannon, C. E. (1948); Zeleny, M. (1982). Multiple Criteria Decision Making. McGraw-Hill.
Diakoulaki, D., Mavrotas, G., Papayannakis, L. (1995). Determining objective weights in
    multiple criteria problems: the CRITIC method. Computers & Operations Research, 22(7).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.application.mcda.normalisation import minmax

# Saaty's random consistency index for matrices of order n = 1..10.
RANDOM_INDEX = (0.0, 0.0, 0.58, 0.90, 1.12, 1.24, 1.32, 1.41, 1.45, 1.49)
CONSISTENCY_THRESHOLD = 0.10


def normalise(weights: np.ndarray) -> np.ndarray:
    w = np.asarray(weights, dtype=float)
    if np.any(w < 0) or w.sum() <= 0:
        raise ValueError("weights must be non-negative with a positive sum")
    return w / w.sum()


def _equal(n: int) -> np.ndarray:
    return np.full(n, 1.0 / n)


@dataclass(frozen=True)
class EntropyResult:
    weights: np.ndarray
    entropy: np.ndarray       # e_j ∈ [0, 1]
    divergence: np.ndarray    # d_j = 1 − e_j


def entropy(values: np.ndarray) -> EntropyResult:
    """
    Shannon-entropy weights.

        p_ij = x_ij / Σ_i x_ij,   e_j = −(1 / ln m) Σ_i p_ij ln p_ij
        w_j = (1 − e_j) / Σ_k (1 − e_k)

    Criteria whose values barely differ carry little information and get little weight.
    Requires positive values and m ≥ 2. If every criterion is constant, weights are equal.
    """
    m, n = values.shape
    if m < 2:
        raise ValueError("entropy weighting needs at least two alternatives")
    if np.any(values <= 0):
        raise ValueError("entropy weighting requires strictly positive values")
    p = values / values.sum(axis=0)
    e = -(p * np.log(p)).sum(axis=0) / np.log(m)
    e = np.clip(e, 0.0, 1.0)
    d = 1.0 - e
    w = _equal(n) if d.sum() <= 1e-12 else d / d.sum()
    return EntropyResult(weights=w, entropy=e, divergence=d)


@dataclass(frozen=True)
class CriticResult:
    weights: np.ndarray
    std: np.ndarray           # σ_j of the min-max normalised column
    correlation: np.ndarray   # r_jk, n × n (0 where undefined)
    information: np.ndarray   # C_j = σ_j Σ_k (1 − r_jk)


def critic(values: np.ndarray, benefit: np.ndarray) -> CriticResult:
    """
    CRITIC (CRiteria Importance Through Intercriteria Correlation) weights.

        C_j = σ_j Σ_k (1 − r_jk),   w_j = C_j / Σ_k C_k

    σ_j is the standard deviation of the min-max normalised column and r_jk the Pearson
    correlation between columns. Contrast raises a weight, redundancy with other criteria lowers it.
    """
    m, n = values.shape
    if m < 2:
        raise ValueError("CRITIC weighting needs at least two alternatives")
    z = minmax(values, benefit)
    std = z.std(axis=0, ddof=1) if m > 1 else np.zeros(n)
    with np.errstate(invalid="ignore", divide="ignore"):
        r = np.corrcoef(z, rowvar=False) if n > 1 else np.ones((1, 1))
    r = np.nan_to_num(np.atleast_2d(r), nan=0.0)
    np.fill_diagonal(r, 1.0)
    info = std * (1.0 - r).sum(axis=0)
    w = _equal(n) if info.sum() <= 1e-12 else info / info.sum()
    return CriticResult(weights=w, std=std, correlation=r, information=info)


@dataclass(frozen=True)
class AHPResult:
    weights: np.ndarray
    lambda_max: float
    consistency_index: float
    consistency_ratio: float

    @property
    def is_consistent(self) -> bool:
        return self.consistency_ratio < CONSISTENCY_THRESHOLD


def validate_pairwise(matrix: np.ndarray, tol: float = 1e-6) -> np.ndarray:
    """Check that *matrix* is a square, positive, reciprocal comparison matrix."""
    a = np.asarray(matrix, dtype=float)
    if a.ndim != 2 or a.shape[0] != a.shape[1]:
        raise ValueError(f"pairwise matrix must be square, got shape {a.shape}")
    if not np.all(np.isfinite(a)) or np.any(a <= 0):
        raise ValueError("pairwise matrix entries must be positive and finite")
    if not np.allclose(np.diag(a), 1.0, atol=tol):
        raise ValueError("pairwise matrix diagonal must be 1")
    if not np.allclose(a * a.T, 1.0, atol=tol):
        raise ValueError("pairwise matrix must be reciprocal: a_ji = 1 / a_ij")
    return a


def ahp(matrix: np.ndarray) -> AHPResult:
    """
    AHP priority vector from a pairwise comparison matrix A (Saaty eigenvector method).

        A w = λ_max w,   CI = (λ_max − n) / (n − 1),   CR = CI / RI_n

    CR < 0.10 is Saaty's acceptance threshold.
    """
    a = validate_pairwise(matrix)
    n = a.shape[0]
    eigvals, eigvecs = np.linalg.eig(a)
    k = int(np.argmax(eigvals.real))
    lam = float(eigvals[k].real)
    w = np.abs(eigvecs[:, k].real)
    w = w / w.sum()
    ci = 0.0 if n <= 2 else max((lam - n) / (n - 1), 0.0)
    ri = RANDOM_INDEX[n - 1] if n <= len(RANDOM_INDEX) else RANDOM_INDEX[-1]
    cr = 0.0 if ri == 0 else ci / ri
    return AHPResult(weights=w, lambda_max=lam, consistency_index=ci, consistency_ratio=cr)


def combine(subjective: np.ndarray, objective: np.ndarray, alpha: float = 0.5) -> np.ndarray:
    """Convex combination w = α·w_subj + (1 − α)·w_obj, α ∈ [0, 1]."""
    if not 0.0 <= alpha <= 1.0:
        raise ValueError("alpha must lie in [0, 1]")
    return normalise(alpha * normalise(subjective) + (1.0 - alpha) * normalise(objective))
