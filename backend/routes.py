"""API route handlers for TDSS."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Response

from app.application.adjustments import apply_project_params
from app.application.dss_engine import DecisionSupportSystem
from app.data.interchange_data import (
    ALTERNATIVE_COLORS,
    ALTERNATIVE_COLORS_DARK,
    BLUEPRINT_PATHS,
    CRITERIA,
    INTERCHANGE_DATA,
    get_alternatives_for_context,
    resolve_alternative_description,
    resolve_criterion_labels,
    resolve_interchange_detail,
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


@router.get("/contexts", response_model=ContextListResponse)
def list_contexts():
    return ContextListResponse(contexts=list(INTERCHANGE_DATA.keys()))


@router.post("/evaluate", response_model=EvaluateResponse)
def evaluate(req: EvaluateRequest, lang: str = Query(default="en")):
    if req.context not in INTERCHANGE_DATA:
        raise HTTPException(status_code=404, detail=f"Unknown context: {req.context}")

    locale = lang if lang in ("uk", "en") else "en"

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
    alternatives, notes = apply_project_params(base_alternatives, req.params)
    adjustment_notes = [AdjustmentNote(kind=n.kind, message=n.message) for n in notes]

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

    criterion_labels = resolve_criterion_labels(locale)

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
                description=resolve_alternative_description(r.alternative_name, locale),
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
        criterion_labels=criterion_labels,
        normalised_weights=norm_w,
        adjustments=adjustment_notes,
    )


@router.get("/interchange/{name}", response_model=InterchangeDetailSchema)
def get_interchange_detail(name: str, response: Response, lang: str = Query(default="en")):
    locale = lang if lang in ("uk", "en") else "en"
    info = resolve_interchange_detail(name, locale)
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
