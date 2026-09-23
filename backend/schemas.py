"""Pydantic request/response schemas for the TDSS API."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class CriterionSchema(BaseModel):
    name: str
    direction: str
    weight: float
    unit: str


class WeightsInput(BaseModel):
    construction_cost_mln: float = Field(0.30, ge=0, le=1)
    land_area_hectares: float = Field(0.20, ge=0, le=1)
    throughput_vph: float = Field(0.25, ge=0, le=1)
    safety_index: float = Field(0.25, ge=0, le=1)


class ProjectParams(BaseModel):
    design_speed: int = 100
    aadt: int = 45000
    peak_factor: int = 10
    num_lanes: int = 2
    budget: float = 100.0
    land_limit: float = 30.0
    terrain: str = "Flat"
    env_sensitivity: str = "Medium"


MethodId = Literal["wsm", "topsis", "ahp", "promethee", "vikor"]
WeightingMode = Literal["manual", "entropy", "critic", "ahp", "combined"]


class WeightingInput(BaseModel):
    """How criterion weights are obtained.

    manual   — the slider weights in ``EvaluateRequest.weights``
    entropy  — Shannon entropy of the (feasible, adjusted) decision matrix
    critic   — CRITIC contrast/correlation weights
    ahp      — principal eigenvector of ``ahp_matrix``
    combined — alpha · subjective + (1 − alpha) · objective
    """

    mode: WeightingMode = "manual"
    ahp_matrix: Optional[List[List[float]]] = Field(
        None, description="4×4 pairwise comparison matrix in criteria order (Saaty 1/9…9)"
    )
    subjective: Literal["manual", "ahp"] = "manual"
    objective: Literal["entropy", "critic"] = "entropy"
    alpha: float = Field(0.5, ge=0, le=1)


class EvaluateRequest(BaseModel):
    context: str
    weights: WeightsInput
    params: ProjectParams
    methods: List[MethodId] = Field(default_factory=lambda: ["wsm"], min_length=1)
    weighting: WeightingInput = Field(default_factory=WeightingInput)

    @field_validator("methods")
    @classmethod
    def _unique_methods(cls, v: List[str]) -> List[str]:
        return list(dict.fromkeys(v))


class AdjustmentNote(BaseModel):
    """A single human-readable note describing a parameter-driven adjustment."""
    kind: str   # one of: terrain, env_sensitivity, design_speed, traffic_demand, feasibility
    message: str


class EvaluationResultSchema(BaseModel):
    alternative_name: str
    raw_values: Dict[str, float]
    normalised_values: Dict[str, float]
    weighted_scores: Dict[str, float]
    total_score: float
    rank: int
    description: str = ""
    color: str = ""
    color_dark: str = ""
    blueprint_path: str = ""


class MethodScore(BaseModel):
    alternative_name: str
    score: float
    utility: float = Field(
        description="Score rescaled to [0, 1], 1 = best, comparable across methods"
    )
    rank: int


class MethodResultSchema(BaseModel):
    method: str
    label: str
    higher_is_better: bool
    scores: List[MethodScore]            # sorted by rank
    details: Dict[str, Any] = {}


class RankAgreementSchema(BaseModel):
    methods: List[str]
    spearman: List[List[Optional[float]]]
    kendall: List[List[Optional[float]]]
    consensus: List[MethodScore]         # Borda count over all methods, sorted by rank
    unanimous_winner: bool


class WeightingInfo(BaseModel):
    mode: str
    details: Dict[str, Any] = {}


class MethodInfoSchema(BaseModel):
    id: str
    label: str
    description: str


class EvaluateResponse(BaseModel):
    context: str
    results: List[EvaluationResultSchema]
    criteria: List[CriterionSchema]
    criterion_labels: Dict[str, str]
    normalised_weights: Dict[str, float]
    adjustments: List[AdjustmentNote] = []
    method_results: Dict[str, MethodResultSchema] = {}
    rank_agreement: Optional[RankAgreementSchema] = None
    weighting: Optional[WeightingInfo] = None


class InterchangeDetailSchema(BaseModel):
    name: str
    lat: float = 0.0
    lon: float = 0.0
    example_name: str = ""
    pros: List[str] = []
    cons: List[str] = []
    engineering_desc: str = ""


class ContextListResponse(BaseModel):
    contexts: List[str]
