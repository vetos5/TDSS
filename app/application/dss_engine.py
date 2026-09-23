"""
Decision Support System — Weighted Sum Model (WSM) for transport
interchange evaluation.

Architectural Role (Decoupled Architecture)
--------------------------------------------
This module is the *pure Logic Layer*.  It knows nothing about SVG files,
geometric parsers, databases, or UI frameworks.  It receives plain Python
data structures and returns plain Python data structures.  This isolation
makes the MCDA engine independently testable and reusable across any
front-end or data source.

    DATA  → app.data.interchange_data   (expert constants, no I/O)
    LOGIC → app.application.dss_engine  (THIS FILE — pure maths only)
    VIEW  → backend/ + frontend/         (API and Vue UI, no calculations)

Since v5 the arithmetic is delegated to ``app.application.mcda.methods.wsm``;
this class is kept as the stable WSM interface used by the API and legacy UI.

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

import numpy as np

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
        alternative.  In the decoupled architecture these values come
        exclusively from the expert data layer (``app.data``), not from
        any geometric parser or SVG file.
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
    2. Build ``Alternative`` objects whose ``raw_values`` dicts are populated
       by the data layer (``app.data.interchange_data``) — not by any parser.
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

        # The maths lives in the multi-method package; this class keeps the original
        # 4-decimal rounding and ordering contract. Imported here to avoid an import cycle
        # (mcda.matrix uses the dataclasses defined in this module).
        from app.application.mcda import DecisionMatrix
        from app.application.mcda.methods import wsm

        matrix = DecisionMatrix.from_alternatives(alternatives, self.criteria)
        w = np.array([norm_w[c.name] for c in self.criteria])
        details = wsm.run(matrix, w).details

        results: List[EvaluationResult] = []
        for i, alt in enumerate(alternatives):
            normalised = {
                c.name: round(float(details["normalised"][i, j]), 4)
                for j, c in enumerate(self.criteria)
            }
            weighted = {
                c.name: round(float(details["weighted"][i, j]), 4)
                for j, c in enumerate(self.criteria)
            }
            results.append(
                EvaluationResult(
                    alternative_name=alt.name,
                    raw_values=dict(alt.raw_values),
                    normalised_values=normalised,
                    weighted_scores=weighted,
                    total_score=round(sum(weighted.values()), 4),
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
