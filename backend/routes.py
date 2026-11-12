"""API route handlers for TDSS."""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass, replace
from typing import Any

import numpy as np
from fastapi import APIRouter, HTTPException, Query, Response

from app.application.adjustments import apply_project_params
from app.application.dss_engine import DecisionSupportSystem
from app.application.evaluation import (
    MultiMethodEvaluation,
    WeightSelection,
    analyse_robustness,
    run_methods,
    select_weights,
)
from app.application.mcda import METHODS, DecisionMatrix
from app.application.mcda.smaa import ValueUncertainty, WeightUncertainty
from app.application.model3d import build_model
from app.application.prediction import ResidualModel
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
from app.data.interchange_geometry import PIER_MIN_HEIGHT_M
from app.data.mcda_methods import resolve_method_info
from app.data.uncertainty_defaults import DEFAULT_VALUE_UNCERTAINTY
from backend.limits import slot
from backend.model_routes import current_model, require_model_params
from backend.schemas import (
    AdjustmentNote,
    ContextListResponse,
    CriterionSchema,
    CriterionSensitivitySchema,
    EvaluateRequest,
    EvaluateResponse,
    EvaluationResultSchema,
    InterchangeDetailSchema,
    MethodInfoSchema,
    MethodResultSchema,
    MethodScore,
    Model3DResponse,
    Model3DRouteSchema,
    Model3DSegmentSchema,
    RankAgreementSchema,
    RobustnessRequest,
    RobustnessResponse,
    SensitivitySchema,
    SMAAAlternative,
    SMAAMethodSchema,
    ValueRangeInput,
    WeightingInfo,
)

router = APIRouter()

# SMAA is the costliest request (seconds of CPU at the iteration limit); see backend.limits.
_ROBUSTNESS_SLOTS = threading.BoundedSemaphore(2)


@router.get("/contexts", response_model=ContextListResponse)
def list_contexts():
    return ContextListResponse(contexts=list(INTERCHANGE_DATA.keys()))


@dataclass
class _Prepared:
    """Adjusted feasible alternatives, their decision matrix and the resolved weights."""

    locale: str
    alternatives: list
    matrix: DecisionMatrix
    selection: WeightSelection
    weights: dict[str, float]
    notes: list[AdjustmentNote]
    model: ResidualModel | None = None   # set when value_source == "model"


# Model-corrected values keep the precision of the site rules' output (0.01 for cost / land /
# safety, whole veh/h for throughput) — the model is far less precise than that, and the expert
# constants are already this round, so with no records nothing changes.
_THROUGHPUT_DECIMALS = 0
_VALUE_DECIMALS = 2


def _model_raw_values(model: ResidualModel, alt: Any, params: Any) -> dict[str, float]:
    """The expert constants of *alt* × the model's correction e^μ under *params* (rounded)."""
    values = model.correct_values(alt.name, alt.raw_values, params)
    return {
        c: round(v, _THROUGHPUT_DECIMALS if c == "throughput_vph" else _VALUE_DECIMALS)
        for c, v in values.items()
    }


def _model_note(model: ResidualModel) -> AdjustmentNote:
    n, synthetic = model.n_records, model.n_synthetic
    if n == 0:
        message = (
            "Criterion values: the prediction model has no training records yet, so the expert "
            "constants are used unchanged."
        )
    else:
        source = f"{n} project record{'' if n == 1 else 's'}"
        if synthetic == n:
            source += " (all synthetic demo data)"
        elif synthetic:
            source += f" ({synthetic} of them synthetic demo data)"
        message = (
            f"Criterion values: expert constants corrected by the prediction model trained on "
            f"{source}; the site rules and hard constraints are applied to the corrected values."
        )
    return AdjustmentNote(kind="model", message=message)


def _prepare(req: EvaluateRequest, lang: str) -> _Prepared:
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
    model = None
    adjustment_notes: list[AdjustmentNote] = []
    if req.value_source == "model":
        # Replace the constants by constants × e^μ (the model's correction at these conditions)
        # *before* the site rules, so terrain / env. / speed rules, the capacity penalty and the
        # feasibility filter all still apply on top of the learned values.
        require_model_params(req.params)
        model = current_model()
        base_alternatives = [
            replace(alt, raw_values=_model_raw_values(model, alt, req.params))
            for alt in base_alternatives
        ]
        adjustment_notes.append(_model_note(model))
    alternatives, notes = apply_project_params(base_alternatives, req.params)
    adjustment_notes += [AdjustmentNote(kind=n.kind, message=n.message) for n in notes]

    if not alternatives:
        raise HTTPException(
            status_code=422,
            detail=(
                "All alternatives in this context are infeasible under the current budget "
                "and land limits. Increase the budget or land limit and try again."
            ),
        )

    matrix = DecisionMatrix.from_alternatives(alternatives, CRITERIA)
    wr = req.weighting
    try:
        selection = select_weights(
            matrix,
            matrix.weights_vector(norm_w),
            wr.mode,
            ahp_matrix=wr.ahp_matrix,
            subjective=wr.subjective,
            objective=wr.objective,
            alpha=wr.alpha,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    adjustment_notes += [AdjustmentNote(kind=n.kind, message=n.message) for n in selection.notes]
    norm_w = {c.name: float(w) for c, w in zip(CRITERIA, selection.weights, strict=True)}
    return _Prepared(locale, alternatives, matrix, selection, norm_w, adjustment_notes, model)


@router.post("/evaluate", response_model=EvaluateResponse)
def evaluate(req: EvaluateRequest, lang: str = Query(default="en")):
    prep = _prepare(req, lang)
    locale, alternatives, matrix, selection = (
        prep.locale, prep.alternatives, prep.matrix, prep.selection
    )
    norm_w, adjustment_notes = prep.weights, prep.notes

    multi = run_methods(matrix, selection, req.methods)

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
        value_source=req.value_source,
        **_multi_method_fields(multi, locale),
    )


@router.post("/robustness", response_model=RobustnessResponse)
def robustness(req: RobustnessRequest, lang: str = Query(default="en")):
    """SMAA-2 rank acceptability and weight sensitivity for the selected methods."""
    with slot(_ROBUSTNESS_SLOTS):
        return _robustness(req, lang)


def _robustness(req: RobustnessRequest, lang: str) -> RobustnessResponse:
    prep = _prepare(req, lang)
    unknown = set(req.uncertainty.values) - {c.name for c in CRITERIA}
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown criteria: {sorted(unknown)}")

    ranges = {
        name: ValueRangeInput(low=lo, high=hi, distribution=dist)
        for name, (lo, hi, dist) in DEFAULT_VALUE_UNCERTAINTY.items()
    }
    notes = list(prep.notes)
    if prep.model is not None:
        # Defaults from the model: the widest relative prediction interval over the evaluated
        # alternatives. Explicit per-criterion ranges in the request still win, and a criterion
        # without training observations keeps the expert default (its interval is only the prior).
        model_ranges = prep.model.value_ranges(
            [a.name for a in prep.alternatives], req.params
        )
        used = [
            c for c in model_ranges
            if c not in req.uncertainty.values and prep.model.n_obs(c) > 0
        ]
        for c in used:
            low, high = model_ranges[c]
            ranges[c] = ValueRangeInput(low=low, high=high, distribution="triangular")
        if used:
            labels = resolve_criterion_labels("en")
            notes.append(AdjustmentNote(
                kind="model",
                message=(
                    f"Value uncertainty from the prediction model's "
                    f"{prep.model.interval_level * 100:.0f} % prediction intervals "
                    f"(triangular) for: {', '.join(labels.get(c, c) for c in used)}."
                ),
            ))
    ranges.update(req.uncertainty.values)
    u = req.uncertainty
    analysis = analyse_robustness(
        prep.matrix,
        prep.selection.weights,
        req.methods,
        value_uncertainty={
            k: ValueUncertainty(v.low, v.high, v.distribution) for k, v in ranges.items()
        },
        weight_model=WeightUncertainty(u.weight_model, u.concentration),
        iterations=u.iterations,
        seed=u.seed,
        limits={
            "construction_cost_mln": req.params.budget,
            "land_area_hectares": req.params.land_limit,
        },
    )

    names = prep.matrix.alternatives
    crits = prep.matrix.criterion_names

    def label(m: str) -> str:
        return resolve_method_info(m, prep.locale)["label"]

    smaa = {}
    for m, r in analysis.smaa.results.items():
        rows = [
            SMAAAlternative(
                alternative_name=n,
                rank_acceptability=[float(v) for v in r.rank_acceptability[i]],
                holistic_acceptability=float(r.holistic_acceptability[i]),
                confidence=_num(r.confidence[i]),
                central_weights=(
                    None if r.central_weights[i] is None
                    else {c: float(v) for c, v in zip(crits, r.central_weights[i], strict=True)}
                ),
            )
            for i, n in enumerate(names)
        ]
        rows.sort(key=lambda a: (-a.holistic_acceptability, names.index(a.alternative_name)))
        smaa[m] = SMAAMethodSchema(method=m, label=label(m), alternatives=rows)

    def name_of(i: int | None) -> str | None:
        return None if i is None else names[i]

    sensitivity = {}
    for m, sa in analysis.sensitivity.items():
        critical = sa.critical
        sensitivity[m] = SensitivitySchema(
            method=m,
            label=label(m),
            winner=names[sa.winner],
            higher_is_better=sa.higher_is_better,
            critical_criterion=critical.criterion if critical else None,
            critical_change=critical.min_change if critical else None,
            criteria=[
                CriterionSensitivitySchema(
                    criterion=c.criterion,
                    weight=c.weight,
                    lower=c.lower,
                    upper=c.upper,
                    winner_below=name_of(c.winner_below),
                    winner_above=name_of(c.winner_above),
                    min_change=c.min_change,
                    grid=c.grid.tolist(),
                    scores={n: c.scores[:, i].tolist() for i, n in enumerate(names)},
                )
                for c in sa.criteria
            ],
        )

    return RobustnessResponse(
        context=req.context,
        alternatives=list(names),
        colors={n: ALTERNATIVE_COLORS.get(n, "#0f766e") for n in names},
        colors_dark={n: ALTERNATIVE_COLORS_DARK.get(n, "#2dd4bf") for n in names},
        weights=prep.weights,
        iterations=u.iterations,
        seed=u.seed,
        weight_model=u.weight_model,
        concentration=u.concentration,
        value_uncertainty=ranges,
        smaa=smaa,
        exceedance={
            n: {c: float(p[i]) for c, p in analysis.smaa.exceedance.items()}
            for i, n in enumerate(names)
        },
        sensitivity=sensitivity,
        adjustments=notes,
        value_source=req.value_source,
    )


@router.get("/methods", response_model=list[MethodInfoSchema])
def list_methods(lang: str = Query(default="en")):
    locale = lang if lang in ("uk", "en") else "en"
    return [MethodInfoSchema(id=m, **resolve_method_info(m, locale)) for m in METHODS]


# ── Serialisation of engine results ──────────────────────────────────────────

# Method details indexed by criterion rather than by alternative, and alternative × alternative
# matrices (m × m, which must not be mistaken for an m × n table when m == n).
_PER_CRITERION_DETAILS = {"ideal", "anti_ideal"}
_PAIRWISE_DETAILS = {"preference_matrix"}


def _num(x: Any) -> float | None:
    x = float(x)
    return None if math.isnan(x) else x


def _jsonable(x: Any) -> Any:
    if isinstance(x, np.ndarray):
        return [_jsonable(v) for v in x.tolist()]
    if isinstance(x, (bool, np.bool_)):
        return bool(x)
    if isinstance(x, (int, float, np.integer, np.floating)):
        return _num(x)
    if isinstance(x, list):
        return [_jsonable(v) for v in x]
    return x


def _method_details(details: dict[str, Any], matrix: DecisionMatrix) -> dict[str, Any]:
    alts, crits = matrix.alternatives, matrix.criterion_names
    out: dict[str, Any] = {}
    for key, val in details.items():
        if isinstance(val, np.ndarray) and val.ndim == 1:
            labels = crits if key in _PER_CRITERION_DETAILS else alts
            out[key] = {k: _num(v) for k, v in zip(labels, val, strict=True)}
        elif isinstance(val, np.ndarray) and val.ndim == 2 and key not in _PAIRWISE_DETAILS:
            out[key] = {
                a: {c: _num(v) for c, v in zip(crits, row, strict=True)}
                for a, row in zip(alts, val, strict=True)
            }
        else:
            out[key] = _jsonable(val)
    return out


def _weighting_details(details: dict[str, Any], matrix: DecisionMatrix) -> dict[str, Any]:
    crits = matrix.criterion_names
    return {
        key: (
            {c: _num(v) for c, v in zip(crits, val, strict=True)}
            if isinstance(val, np.ndarray) and val.ndim == 1
            else _jsonable(val)
        )
        for key, val in details.items()
    }


def _scores(names: tuple[str, ...], scores, utility, ranks) -> list[MethodScore]:
    rows = [
        MethodScore(alternative_name=n, score=float(s), utility=float(u), rank=int(r))
        for n, s, u, r in zip(names, scores, utility, ranks, strict=True)
    ]
    return sorted(rows, key=lambda r: (r.rank, names.index(r.alternative_name)))


def _multi_method_fields(multi: MultiMethodEvaluation, locale: str) -> dict[str, Any]:
    names = multi.matrix.alternatives
    method_results = {
        m: MethodResultSchema(
            method=m,
            label=resolve_method_info(m, locale)["label"],
            higher_is_better=r.higher_is_better,
            scores=_scores(names, r.scores, r.utility, r.ranks),
            details=_method_details(r.details, multi.matrix),
        )
        for m, r in multi.results.items()
    }

    agreement = None
    if multi.agreement is not None:
        a = multi.agreement
        borda = a.consensus_scores
        span = borda.max() - borda.min()
        utility = np.ones_like(borda) if span == 0 else (borda - borda.min()) / span
        agreement = RankAgreementSchema(
            methods=a.methods,
            spearman=_jsonable(a.spearman),
            kendall=_jsonable(a.kendall),
            consensus=_scores(names, borda, utility, a.consensus_ranks),
            unanimous_winner=a.unanimous_winner,
        )

    return {
        "method_results": method_results,
        "rank_agreement": agreement,
        "weighting": WeightingInfo(
            mode=multi.weights.mode,
            details=_weighting_details(multi.weights.details, multi.matrix),
        ),
    }


@router.get("/interchange/{name}/model3d", response_model=Model3DResponse)
def get_interchange_model3d(name: str, response: Response):
    """The 3-D model of a catalogue alternative: centrelines with heights, and piers."""
    model = build_model(name) if len(name) <= 64 else None
    if model is None:
        raise HTTPException(status_code=404, detail="No 3-D model for this alternative")
    # The model changes with a deploy, and a viewer running on an older model draws it wrong (no
    # lane routes, so no traffic), so browsers must not keep it. Building it is cached here.
    response.headers["Cache-Control"] = "no-store"
    return Model3DResponse(
        name=model.name,
        extent_m=model.extent_m,
        level_step_m=model.level_step_m,
        levels=model.levels,
        max_height_m=model.max_height_m,
        max_grade=model.max_grade,
        fill_below_m=PIER_MIN_HEIGHT_M,
        segments=[
            Model3DSegmentSchema(
                id=s.id, kind=s.kind, lanes=s.lanes, width_m=s.width_m, speed_kmh=s.speed_kmh,
                points=[list(p) for p in s.points],
                left_m=list(s.left_m), right_m=list(s.right_m),
                edge_left=s.edge_left, edge_right=s.edge_right, marks=s.marks,
                open_start=s.open_start, open_end=s.open_end,
            )
            for s in model.segments
        ],
        piers=[[p.x, p.y, p.top_m, p.width_m] for p in model.piers],
        routes=[
            Model3DRouteSchema(
                id=r.id, points=[list(p) for p in r.points], phase_s=r.phase_s,
                open_start=r.open_start, open_end=r.open_end,
            )
            for r in model.routes
        ],
        headway_s=model.headway_s,
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
