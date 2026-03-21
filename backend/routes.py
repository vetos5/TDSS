"""API route handlers for TDSS."""

from __future__ import annotations

from typing import Dict, List

from fastapi import APIRouter, HTTPException, Response

from app.application.dss_engine import Alternative, DecisionSupportSystem
from app.data.interchange_data import (
    ALTERNATIVE_COLORS,
    ALTERNATIVE_COLORS_DARK,
    ALTERNATIVE_DESCRIPTIONS,
    BLUEPRINT_PATHS,
    CRITERIA,
    CRITERION_LABELS,
    DETAILED_INTERCHANGE_INFO,
    INTERCHANGE_DATA,
    get_alternatives_for_context,
)

from backend.schemas import (
    AdjustmentNote,
    ContextListResponse,
    CriterionSchema,
    EvaluateRequest,
    EvaluateResponse,
    EvaluationResultSchema,
    InterchangeDetailSchema,
)

router = APIRouter()

# ---------------------------------------------------------------------------
# Terrain cost multipliers (FHWA cost factor guidance)
# Flat → baseline; Rolling → +25 %; Mountainous → +70 %
# ---------------------------------------------------------------------------
_TERRAIN_COST_FACTOR: Dict[str, float] = {
    "Flat":        1.00,
    "Rolling":     1.25,
    "Mountainous": 1.70,
}

# ---------------------------------------------------------------------------
# Environmental sensitivity → land-area effective penalty multiplier.
# Low → baseline; Medium → +10 %; High → +30 %; Critical → +60 %
# Rationale: sensitive areas inflate the *effective* cost of land consumption
# (mitigation, compensation, permitting) so we scale the criterion value
# upward before normalisation, making land-hungry alternatives look worse.
# ---------------------------------------------------------------------------
_ENV_LAND_FACTOR: Dict[str, float] = {
    "Low":      1.00,
    "Medium":   1.10,
    "High":     1.30,
    "Critical": 1.60,
}

# ---------------------------------------------------------------------------
# Design-speed safety penalty.
# Loop-ramp interchanges (Cloverleaf, Trumpet) have geometric design speeds
# of 40–55 km/h.  When the project design speed exceeds this threshold, their
# safety index is penalised because the speed differential at merge/diverge
# points increases crash risk (AASHTO HSM, 2022; PIARC, 2019).
# ---------------------------------------------------------------------------
_LOOP_RAMP_ALTERNATIVES = {"Cloverleaf", "Trumpet"}
_LOOP_RAMP_MAX_SAFE_SPEED = 80  # km/h — above this threshold, apply penalty

# Penalty magnitude: subtract this fraction of the safety_index per 20 km/h
# increment above the threshold (capped at a 40 % reduction).
_SPEED_PENALTY_PER_20KMH = 0.10


def _apply_project_params(
    alternatives: List[Alternative],
    params,
) -> tuple[List[Alternative], List[AdjustmentNote]]:
    """
    Return a *new* list of Alternative objects whose raw_values have been
    adjusted to reflect the project parameters, plus a list of human-readable
    notes describing every adjustment that was made.

    The original Alternative objects from the data layer are never mutated.
    """
    terrain        = params.terrain
    env_sens       = params.env_sensitivity
    design_speed   = params.design_speed
    aadt           = params.aadt
    peak_factor    = params.peak_factor   # percentage of daily traffic in peak hour
    budget         = params.budget
    land_limit     = params.land_limit

    terrain_factor = _TERRAIN_COST_FACTOR.get(terrain, 1.0)
    env_factor     = _ENV_LAND_FACTOR.get(env_sens, 1.0)

    # Peak-hour demand volume (vehicles per hour)
    peak_hour_demand = aadt * (peak_factor / 100.0)

    notes: List[AdjustmentNote] = []
    adjusted: List[Alternative] = []

    # --- Global notes (parameter-level, not alternative-specific) -----------
    if terrain_factor != 1.0:
        notes.append(AdjustmentNote(
            kind="terrain",
            message=(
                f"Terrain '{terrain}': construction costs scaled ×{terrain_factor:.2f} "
                f"(FHWA cost factor)."
            ),
        ))

    if env_factor != 1.0:
        notes.append(AdjustmentNote(
            kind="env_sensitivity",
            message=(
                f"Env. sensitivity '{env_sens}': effective land area scaled ×{env_factor:.2f} "
                f"to reflect mitigation / permitting overhead."
            ),
        ))

    speed_penalty_applied = False
    capacity_warnings: List[str] = []

    for alt in alternatives:
        new_values = dict(alt.raw_values)

        # 1. Terrain → construction cost
        if terrain_factor != 1.0:
            new_values["construction_cost_mln"] = round(
                alt.raw_values["construction_cost_mln"] * terrain_factor, 2
            )

        # 2. Environmental sensitivity → effective land area
        if env_factor != 1.0:
            new_values["land_area_hectares"] = round(
                alt.raw_values["land_area_hectares"] * env_factor, 2
            )

        # 3. Design speed → safety penalty for loop-ramp alternatives
        if alt.name in _LOOP_RAMP_ALTERNATIVES and design_speed > _LOOP_RAMP_MAX_SAFE_SPEED:
            excess_increments = (design_speed - _LOOP_RAMP_MAX_SAFE_SPEED) / 20.0
            raw_penalty = excess_increments * _SPEED_PENALTY_PER_20KMH
            penalty_frac = min(raw_penalty, 0.40)  # cap at 40 %
            original_safety = alt.raw_values["safety_index"]
            new_values["safety_index"] = round(
                max(original_safety * (1 - penalty_frac), 1.0), 2
            )
            if not speed_penalty_applied:
                notes.append(AdjustmentNote(
                    kind="design_speed",
                    message=(
                        f"Design speed {design_speed} km/h exceeds loop-ramp threshold "
                        f"({_LOOP_RAMP_MAX_SAFE_SPEED} km/h): safety index reduced by up to "
                        f"{penalty_frac * 100:.0f} % for loop-ramp alternatives "
                        f"({', '.join(sorted(_LOOP_RAMP_ALTERNATIVES))})."
                    ),
                ))
                speed_penalty_applied = True

        # 4. Traffic demand → throughput capacity check
        throughput = alt.raw_values["throughput_vph"]
        if peak_hour_demand > throughput:
            over_ratio = peak_hour_demand / throughput
            # Scale down throughput score: the alternative is over capacity,
            # so its effective throughput value is capped at rated capacity
            # and we apply an additional 10 % penalty per 10 % over-capacity.
            over_pct = (over_ratio - 1.0) * 100
            capacity_penalty = min((over_ratio - 1.0) * 0.5, 0.40)
            new_values["throughput_vph"] = round(
                throughput * (1 - capacity_penalty), 0
            )
            capacity_warnings.append(
                f"{alt.name} (capacity {int(throughput):,} vph < demand "
                f"{int(peak_hour_demand):,} vph, {over_pct:.0f} % over)"
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
                f"(AADT {aadt:,} × {peak_factor}%) exceeds rated capacity for: "
                + "; ".join(capacity_warnings)
                + ". Effective throughput score reduced proportionally."
            ),
        ))

    # --- Budget / land-limit feasibility note (informational only) ----------
    infeasible = []
    for alt in adjusted:
        over_budget = alt.raw_values["construction_cost_mln"] > budget
        over_land   = alt.raw_values["land_area_hectares"] > land_limit
        if over_budget or over_land:
            reasons = []
            if over_budget:
                reasons.append(
                    f"cost ${alt.raw_values['construction_cost_mln']:.1f}M > budget ${budget:.0f}M"
                )
            if over_land:
                reasons.append(
                    f"land {alt.raw_values['land_area_hectares']:.1f} ha > limit {land_limit:.0f} ha"
                )
            infeasible.append(f"{alt.name} ({', '.join(reasons)})")

    if infeasible:
        notes.append(AdjustmentNote(
            kind="feasibility",
            message=(
                "Hard constraints exceeded — the following alternatives are marked infeasible "
                "and excluded from ranking: " + "; ".join(infeasible) + "."
            ),
        ))
        # Remove infeasible alternatives from the evaluation set
        infeasible_names = {a.name for a in adjusted
                            if a.raw_values["construction_cost_mln"] > budget
                            or a.raw_values["land_area_hectares"] > land_limit}
        adjusted = [a for a in adjusted if a.name not in infeasible_names]

    return adjusted, notes


@router.get("/contexts", response_model=ContextListResponse)
def list_contexts():
    return ContextListResponse(contexts=list(INTERCHANGE_DATA.keys()))


@router.post("/evaluate", response_model=EvaluateResponse)
def evaluate(req: EvaluateRequest):
    if req.context not in INTERCHANGE_DATA:
        raise HTTPException(status_code=404, detail=f"Unknown context: {req.context}")

    weights = {
        "construction_cost_mln": req.weights.construction_cost_mln,
        "land_area_hectares": req.weights.land_area_hectares,
        "throughput_vph": req.weights.throughput_vph,
        "safety_index": req.weights.safety_index,
    }

    total_w = sum(weights.values())
    if total_w <= 0:
        norm_w = {k: 0.25 for k in weights}
    else:
        norm_w = {k: v / total_w for k, v in weights.items()}

    base_alternatives = get_alternatives_for_context(req.context)

    # Apply all project-parameter adjustments before evaluation
    alternatives, adjustment_notes = _apply_project_params(base_alternatives, req.params)

    if not alternatives:
        raise HTTPException(
            status_code=422,
            detail=(
                "All alternatives in this context are infeasible under the current budget "
                "and land limits. Increase the budget or land limit and try again."
            ),
        )

    dss = DecisionSupportSystem(CRITERIA)
    results = dss.evaluate(alternatives, weights=norm_w)

    result_schemas = []
    for r in results:
        result_schemas.append(
            EvaluationResultSchema(
                alternative_name=r.alternative_name,
                raw_values=r.raw_values,
                normalised_values=r.normalised_values,
                weighted_scores=r.weighted_scores,
                total_score=r.total_score,
                rank=r.rank,
                description=ALTERNATIVE_DESCRIPTIONS.get(r.alternative_name, ""),
                color=ALTERNATIVE_COLORS.get(r.alternative_name, "#0f766e"),
                color_dark=ALTERNATIVE_COLORS_DARK.get(r.alternative_name, "#2dd4bf"),
                blueprint_path=BLUEPRINT_PATHS.get(r.alternative_name, ""),
            )
        )

    criteria_schemas = [
        CriterionSchema(name=c.name, direction=c.direction, weight=c.weight, unit=c.unit)
        for c in CRITERIA
    ]

    return EvaluateResponse(
        context=req.context,
        results=result_schemas,
        criteria=criteria_schemas,
        criterion_labels=CRITERION_LABELS,
        normalised_weights=norm_w,
        adjustments=adjustment_notes,
    )


@router.get("/interchange/{name}", response_model=InterchangeDetailSchema)
def get_interchange_detail(name: str, response: Response):
    info = DETAILED_INTERCHANGE_INFO.get(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"No detail for: {name}")

    response.headers["Cache-Control"] = "no-store"

    return InterchangeDetailSchema(
        name=name,
        lat=info.get("lat", 0.0),
        lon=info.get("lon", 0.0),
        example_name=info.get("example_name", ""),
        pros=info.get("pros", []),
        cons=info.get("cons", []),
        engineering_desc=info.get("engineering_desc", ""),
    )
