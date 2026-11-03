"""Professional analyses: design-life traffic and safety, life-cycle economics, break-even and
group decisions. The maths lives in app.application; these handlers only translate."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.application.adjustments import apply_site_adjustments, filter_feasible
from app.application.engineering import Study, analyse
from app.data.interchange_data import (
    ALTERNATIVE_COLORS,
    ALTERNATIVE_COLORS_DARK,
    INTERCHANGE_DATA,
    get_alternatives_for_context,
)
from backend.schemas import (
    AlternativeEngineeringSchema,
    ElementStateSchema,
    EngineeringRequest,
    EngineeringResponse,
)

router = APIRouter()


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
