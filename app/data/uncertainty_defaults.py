"""
Default uncertainty of the expert criterion values, as multiplicative ranges [low, high] around
the point estimate (triangular distribution with its mode at the estimate).

These are modelling assumptions for sensitivity studies, not measured statistics; the user can
override every range in the UI / API.

* Construction cost is right-skewed: road projects overrun far more often than they underrun
  (Flyvbjerg, Holm & Buhl, 2002, report an average overrun of about 20 % for road projects).
* Land take varies with final alignment and mitigation requirements.
* Throughput varies with driver population, heavy-vehicle share and ramp-terminal control.
* The safety index is an expert score and carries judgement uncertainty.

Flyvbjerg, B., Holm, M. S., Buhl, S. (2002). Underestimating costs in public works projects:
    error or lie? Journal of the American Planning Association, 68(3), 279–295.
"""

from __future__ import annotations

from typing import Dict, Tuple

# criterion → (low, high, distribution)
DEFAULT_VALUE_UNCERTAINTY: Dict[str, Tuple[float, float, str]] = {
    "construction_cost_mln": (0.90, 1.50, "triangular"),
    "land_area_hectares":    (0.90, 1.20, "triangular"),
    "throughput_vph":        (0.85, 1.15, "triangular"),
    "safety_index":          (0.85, 1.15, "triangular"),
}

DEFAULT_ITERATIONS = 1000
DEFAULT_WEIGHT_CONCENTRATION = 100.0
