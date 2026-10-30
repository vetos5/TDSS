"""
Grey-box criterion-value prediction: Bayesian residual correction of the expert pipeline.

The expert constants and site-adjustment rules (``app.application.adjustments``) already encode
most of what is known about interchange costs, footprints, capacities and safety. Past project
documents rarely number more than a few dozen, far too few to learn those values from scratch —
but enough to learn *how real projects deviate* from the expert pipeline. So for each criterion
``c`` the model regresses the log residual

    r = ln(observed_c / baseline_c(type, conditions))

on a small, fixed feature vector (p = 16): a per-type intercept for each of the eight types (no
global intercept) and condition slopes — ``log_aadt = ln(AADT / 45 000)``, ``lanes = lanes − 2``,
``speed = (speed − 100) / 20`` and terrain / env. dummies against Flat / Low. One regression per
criterion spans all types, so a slope learnt on Turbines also informs Diamonds.

Conjugate Normal-Inverse-Gamma prior (Bayesian linear regression, e.g. Murphy, 2012, §7.6.3):

    β | σ² ~ N(0, σ² V0),   σ² ~ InvGamma(a0, b0),   V0 = diag(τ_j² / σ0²),   b0 = σ0² (a0 − 1)

Posterior (closed form — retraining is a 16×16 Cholesky solve per criterion):

    Vn = (V0⁻¹ + XᵀX)⁻¹,   mn = Vn Xᵀ r,   an = a0 + n/2,   bn = b0 + ½ (rᵀr − mnᵀ Vn⁻¹ mn)

Posterior predictive at x*: Student-t with ν = 2 an, location μ = x*ᵀ mn and scale
s = √((bn / an)(1 + x*ᵀ Vn x*)). The point prediction is the posterior median baseline · e^μ and
the interval baseline · e^(μ ± t_ν · s). With no records the prior mean β = 0 gives e^μ = 1, so
the model reproduces the expert values exactly until data exist.

Murphy, K. P. (2012). Machine Learning: A Probabilistic Perspective. MIT Press.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
from scipy import linalg
from scipy.stats import t as student_t

from app.application.adjustments import apply_site_adjustments
from app.application.dss_engine import Alternative
from app.application.prediction.records import (
    CONTEXT_OF_TYPE,
    INTERCHANGE_TYPES,
    Conditions,
    ProjectRecord,
)
from app.data.interchange_data import INTERCHANGE_DATA
from app.data.prediction_defaults import (
    CV_FOLDS,
    CV_MIN_OBS,
    ENV_LEVELS,
    INTERVAL_LEVEL,
    LOO_MAX_OBS,
    PRIOR_A0,
    PRIOR_SIGMA0,
    PRIOR_TAU_SLOPE,
    PRIOR_TAU_TYPE,
    REFERENCE_CONDITIONS,
    SAFETY_BOUNDS,
    SPEED_FEATURE_STEP,
    TARGETS,
    TERRAIN_LEVELS,
)

# ---------------------------------------------------------------------------
# Expert baseline
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _BaselineParams:
    """``ProjectParameters`` for the expert rules: zero demand (no capacity penalty, so the
    throughput baseline is the rated capacity) and no hard constraints."""

    design_speed: float
    aadt: float
    terrain: str
    env_sensitivity: str
    peak_factor: int = 0
    budget: float = math.inf
    land_limit: float = math.inf


def expert_baseline(interchange_type: str, conditions: Any = None) -> Dict[str, float]:
    """Expert criterion values of *interchange_type* under *conditions*.

    Runs the existing site-adjustment rules (terrain cost factor, env. land factor, loop-ramp
    speed penalty) on the expert constants with ``peak_factor = 0``, so the model learns residuals
    against exactly what the rest of the system would show.
    """
    cond = Conditions.of(conditions)
    raw = INTERCHANGE_DATA[CONTEXT_OF_TYPE[interchange_type]][interchange_type]
    params = _BaselineParams(
        design_speed=cond.design_speed,
        aadt=cond.aadt,
        terrain=cond.terrain,
        env_sensitivity=cond.env_sensitivity,
    )
    adjusted, _notes = apply_site_adjustments(
        [Alternative(name=interchange_type, raw_values=dict(raw))], params
    )
    return {c: float(adjusted[0].raw_values[c]) for c in TARGETS}


# ---------------------------------------------------------------------------
# Features
# ---------------------------------------------------------------------------

_SLOPE_FEATURES: Tuple[str, ...] = (
    "log_aadt", "lanes", "speed",
    *(f"terrain:{level}" for level in TERRAIN_LEVELS[1:]),
    *(f"env:{level}" for level in ENV_LEVELS[1:]),
)
FEATURE_NAMES: Tuple[str, ...] = (
    *(f"type:{name}" for name in INTERCHANGE_TYPES),
    *_SLOPE_FEATURES,
)
N_TYPES = len(INTERCHANGE_TYPES)


def features(interchange_type: str, conditions: Any = None) -> np.ndarray:
    """Feature vector x (length 16, order ``FEATURE_NAMES``) for a type under *conditions*."""
    cond = Conditions.of(conditions)
    x = np.zeros(len(FEATURE_NAMES))
    x[INTERCHANGE_TYPES.index(interchange_type)] = 1.0
    x[N_TYPES + 0] = math.log(cond.aadt / float(REFERENCE_CONDITIONS["aadt"]))
    x[N_TYPES + 1] = cond.num_lanes - float(REFERENCE_CONDITIONS["num_lanes"])
    x[N_TYPES + 2] = (
        cond.design_speed - float(REFERENCE_CONDITIONS["design_speed"])
    ) / SPEED_FEATURE_STEP
    for level in TERRAIN_LEVELS[1:]:
        x[FEATURE_NAMES.index(f"terrain:{level}")] = float(cond.terrain == level)
    for level in ENV_LEVELS[1:]:
        x[FEATURE_NAMES.index(f"env:{level}")] = float(cond.env_sensitivity == level)
    return x


def prior_scale_diag(criterion: str) -> np.ndarray:
    """Diagonal of V0 = τ_j² / σ0_c² (prior coefficient variance in units of σ²)."""
    tau = np.array([PRIOR_TAU_TYPE] * N_TYPES + [PRIOR_TAU_SLOPE] * len(_SLOPE_FEATURES))
    return tau**2 / PRIOR_SIGMA0[criterion] ** 2


# ---------------------------------------------------------------------------
# Normal-Inverse-Gamma Bayesian linear regression
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NIGPosterior:
    """Posterior N(mn, σ² Vn) × InvGamma(an, bn) of a conjugate Bayesian linear regression."""

    mean: np.ndarray        # mn, shape (p,)
    scale: np.ndarray       # Vn, shape (p, p)
    a: float
    b: float
    n: int

    @property
    def df(self) -> float:
        return 2.0 * self.a

    @property
    def noise_sd(self) -> float:
        """Posterior mean of σ², square-rooted: √(bn / (an − 1))."""
        return math.sqrt(self.b / (self.a - 1.0))

    @property
    def coef_sd(self) -> np.ndarray:
        """Marginal posterior sd of each coefficient: √(diag(Vn) · bn / (an − 1))."""
        return np.sqrt(np.diag(self.scale) * self.b / (self.a - 1.0))

    def predictive(self, X: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Location μ and scale s of the Student-t predictive (ν = ``df``) for rows of *X*."""
        X = np.atleast_2d(X)
        mu = X @ self.mean
        quad = np.einsum("ij,jk,ik->i", X, self.scale, X)
        return mu, np.sqrt(self.b / self.a * (1.0 + quad))


def fit_nig(
    X: np.ndarray, r: np.ndarray, v0_diag: np.ndarray, a0: float, b0: float
) -> NIGPosterior:
    """Closed-form NIG posterior for r = Xβ + ε with prior β | σ² ~ N(0, σ² diag(v0_diag))."""
    X = np.asarray(X, dtype=float).reshape(-1, len(v0_diag))
    r = np.asarray(r, dtype=float).reshape(-1)
    precision = X.T @ X + np.diag(1.0 / v0_diag)          # Vn⁻¹
    factor = linalg.cho_factor(precision, lower=True)
    xtr = X.T @ r
    mean = linalg.cho_solve(factor, xtr)
    scale = linalg.cho_solve(factor, np.eye(len(v0_diag)))
    # mnᵀ Vn⁻¹ mn = mnᵀ Xᵀ r because Vn⁻¹ mn = Xᵀ r; the difference is ≥ 0 analytically.
    sse = max(float(r @ r - mean @ xtr), 0.0)
    n = len(r)
    return NIGPosterior(mean=mean, scale=scale, a=a0 + n / 2.0, b=b0 + 0.5 * sse, n=n)


def prior_hyperparameters(criterion: str) -> Tuple[np.ndarray, float, float]:
    """(diag V0, a0, b0) for *criterion*; b0 = σ0² (a0 − 1) so that E[σ²] = σ0²."""
    sigma0 = PRIOR_SIGMA0[criterion]
    return prior_scale_diag(criterion), PRIOR_A0, sigma0**2 * (PRIOR_A0 - 1.0)


def fit_criterion(criterion: str, X: np.ndarray, r: np.ndarray) -> NIGPosterior:
    v0, a0, b0 = prior_hyperparameters(criterion)
    return fit_nig(X, r, v0, a0, b0)


# ---------------------------------------------------------------------------
# Training data
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CriterionData:
    """Design matrix of the records that observed one criterion."""

    X: np.ndarray            # (n, p)
    r: np.ndarray            # (n,) log residuals
    observed: np.ndarray     # (n,)
    baseline: np.ndarray     # (n,)

    @property
    def n(self) -> int:
        return len(self.r)


def build_training_data(records: Iterable[ProjectRecord]) -> Dict[str, CriterionData]:
    """Per criterion, the rows of the records that have that target."""
    rows: Dict[str, List[Tuple[np.ndarray, float, float]]] = {c: [] for c in TARGETS}
    for record in records:
        x = features(record.interchange_type, record.conditions)
        baseline = expert_baseline(record.interchange_type, record.conditions)
        for criterion, observed in record.targets.items():
            if criterion in rows:
                rows[criterion].append((x, float(observed), baseline[criterion]))
    data: Dict[str, CriterionData] = {}
    for criterion, items in rows.items():
        X = np.array([x for x, _, _ in items]).reshape(-1, len(FEATURE_NAMES))
        observed = np.array([o for _, o, _ in items], dtype=float)
        baseline = np.array([b for _, _, b in items], dtype=float)
        data[criterion] = CriterionData(
            X=X, r=np.log(observed / baseline), observed=observed, baseline=baseline
        )
    return data


def _t_quantile(level: float, df: float) -> float:
    return float(student_t.ppf(0.5 + level / 2.0, df))


def _clamp(criterion: str, values: np.ndarray) -> np.ndarray:
    if criterion == "safety_index":
        return np.clip(values, *SAFETY_BOUNDS)
    return values


def _predict_values(
    posterior: NIGPosterior, criterion: str, X: np.ndarray, baseline: np.ndarray, level: float
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(predicted, low, high) on the natural scale; safety clamped to [1, 10]."""
    mu, s = posterior.predictive(X)
    half = _t_quantile(level, posterior.df) * s
    return (
        _clamp(criterion, baseline * np.exp(mu)),
        _clamp(criterion, baseline * np.exp(mu - half)),
        _clamp(criterion, baseline * np.exp(mu + half)),
    )


# ---------------------------------------------------------------------------
# Residual model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Correction:
    """Multiplicative model correction of one criterion at given conditions.

    ``factor`` = e^μ multiplies the expert value; ``low_ratio`` / ``high_ratio`` are the interval
    bounds divided by the point prediction (after the safety clamp).
    """

    factor: float
    low_ratio: float
    high_ratio: float


class ResidualModel:
    """Fitted residual-correction model: one NIG posterior per criterion.

    Usable on its own: ``ResidualModel.fit(records).predict("Turbine", params)``.
    """

    def __init__(
        self,
        posteriors: Mapping[str, NIGPosterior],
        *,
        n_records: int = 0,
        n_synthetic: int = 0,
        interval_level: float = INTERVAL_LEVEL,
    ) -> None:
        self.posteriors: Dict[str, NIGPosterior] = dict(posteriors)
        self.n_records = n_records
        self.n_synthetic = n_synthetic
        self.interval_level = interval_level

    @classmethod
    def fit(
        cls, records: Sequence[ProjectRecord], *, interval_level: float = INTERVAL_LEVEL
    ) -> "ResidualModel":
        data = build_training_data(records)
        return cls.from_training_data(
            data,
            n_records=len(records),
            n_synthetic=sum(1 for r in records if r.synthetic),
            interval_level=interval_level,
        )

    @classmethod
    def from_training_data(
        cls,
        data: Mapping[str, CriterionData],
        *,
        n_records: int = 0,
        n_synthetic: int = 0,
        interval_level: float = INTERVAL_LEVEL,
    ) -> "ResidualModel":
        posteriors = {c: fit_criterion(c, data[c].X, data[c].r) for c in TARGETS}
        return cls(
            posteriors,
            n_records=n_records,
            n_synthetic=n_synthetic,
            interval_level=interval_level,
        )

    # -- queries -------------------------------------------------------------

    def n_obs(self, criterion: str) -> int:
        return self.posteriors[criterion].n

    def noise_sd(self, criterion: str) -> float:
        return self.posteriors[criterion].noise_sd

    def predict(
        self, interchange_type: str, conditions: Any = None
    ) -> Dict[str, Dict[str, float]]:
        """Per criterion ``{expert, predicted, low, high}`` for one type under *conditions*.

        *conditions* may be a ``Conditions``, a mapping, or an object with the attributes
        (``backend.schemas.ProjectParams`` works as is).
        """
        cond = Conditions.of(conditions)
        x = features(interchange_type, cond)[None, :]
        baseline = expert_baseline(interchange_type, cond)
        out: Dict[str, Dict[str, float]] = {}
        for criterion in TARGETS:
            expert = baseline[criterion]
            predicted, low, high = _predict_values(
                self.posteriors[criterion], criterion, x, np.array([expert]),
                self.interval_level,
            )
            out[criterion] = {
                "expert": expert,
                "predicted": float(predicted[0]),
                "low": float(low[0]),
                "high": float(high[0]),
            }
        return out

    def corrections(self, interchange_type: str, conditions: Any = None) -> Dict[str, Correction]:
        """Per criterion the multiplicative correction e^μ and the interval ratios."""
        cond = Conditions.of(conditions)
        x = features(interchange_type, cond)[None, :]
        prediction = self.predict(interchange_type, cond)
        out: Dict[str, Correction] = {}
        for criterion in TARGETS:
            mu, _ = self.posteriors[criterion].predictive(x)
            p = prediction[criterion]
            out[criterion] = Correction(
                factor=float(np.exp(mu[0])),
                low_ratio=p["low"] / p["predicted"],
                high_ratio=p["high"] / p["predicted"],
            )
        return out

    def correct_values(
        self, interchange_type: str, raw_values: Mapping[str, float], conditions: Any = None
    ) -> Dict[str, float]:
        """*raw_values* (unadjusted expert constants) × e^μ per criterion, safety clamped.

        Feed the result to ``apply_project_params`` instead of the constants: the site rules,
        capacity penalty and feasibility filter then run on the corrected values.
        """
        corrections = self.corrections(interchange_type, conditions)
        values = dict(raw_values)
        for criterion, correction in corrections.items():
            if criterion in values:
                corrected = np.array([values[criterion] * correction.factor])
                values[criterion] = float(_clamp(criterion, corrected)[0])
        return values

    def value_ranges(
        self, interchange_types: Iterable[str], conditions: Any = None
    ) -> Dict[str, Tuple[float, float]]:
        """Per criterion (min low_ratio, max high_ratio) over *interchange_types*.

        A multiplicative uncertainty range for robustness analysis taken from the model's
        prediction intervals, kept within 0 < low ≤ 1 ≤ high ≤ 10.
        """
        ranges: Dict[str, Tuple[float, float]] = {}
        all_corrections = [self.corrections(t, conditions) for t in interchange_types]
        for criterion in TARGETS:
            lows = [c[criterion].low_ratio for c in all_corrections]
            highs = [c[criterion].high_ratio for c in all_corrections]
            low = min(max(min(lows, default=1.0), 1e-6), 1.0)
            high = min(max(max(highs, default=1.0), 1.0), 10.0)
            ranges[criterion] = (low, high)
        return ranges

    def coefficients(self) -> Dict[str, List[Dict[str, Any]]]:
        """Per criterion, per feature: posterior mean and sd of the log-scale coefficient."""
        out: Dict[str, List[Dict[str, Any]]] = {}
        for criterion in TARGETS:
            posterior = self.posteriors[criterion]
            out[criterion] = [
                {"feature": name, "mean": float(m), "sd": float(s)}
                for name, m, s in zip(FEATURE_NAMES, posterior.mean, posterior.coef_sd, strict=True)
            ]
        return out


# ---------------------------------------------------------------------------
# Cross-validation
# ---------------------------------------------------------------------------


def _folds(n: int) -> List[np.ndarray]:
    """Held-out index sets: leave-one-out up to LOO_MAX_OBS, else deterministic i mod K folds."""
    if n <= LOO_MAX_OBS:
        return [np.array([i]) for i in range(n)]
    return [np.arange(k, n, CV_FOLDS) for k in range(CV_FOLDS)]


def cross_validate_criterion(
    criterion: str, data: CriterionData, *, interval_level: float = INTERVAL_LEVEL
) -> Dict[str, Optional[float]]:
    """Out-of-sample accuracy of the expert values vs. the model for one criterion.

    ``loo_mape_*`` are mean |observed − value| / observed over held-out records and
    ``coverage90`` the share of held-out observations inside the prediction interval. All three
    are None below ``CV_MIN_OBS`` observations.
    """
    n = data.n
    metrics: Dict[str, Optional[float]] = {
        "n_obs": n, "loo_mape_expert": None, "loo_mape_model": None, "coverage90": None,
    }
    if n < CV_MIN_OBS:
        return metrics
    predicted = np.empty(n)
    low = np.empty(n)
    high = np.empty(n)
    for held_out in _folds(n):
        keep = np.ones(n, dtype=bool)
        keep[held_out] = False
        posterior = fit_criterion(criterion, data.X[keep], data.r[keep])
        p, lo, hi = _predict_values(
            posterior, criterion, data.X[held_out], data.baseline[held_out], interval_level
        )
        predicted[held_out], low[held_out], high[held_out] = p, lo, hi
    observed = data.observed
    metrics["loo_mape_expert"] = float(np.mean(np.abs(observed - data.baseline) / observed))
    metrics["loo_mape_model"] = float(np.mean(np.abs(observed - predicted) / observed))
    metrics["coverage90"] = float(np.mean((observed >= low) & (observed <= high)))
    return metrics


def cross_validate(
    records: Sequence[ProjectRecord] | Mapping[str, CriterionData],
    *,
    interval_level: float = INTERVAL_LEVEL,
) -> Dict[str, Dict[str, Optional[float]]]:
    """``cross_validate_criterion`` for every criterion (records or prebuilt training data)."""
    data = records if isinstance(records, Mapping) else build_training_data(records)
    return {
        c: cross_validate_criterion(c, data[c], interval_level=interval_level) for c in TARGETS
    }
