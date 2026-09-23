"""
Site-condition adjustment factors applied to raw criterion values before evaluation.

Expert constants only — the rules that use them live in ``app.application.adjustments``.
"""

from __future__ import annotations

from typing import Dict

# Construction-cost multiplier by terrain class (FHWA cost factors).
TERRAIN_COST_FACTOR: Dict[str, float] = {
    "Flat":        1.00,
    "Rolling":     1.25,
    "Mountainous": 1.70,
}

# Effective land-area multiplier by environmental sensitivity (mitigation / setback overhead).
ENV_LAND_FACTOR: Dict[str, float] = {
    "Low":      1.00,
    "Medium":   1.10,
    "High":     1.30,
    "Critical": 1.60,
}

# Loop-ramp designs lose safety above this design speed.
LOOP_RAMP_ALTERNATIVES = frozenset({"Cloverleaf", "Trumpet"})
LOOP_RAMP_MAX_SAFE_SPEED = 80          # km/h
SPEED_PENALTY_PER_20KMH = 0.10         # safety fraction lost per 20 km/h over the threshold
MAX_SPEED_PENALTY = 0.40
MIN_SAFETY_INDEX = 1.0

# Throughput penalty when peak-hour demand exceeds rated capacity.
CAPACITY_PENALTY_SLOPE = 0.5           # penalty per unit of over-capacity ratio
MAX_CAPACITY_PENALTY = 0.40
