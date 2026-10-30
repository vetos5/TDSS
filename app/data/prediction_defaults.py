"""
Constants of the document-trained criterion-value prediction model ("Bayesian residual
correction"). Constants only — the logic lives in ``app.application.prediction``.

Assumptions
-----------
* **Reference conditions.** The expert constants in ``INTERCHANGE_DATA`` describe a "typical"
  project; we interpret them as values at AADT 45 000 veh/day, 2 lanes per direction, design speed
  100 km/h, flat terrain and low environmental sensitivity (the ``ProjectParams`` defaults, except
  that env. sensitivity Low is the neutral level of ``ENV_LAND_FACTOR``). The expert baseline at
  these conditions is the constants themselves, except that the existing loop-ramp rule already
  lowers the Cloverleaf / Trumpet safety index at 100 km/h. A document that omits a condition gets
  the reference value imputed, with a warning — the record still teaches the type-level
  correction, just not the slope of the missing condition.
* **Residuals are multiplicative.** The model learns ``ln(observed / expert baseline)``: cost
  overruns, land-take and capacity deviations are naturally relative, and the log keeps every
  prediction positive.
* **Priors.** ``σ0`` is the prior guess of the per-project scatter around the expert pipeline on
  the log scale (cost 0.20 ≈ ±20 %, in line with the road-project overruns reported by Flyvbjerg,
  Holm & Buhl, 2002; land 0.15; throughput 0.10 — HCM capacities are comparatively well
  calibrated; safety 0.12 — expert score). ``τ`` is the prior sd of a coefficient: a type may be
  off by about ±30 % overall, a condition slope by about ±15 % per unit. ``a0 = 3`` is a weak
  prior on the noise (equivalent to ~6 observations) with ``E[σ²] = σ0²``. With zero records the
  posterior equals the prior, whose mean is zero — the model then reproduces the expert values
  exactly.
* **Interval level** 0.90: a 90 % prediction interval is wide enough to be honest with small
  corpora and narrow enough to be useful as a robustness range.
* **Cross-validation.** Leave-one-out is exact and cheap for small corpora; above 200 observations
  of a criterion a deterministic 10-fold split keeps retraining in milliseconds.
* **Uploads.** Plain-text, Markdown, CSV, JSON / JSONL and (optionally) PDF documents up to 5 MB —
  ample for a project report; larger files are almost certainly scans or archives.

* **Robust likelihood.** The noise is Student-t with ν = 8 rather than Gaussian, so one gross error
  (a unit mistake) is downweighted instead of pulling the whole fit. On clean data the weights stay
  close to 1 and the fit is close to the Gaussian one.

Flyvbjerg, B., Holm, M. S., Buhl, S. (2002). Underestimating costs in public works projects:
    error or lie? Journal of the American Planning Association, 68(3), 279–295.
Lange, K. L., Little, R. J. A., Taylor, J. M. G. (1989). Robust statistical modeling using the t
    distribution. Journal of the American Statistical Association, 84(408), 881–896.
"""

from __future__ import annotations

from typing import Dict, Tuple

from app.data.adjustment_rules import ENV_LAND_FACTOR, TERRAIN_COST_FACTOR

# ---------------------------------------------------------------------------
# Criteria the model predicts (same names as app.data.interchange_data.CRITERIA)
# ---------------------------------------------------------------------------

TARGETS: Tuple[str, ...] = (
    "construction_cost_mln",
    "land_area_hectares",
    "throughput_vph",
    "safety_index",
)

SAFETY_BOUNDS: Tuple[float, float] = (1.0, 10.0)

# ---------------------------------------------------------------------------
# Site conditions
# ---------------------------------------------------------------------------

REFERENCE_CONDITIONS: Dict[str, object] = {
    "aadt": 45_000,          # veh/day
    "num_lanes": 2,          # per direction
    "design_speed": 100,     # km/h
    "terrain": "Flat",
    "env_sensitivity": "Low",
}

TERRAIN_LEVELS: Tuple[str, ...] = tuple(TERRAIN_COST_FACTOR)    # Flat, Rolling, Mountainous
ENV_LEVELS: Tuple[str, ...] = tuple(ENV_LAND_FACTOR)            # Low, Medium, High, Critical

NUM_LANES_RANGE: Tuple[int, int] = (1, 6)
DESIGN_SPEED_RANGE: Tuple[float, float] = (40.0, 140.0)
YEAR_RANGE: Tuple[int, int] = (1900, 2100)

# Speed slope unit: one feature unit = 20 km/h (the step used by the loop-ramp safety rule).
SPEED_FEATURE_STEP = 20.0

# ---------------------------------------------------------------------------
# Prior hyper-parameters of the Normal-Inverse-Gamma regression (log scale)
# ---------------------------------------------------------------------------

PRIOR_SIGMA0: Dict[str, float] = {
    "construction_cost_mln": 0.20,
    "land_area_hectares":    0.15,
    "throughput_vph":        0.10,
    "safety_index":          0.12,
}
PRIOR_TAU_TYPE = 0.30        # prior sd of a per-type intercept
PRIOR_TAU_SLOPE = 0.15       # prior sd of a condition slope
PRIOR_A0 = 3.0               # Inverse-Gamma shape; b0 = σ0² (a0 − 1) so that E[σ²] = σ0²

INTERVAL_LEVEL = 0.90

# Student-t likelihood (outlier resistance). Lange, Little & Taylor (1989) suggest ν = 4; on the
# demo corpus ν = 8 keeps the clean-data accuracy within 0.2 pp of the Gaussian fit while a ×10 unit
# mistake still gets a weight of ≈ 0.05. An observation whose final weight falls below
# OUTLIER_WEIGHT (≈ 5.3 noise scales, ≈ 4.6 sd off the fit; a ×3 error) is reported in its
# document's warnings.
ROBUST_NU = 8.0
ROBUST_MAX_ITER = 100
ROBUST_TOL = 1e-8            # max change of any weight between iterations
OUTLIER_WEIGHT = 0.25

# Cross-validation of the accuracy table.
CV_MIN_OBS = 3               # fewer observations → metrics are null
LOO_MAX_OBS = 200            # above this, deterministic K-fold instead of leave-one-out
CV_FOLDS = 10

# ---------------------------------------------------------------------------
# Value synonyms (keys are lower-case; apostrophes normalised to ')
# ---------------------------------------------------------------------------

INTERCHANGE_TYPE_SYNONYMS: Dict[str, str] = {
    # Cloverleaf
    "cloverleaf": "Cloverleaf",
    "clover leaf": "Cloverleaf",
    "clover-leaf": "Cloverleaf",
    "full cloverleaf": "Cloverleaf",
    "конюшина": "Cloverleaf",
    "конюшинний лист": "Cloverleaf",
    "конюшинка": "Cloverleaf",
    # Turbine
    "turbine": "Turbine",
    "турбіна": "Turbine",
    "турбінна": "Turbine",
    "турбінний": "Turbine",
    # Stack
    "stack": "Stack (4-Level)",
    "stack (4-level)": "Stack (4-Level)",
    "4-level": "Stack (4-Level)",
    "4-level stack": "Stack (4-Level)",
    "four-level": "Stack (4-Level)",
    "four-level stack": "Stack (4-Level)",
    "four level stack": "Stack (4-Level)",
    "чотирирівнева": "Stack (4-Level)",
    "чотирирівневий": "Stack (4-Level)",
    "чотирирівнева розв'язка": "Stack (4-Level)",
    # Diamond
    "diamond": "Diamond",
    "ромб": "Diamond",
    "ромбоподібна": "Diamond",
    "ромбоподібний": "Diamond",
    # SPUI
    "spui": "SPUI",
    "single point": "SPUI",
    "single point interchange": "SPUI",
    "single point urban interchange": "SPUI",
    "single-point urban interchange": "SPUI",
    "одноточкова": "SPUI",
    "одноточковий": "SPUI",
    # DDI
    "ddi": "DDI",
    "diverging diamond": "DDI",
    "diverging diamond interchange": "DDI",
    "розбіжний ромб": "DDI",
    # Trumpet
    "trumpet": "Trumpet",
    "труба": "Trumpet",
    "трубний": "Trumpet",
    # Directional T
    "directional t": "Directional T",
    "directional-t": "Directional T",
    "напрямна т": "Directional T",
    "напрямна t": "Directional T",
    "напрямна-т": "Directional T",
}

TERRAIN_SYNONYMS: Dict[str, str] = {
    "flat": "Flat", "level": "Flat", "рівнинний": "Flat", "рівнина": "Flat",
    "rolling": "Rolling", "hilly": "Rolling", "горбистий": "Rolling",
    "пересічений": "Rolling",
    "mountainous": "Mountainous", "mountain": "Mountainous", "гірський": "Mountainous",
    "гори": "Mountainous",
}

ENV_SYNONYMS: Dict[str, str] = {
    "low": "Low", "низька": "Low", "низький": "Low",
    "medium": "Medium", "moderate": "Medium", "середня": "Medium", "середній": "Medium",
    "помірна": "Medium",
    "high": "High", "висока": "High", "високий": "High",
    "critical": "Critical", "критична": "Critical", "критичний": "Critical",
}

TRUE_WORDS = frozenset({"true", "yes", "y", "1", "так", "t"})
FALSE_WORDS = frozenset({"false", "no", "n", "0", "ні", "f", ""})

# ---------------------------------------------------------------------------
# Field-name synonyms: canonical field → accepted spellings (EN + UK, lower-case).
# Used for "Key: value" lines in text documents and for CSV headers / JSON keys.
# ---------------------------------------------------------------------------

FIELD_SYNONYMS: Dict[str, Tuple[str, ...]] = {
    "interchange_type": (
        "interchange_type", "interchange type", "type", "тип розв'язки", "тип", "тип вузла",
    ),
    "aadt": (
        "aadt", "traffic (aadt)", "інтенсивність", "сдр",
        "середньодобова інтенсивність", "інтенсивність руху",
    ),
    "num_lanes": (
        "num_lanes", "lanes per direction", "lanes", "number of lanes", "кількість смуг",
        "смуг у кожному напрямку", "смуги",
    ),
    "design_speed": ("design_speed", "design speed", "розрахункова швидкість"),
    "terrain": ("terrain", "рельєф"),
    "env_sensitivity": (
        "env_sensitivity", "environmental sensitivity", "env sensitivity", "env. sensitivity",
        "екологічна чутливість",
    ),
    "construction_cost_mln": (
        "construction_cost_mln", "construction cost", "cost", "вартість будівництва", "вартість",
    ),
    "land_area_hectares": (
        "land_area_hectares", "land area", "land take", "right-of-way", "right of way", "площа",
        "площа відведення",
    ),
    "throughput_vph": (
        "throughput_vph", "capacity", "throughput", "пропускна здатність",
    ),
    "safety_index": ("safety_index", "safety index", "індекс безпеки"),
    "name": ("name", "project", "project name", "проєкт", "проект", "назва"),
    "year": ("year", "рік"),
    "country": ("country", "країна"),
    "synthetic": ("synthetic", "синтетичний"),
}

# ---------------------------------------------------------------------------
# Corpus documents
# ---------------------------------------------------------------------------

# file extension → document kind
ALLOWED_EXTENSIONS: Dict[str, str] = {
    ".csv": "csv",
    ".json": "json",
    ".jsonl": "json",
    ".txt": "text",
    ".md": "text",
    ".pdf": "pdf",
}
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
SYNTHETIC_PREFIX = "synthetic_"
