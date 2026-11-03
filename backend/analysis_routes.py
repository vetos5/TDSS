"""Professional analyses: design-life traffic and safety, life-cycle economics, break-even and
group decisions. The maths lives in app.application; these handlers only translate."""

from __future__ import annotations

import threading

from fastapi import APIRouter, HTTPException, Query

from app.application.adjustments import apply_site_adjustments, filter_feasible
from app.application.economics import appraise
from app.application.engineering import Study, analyse
from app.application.mcda import METHODS
from app.application.mcda.breakeven import analyse_breakeven
from app.data.interchange_data import (
    ALTERNATIVE_COLORS,
    ALTERNATIVE_COLORS_DARK,
    INTERCHANGE_DATA,
    get_alternatives_for_context,
)
from app.data.mcda_methods import resolve_method_info
from backend.limits import slot
from backend.routes import _prepare
from backend.schemas import (
    AlternativeEconomicsSchema,
    AlternativeEngineeringSchema,
    BreakEvenItemSchema,
    BreakEvenMethodSchema,
    BreakEvenResponse,
    EconomicsResponse,
    ElementStateSchema,
    EngineeringRequest,
    EngineeringResponse,
    EvaluateRequest,
)

router = APIRouter()

# Break-even re-runs a method a few hundred times per cell; cap it like the robustness analysis.
_BREAKEVEN_SLOTS = threading.BoundedSemaphore(2)
# Criterion scales with a natural end: the safety index is out of 10.
_VALUE_BOUNDS = {"safety_index": (0.0, 10.0)}


def _locale(lang: str) -> str:
    return lang if lang in ("uk", "en") else "en"


def _site_alternatives(context: str, params):
    """Every alternative of *context* with the site rules applied, and the feasible names."""
    if context not in INTERCHANGE_DATA:
        raise HTTPException(status_code=404, detail=f"Unknown context: {context}")
    adjusted, _ = apply_site_adjustments(get_alternatives_for_context(context), params)
    feasible, _ = filter_feasible(adjusted, params.budget, params.land_limit)
    return adjusted, {a.name for a in feasible}


@router.post("/engineering", response_model=EngineeringResponse)
def engineering(req: EngineeringRequest, lang: str = Query(default="en")):
    """Design-life traffic per element (V/C, LOS, delay) and expected crashes per alternative."""
    adjusted, feasible = _site_alternatives(req.context, req.params)
    result = analyse([a.name for a in adjusted], req.params, Study.of(req.study), _locale(lang))
    return EngineeringResponse(
        context=req.context,
        study=req.study,
        years=result.years,
        peak_hour_veh=result.peak_hour_veh,
        peak_direction_pcph=result.peak_direction_pcph,
        turning_pcph=result.turning_pcph,
        lane_capacity_pcph=result.lane_capacity_pcph,
        hv_factor=result.hv_factor,
        alternatives=[
            AlternativeEngineeringSchema(
                name=a.name,
                color=ALTERNATIVE_COLORS.get(a.name, "#0f766e"),
                color_dark=ALTERNATIVE_COLORS_DARK.get(a.name, "#2dd4bf"),
                feasible=a.name in feasible,
                opening=[ElementStateSchema(**vars(s)) for s in a.opening],
                design=[ElementStateSchema(**vars(s)) for s in a.design],
                critical_element=a.critical_element,
                vc_series=a.vc_series,
                mainline_vc_series=a.mainline_vc_series,
                delay_vehh=a.delay_vehh,
                crashes=a.crashes,
                fi_crashes=a.fi_crashes,
                year_los_e=a.year_los_e,
                year_capacity=a.year_capacity,
                cmf_speed=a.cmf_speed,
                crashes_total=round(a.crashes_total, 2),
                fi_total=round(a.fi_total, 2),
                delay_total_vehh=round(a.delay_total_vehh, 0),
            )
            for a in result.alternatives
        ],
    )


@router.post("/economics", response_model=EconomicsResponse)
def economics(req: EngineeringRequest, lang: str = Query(default="en")):
    """Life-cycle cost, NPV, BCR and payback of each alternative against the do-minimum."""
    adjusted, feasible = _site_alternatives(req.context, req.params)
    study = Study.of(req.study)
    eng = analyse([a.name for a in adjusted], req.params, study, _locale(lang))
    costs = {a.name: a.raw_values["construction_cost_mln"] for a in adjusted}
    result = appraise(costs, eng.alternatives, study, feasible)
    return EconomicsResponse(
        context=req.context,
        study=req.study,
        years=result.years,
        base=result.base,
        best_lcc=result.best_lcc,
        crash_cost_fi=result.crash_cost_fi,
        crash_cost_pdo=result.crash_cost_pdo,
        alternatives=[
            AlternativeEconomicsSchema(
                **vars(a),
                color=ALTERNATIVE_COLORS.get(a.name, "#0f766e"),
                color_dark=ALTERNATIVE_COLORS_DARK.get(a.name, "#2dd4bf"),
            )
            for a in result.alternatives
        ],
    )


@router.post("/breakeven", response_model=BreakEvenResponse)
def breakeven(req: EvaluateRequest, lang: str = Query(default="en")):
    """Criterion values at which each challenger would win, and each winner's margin."""
    with slot(_BREAKEVEN_SLOTS):
        prep = _prepare(req, lang)
        out = {}
        for m in req.methods:
            res = analyse_breakeven(prep.matrix, prep.selection.weights, METHODS[m], _VALUE_BOUNDS)
            out[m] = BreakEvenMethodSchema(
                method=m,
                label=resolve_method_info(m, prep.locale)["label"],
                winner=res.winner,
                items=[BreakEvenItemSchema(**vars(i)) for i in res.items],
            )
        return BreakEvenResponse(
            context=req.context,
            alternatives=list(prep.matrix.alternatives),
            methods=out,
            adjustments=prep.notes,
        )
