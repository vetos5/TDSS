"""
Project-parameter adjustment rules.

Modifies raw criterion values of each alternative for site conditions (terrain, environmental
sensitivity, design speed, traffic demand) and removes alternatives that break the hard budget
and land constraints. Every applied rule yields a human-readable ``AdjustmentNote``.
See DOCUMENTATION.md §3.4–3.5 for the formulas.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Protocol, Tuple

from app.application.dss_engine import Alternative
from app.data.adjustment_rules import (
    CAPACITY_PENALTY_SLOPE,
    ENV_LAND_FACTOR,
    LOOP_RAMP_ALTERNATIVES,
    LOOP_RAMP_MAX_SAFE_SPEED,
    MAX_CAPACITY_PENALTY,
    MAX_SPEED_PENALTY,
    MIN_SAFETY_INDEX,
    SPEED_PENALTY_PER_20KMH,
    TERRAIN_COST_FACTOR,
)


class ProjectParameters(Protocol):
    """Project parameters the rules read; ``backend.schemas.ProjectParams`` satisfies it."""

    design_speed: int
    aadt: int
    peak_factor: int
    budget: float
    land_limit: float
    terrain: str
    env_sensitivity: str


@dataclass
class AdjustmentNote:
    """A human-readable note describing one applied rule.

    ``kind`` is one of: terrain, env_sensitivity, design_speed, traffic_demand, feasibility.
    """

    kind: str
    message: str


def apply_site_adjustments(
    alternatives: List[Alternative],
    params: ProjectParameters,
) -> Tuple[List[Alternative], List[AdjustmentNote]]:
    """Return adjusted copies of *alternatives* and the notes for every rule that fired."""
    terrain_factor = TERRAIN_COST_FACTOR.get(params.terrain, 1.0)
    env_factor = ENV_LAND_FACTOR.get(params.env_sensitivity, 1.0)
    peak_hour_demand = params.aadt * (params.peak_factor / 100.0)

    notes: List[AdjustmentNote] = []
    adjusted: List[Alternative] = []

    if terrain_factor != 1.0:
        notes.append(AdjustmentNote(
            kind="terrain",
            message=(
                f"Terrain '{params.terrain}': construction costs scaled ×{terrain_factor:.2f} "
                f"(FHWA cost factor)."
            ),
        ))

    if env_factor != 1.0:
        notes.append(AdjustmentNote(
            kind="env_sensitivity",
            message=(
                f"Env. sensitivity '{params.env_sensitivity}': effective land area scaled "
                f"×{env_factor:.2f} to reflect mitigation / permitting overhead."
            ),
        ))

    speed_penalty_applied = False
    capacity_warnings: List[str] = []

    for alt in alternatives:
        new_values = dict(alt.raw_values)

        if terrain_factor != 1.0:
            new_values["construction_cost_mln"] = round(
                alt.raw_values["construction_cost_mln"] * terrain_factor, 2
            )

        if env_factor != 1.0:
            new_values["land_area_hectares"] = round(
                alt.raw_values["land_area_hectares"] * env_factor, 2
            )

        if alt.name in LOOP_RAMP_ALTERNATIVES and params.design_speed > LOOP_RAMP_MAX_SAFE_SPEED:
            excess_increments = (params.design_speed - LOOP_RAMP_MAX_SAFE_SPEED) / 20.0
            penalty_frac = min(excess_increments * SPEED_PENALTY_PER_20KMH, MAX_SPEED_PENALTY)
            new_values["safety_index"] = round(
                max(alt.raw_values["safety_index"] * (1 - penalty_frac), MIN_SAFETY_INDEX), 2
            )
            if not speed_penalty_applied:
                notes.append(AdjustmentNote(
                    kind="design_speed",
                    message=(
                        f"Design speed {params.design_speed} km/h exceeds loop-ramp threshold "
                        f"({LOOP_RAMP_MAX_SAFE_SPEED} km/h): safety index reduced by up to "
                        f"{penalty_frac * 100:.0f} % for loop-ramp alternatives "
                        f"({', '.join(sorted(LOOP_RAMP_ALTERNATIVES))})."
                    ),
                ))
                speed_penalty_applied = True

        throughput = alt.raw_values["throughput_vph"]
        if peak_hour_demand > throughput:
            over_ratio = peak_hour_demand / throughput
            capacity_penalty = min(
                (over_ratio - 1.0) * CAPACITY_PENALTY_SLOPE, MAX_CAPACITY_PENALTY
            )
            new_values["throughput_vph"] = round(throughput * (1 - capacity_penalty), 0)
            capacity_warnings.append(
                f"{alt.name} (capacity {int(throughput):,} vph < demand "
                f"{int(peak_hour_demand):,} vph, {(over_ratio - 1.0) * 100:.0f} % over)"
            )

        adjusted.append(Alternative(
            name=alt.name,
            raw_values=new_values,
            description=alt.description,
        ))

    if capacity_warnings:
        notes.append(AdjustmentNote(
            kind="traffic_demand",
            message=(
                f"Peak-hour demand {int(peak_hour_demand):,} vph "
                f"(AADT {params.aadt:,} × {params.peak_factor}%) exceeds rated capacity for: "
                + "; ".join(capacity_warnings)
                + ". Effective throughput score reduced proportionally."
            ),
        ))

    return adjusted, notes


def filter_feasible(
    alternatives: List[Alternative],
    budget: float,
    land_limit: float,
) -> Tuple[List[Alternative], List[AdjustmentNote]]:
    """Drop alternatives whose cost exceeds *budget* (M USD) or land exceeds *land_limit* (ha)."""
    feasible: List[Alternative] = []
    infeasible: List[str] = []

    for alt in alternatives:
        cost = alt.raw_values["construction_cost_mln"]
        land = alt.raw_values["land_area_hectares"]
        reasons = []
        if cost > budget:
            reasons.append(f"cost ${cost:.1f}M > budget ${budget:.0f}M")
        if land > land_limit:
            reasons.append(f"land {land:.1f} ha > limit {land_limit:.0f} ha")
        if reasons:
            infeasible.append(f"{alt.name} ({', '.join(reasons)})")
        else:
            feasible.append(alt)

    notes: List[AdjustmentNote] = []
    if infeasible:
        notes.append(AdjustmentNote(
            kind="feasibility",
            message=(
                "Hard constraints exceeded — the following alternatives are marked infeasible "
                "and excluded from ranking: " + "; ".join(infeasible) + "."
            ),
        ))
    return feasible, notes


def apply_project_params(
    alternatives: List[Alternative],
    params: ProjectParameters,
) -> Tuple[List[Alternative], List[AdjustmentNote]]:
    """Site adjustments followed by the hard feasibility filter."""
    adjusted, notes = apply_site_adjustments(alternatives, params)
    feasible, feasibility_notes = filter_feasible(adjusted, params.budget, params.land_limit)
    return feasible, notes + feasibility_notes
