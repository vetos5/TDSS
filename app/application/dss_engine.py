"""
Decision Support System — Weighted Sum Model (WSM) for transport
interchange evaluation.

Academic context (MCDA)
-----------------------
Multi-Criteria Decision Analysis (MCDA) provides a structured framework
for evaluating competing design alternatives against multiple, potentially
conflicting objectives.  The Weighted Sum Model (WSM) — also called the
Simple Additive Weighting (SAW) method — is the most widely used MCDA
technique for single-decision-maker problems with commensurable, quantitative
criteria (Fishburn, 1967; Triantaphyllou, 2000).

WSM Formula
-----------
The composite priority score for alternative *i* is:

    S_i = Σ_j ( w_j · x̄_ij )

where:
    S_i    — composite score for alternative i  (dimensionless, ∈ [0, 1])
    w_j    — normalised weight for criterion j   (decision-maker preference)
    x̄_ij  — Min-Max normalised value of criterion j for alternative i

Min-Max Normalisation
---------------------
Raw criterion values are mapped to [0, 1] while preserving the direction
of preference:

    MAXIMIZE (higher raw = better):
        x̄_ij = (x_ij − min_j) / (max_j − min_j)

    MINIMIZE (lower raw = better):
        x̄_ij = (max_j − x_ij) / (max_j − min_j)

Edge case: if max_j = min_j (all alternatives identical for this criterion)
the normalised score is set to 0.5 (neutral) to avoid division-by-zero.

References
----------
Fishburn, P. C. (1967). Additive utilities with incomplete product sets.
    Operations Research, 15(3), 537–542.
Triantaphyllou, E. (2000). Multi-Criteria Decision Making Methods: A
    Comparative Study. Kluwer Academic Publishers, Dordrecht.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional


# Type alias for criterion optimisation direction.
CriterionDirection = Literal["maximize", "minimize"]


@dataclass
class Criterion:
    """
    A single evaluation criterion with its optimisation direction.

    Attributes
    ----------
    name :
        Unique identifier used as the dictionary key throughout the engine.
    direction :
        ``"maximize"`` — higher raw value is preferred (e.g. safety score).
        ``"minimize"`` — lower raw value is preferred (e.g. construction cost).
    weight :
        Default relative importance weight.  The engine always re-normalises
        all weights before computing scores, so only *ratios* between weights
        matter.
    unit :
        Physical unit string for display purposes (e.g. ``"€"``, ``"m²"``).
    """

    name: str
    direction: CriterionDirection
    weight: float = 0.25
    unit: str = ""


@dataclass
class Alternative:
    """
    A transport interchange design alternative being evaluated.

    Attributes
    ----------
    name :
        Display label (e.g. ``"Cloverleaf"``, ``"Roundabout"``).
    raw_values :
        Mapping of ``criterion_name → raw numeric value`` for this
        alternative.  Values are typically populated by combining dynamic
        SVG-geometry metrics with hardcoded expert estimates.
    description :
        Optional free-text description for the UI.
    """

    name: str
    raw_values: Dict[str, float] = field(default_factory=dict)
    description: str = ""


@dataclass
class EvaluationResult:
    """
    Full WSM evaluation outcome for a single alternative.

    Attributes
    ----------
    alternative_name :
        Mirrors ``Alternative.name``.
    raw_values :
        Original unscaled criterion values.
    normalised_values :
        Min-Max normalised values (direction-aware), one per criterion.
    weighted_scores :
        Element-wise product ``w_j · x̄_ij`` for each criterion.
    total_score :
        Sum of weighted_scores — the WSM composite score S_i ∈ [0, 1].
    rank :
        Ordinal rank among all evaluated alternatives (1 = best).
    """

    alternative_name: str
    raw_values: Dict[str, float]
    normalised_values: Dict[str, float]
    weighted_scores: Dict[str, float]
    total_score: float
    rank: int = 0


class DecisionSupportSystem:
    """
    Weighted Sum Model (WSM) engine for transport interchange MCDA.

    Typical workflow
    ----------------
    1. Instantiate with a list of ``Criterion`` objects (names + directions).
    2. Build ``Alternative`` objects and populate their ``raw_values`` dicts
       with both dynamically-computed SVG metrics and expert-preset values.
    3. Call ``evaluate(alternatives, weights)`` to obtain a ranked list of
       ``EvaluationResult`` objects.

    Example
    -------
    >>> criteria = [
    ...     Criterion("Cost",       direction="minimize", unit="€"),
    ...     Criterion("Area",       direction="minimize", unit="m²"),
    ...     Criterion("Throughput", direction="maximize", unit="PCU/h"),
    ...     Criterion("Safety",     direction="maximize", unit="/10"),
    ... ]
    >>> dss = DecisionSupportSystem(criteria)
    >>> results = dss.evaluate(alternatives, weights={"Cost": 0.4, "Area": 0.2,
    ...                                               "Throughput": 0.2, "Safety": 0.2})
    >>> for r in results:
    ...     print(r.rank, r.alternative_name, r.total_score)
    """

    def __init__(self, criteria: List[Criterion]) -> None:
        self.criteria: List[Criterion] = list(criteria)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        alternatives: List[Alternative],
        weights: Optional[Dict[str, float]] = None,
    ) -> List[EvaluationResult]:
        """
        Run the WSM evaluation and return results sorted by descending score.

        Parameters
        ----------
        alternatives :
            List of ``Alternative`` objects with ``raw_values`` populated.
        weights :
            Optional dict mapping ``criterion_name → weight``.  If provided,
            these values override the weights stored in each ``Criterion``.
            Weights are **automatically re-normalised** so that their sum
            equals 1.0 — the caller may pass raw integer preference scores
            (e.g. 1, 2, 3, 4) and the engine will normalise them correctly.

        Returns
        -------
        List[EvaluationResult]
            Sorted by descending ``total_score``; the best alternative has
            ``rank = 1``.

        Raises
        ------
        ValueError
            If the sum of effective weights is zero or negative.
        """
        if not alternatives or not self.criteria:
            return []

        # Collect effective weights (override dict takes priority)
        effective_weights: Dict[str, float] = {
            c.name: (weights[c.name] if weights and c.name in weights else c.weight)
            for c in self.criteria
        }

        # Re-normalise weights so they always sum to 1.0.
        # This makes the engine tolerant of user rounding errors and allows
        # arbitrary "importance score" inputs rather than requiring exact fractions.
        total_w = sum(effective_weights.values())
        if total_w <= 0:
            raise ValueError(
                "Sum of criterion weights must be positive. "
                f"Got: {effective_weights}"
            )
        norm_w: Dict[str, float] = {k: v / total_w for k, v in effective_weights.items()}

        # Compute per-criterion min/max across all alternatives.
        # These anchor values define the normalisation scale.
        col_min: Dict[str, float] = {}
        col_max: Dict[str, float] = {}
        for c in self.criteria:
            vals = [alt.raw_values.get(c.name, 0.0) for alt in alternatives]
            col_min[c.name] = min(vals)
            col_max[c.name] = max(vals)

        results: List[EvaluationResult] = []
        for alt in alternatives:
            normalised: Dict[str, float] = {}
            weighted: Dict[str, float] = {}

            for c in self.criteria:
                raw = alt.raw_values.get(c.name, 0.0)
                lo, hi = col_min[c.name], col_max[c.name]
                span = hi - lo

                if span == 0.0:
                    # All alternatives are identical on this criterion.
                    # Assign a neutral mid-point score to avoid any bias.
                    x_norm = 0.5
                elif c.direction == "maximize":
                    # Higher raw value → normalised score closer to 1.
                    x_norm = (raw - lo) / span
                else:
                    # MINIMIZE: invert so lower raw value → score closer to 1.
                    x_norm = (hi - raw) / span

                normalised[c.name] = round(x_norm, 4)
                weighted[c.name] = round(x_norm * norm_w[c.name], 4)

            total_score = round(sum(weighted.values()), 4)
            results.append(
                EvaluationResult(
                    alternative_name=alt.name,
                    raw_values=dict(alt.raw_values),
                    normalised_values=normalised,
                    weighted_scores=weighted,
                    total_score=total_score,
                )
            )

        # Sort descending — rank 1 is the highest-scoring (best) alternative.
        results.sort(key=lambda r: r.total_score, reverse=True)
        for rank, res in enumerate(results, start=1):
            res.rank = rank

        return results

    # ------------------------------------------------------------------
    # Convenience helper
    # ------------------------------------------------------------------

    def criterion_names(self) -> List[str]:
        """Return criterion names in definition order."""
        return [c.name for c in self.criteria]
