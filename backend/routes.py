"""API route handlers for TDSS."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.application.dss_engine import DecisionSupportSystem
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
    ContextListResponse,
    CriterionSchema,
    EvaluateRequest,
    EvaluateResponse,
    EvaluationResultSchema,
    InterchangeDetailSchema,
)

router = APIRouter()


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

    alternatives = get_alternatives_for_context(req.context)
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
    )


@router.get("/interchange/{name}", response_model=InterchangeDetailSchema)
def get_interchange_detail(name: str):
    info = DETAILED_INTERCHANGE_INFO.get(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"No detail for: {name}")

    return InterchangeDetailSchema(
        name=name,
        lat=info.get("lat", 0.0),
        lon=info.get("lon", 0.0),
        example_name=info.get("example_name", ""),
        pros=info.get("pros", []),
        cons=info.get("cons", []),
        engineering_desc=info.get("engineering_desc", ""),
    )
