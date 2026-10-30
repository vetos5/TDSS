"""
Generate the SYNTHETIC demo corpus ``corpus/documents/synthetic_precedents.csv``.

These rows are not real projects. They exist so the prediction model has something to learn
before real project documents are added, and so the tests can check that it recovers known
effects. Each observed value is

    observed = expert_baseline(type, conditions) · exp(true effect + N(0, σ0_c))

with the hidden "true" effects in ``TRUE_EFFECTS`` (on the model's own feature scale) and σ0_c the
prior noise level of the criterion. The baseline is the real ``expert_baseline``, so the data stay
consistent with the expert constants and adjustment rules. Deterministic: numpy
``default_rng(2026)``.

Run from the repository root:

    python -m scripts.make_synthetic_corpus
"""

from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

from app.application.prediction import (
    FEATURE_NAMES,
    INTERCHANGE_TYPES,
    Conditions,
    expert_baseline,
    features,
)
from app.data.prediction_defaults import (
    ENV_LEVELS,
    PRIOR_SIGMA0,
    SAFETY_BOUNDS,
    TARGETS,
    TERRAIN_LEVELS,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "corpus" / "documents" / "synthetic_precedents.csv"
SEED = 2026
N_RECORDS = 60

# criterion → feature → coefficient on ln(observed / baseline)
TRUE_EFFECTS: Dict[str, Dict[str, float]] = {
    "construction_cost_mln": {
        "lanes": 0.12, "log_aadt": 0.10, "type:Turbine": 0.20, "type:DDI": -0.10,
    },
    "land_area_hectares": {"lanes": 0.08},
    "throughput_vph": {"lanes": 0.22},
    "safety_index": {"speed": -0.05},
}

COLUMNS = [
    "name", "interchange_type", "year", "country",
    "aadt", "num_lanes", "design_speed", "terrain", "env_sensitivity",
    *TARGETS,
    "synthetic",
]
COUNTRIES = ("Ukraine", "Poland", "Germany", "Netherlands", "Spain", "USA", "Canada")
SPEEDS = (60, 70, 80, 90, 100, 110, 120, 130)
DECIMALS = {
    "construction_cost_mln": 2, "land_area_hectares": 2, "throughput_vph": 0, "safety_index": 2,
}
OMIT_PROBABILITY = 0.15


def generate_rows(n: int, rng: np.random.Generator) -> List[Dict[str, Any]]:
    """*n* synthetic precedent rows (canonical field names); types cycle through all eight."""
    rows: List[Dict[str, Any]] = []
    for i in range(n):
        interchange_type = INTERCHANGE_TYPES[i % len(INTERCHANGE_TYPES)]
        cond = Conditions(
            aadt=float(round(math.exp(rng.uniform(math.log(15_000), math.log(120_000))), -2)),
            num_lanes=int(rng.integers(1, 5)),
            design_speed=float(rng.choice(SPEEDS)),
            terrain=str(rng.choice(TERRAIN_LEVELS, p=[0.5, 0.3, 0.2])),
            env_sensitivity=str(rng.choice(ENV_LEVELS, p=[0.35, 0.3, 0.25, 0.1])),
        )
        x = dict(zip(FEATURE_NAMES, features(interchange_type, cond), strict=True))
        baseline = expert_baseline(interchange_type, cond)
        noise = rng.normal(0.0, [PRIOR_SIGMA0[c] for c in TARGETS])
        omit = rng.random(len(TARGETS)) < OMIT_PROBABILITY
        if omit.all():
            omit[0] = False

        row: Dict[str, Any] = {
            "name": f"Synthetic precedent {i + 1:03d} — {interchange_type}",
            "interchange_type": interchange_type,
            "year": int(rng.integers(2006, 2025)),
            "country": str(rng.choice(COUNTRIES)),
            "aadt": int(cond.aadt),
            "num_lanes": cond.num_lanes,
            "design_speed": int(cond.design_speed),
            "terrain": cond.terrain,
            "env_sensitivity": cond.env_sensitivity,
            "synthetic": "true",
        }
        for k, criterion in enumerate(TARGETS):
            effect = sum(coef * x[f] for f, coef in TRUE_EFFECTS[criterion].items())
            value = baseline[criterion] * math.exp(effect + noise[k])
            if criterion == "safety_index":
                value = min(max(value, SAFETY_BOUNDS[0]), SAFETY_BOUNDS[1])
            decimals = DECIMALS[criterion]
            rounded = round(value, decimals)
            row[criterion] = "" if omit[k] else (int(rounded) if decimals == 0 else rounded)
        rows.append(row)
    return rows


def main() -> None:
    rows = generate_rows(N_RECORDS, np.random.default_rng(SEED))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} synthetic records to {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
