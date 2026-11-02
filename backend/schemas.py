"""Pydantic request/response schemas for the TDSS API."""

from __future__ import annotations

from typing import Annotated, Any, Dict, List, Literal, Optional

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


# The bounds keep public requests to values the engine and the model are built for (the UI's
# ranges are narrower still); an unbounded int such as 10**400 would otherwise overflow in floats.
# Budget and land limit only need to stay finite: 1e9 is the code's own "no limit".
class ProjectParams(BaseModel):
    design_speed: int = Field(100, ge=20, le=200)
    aadt: int = Field(45000, ge=0, le=1_000_000)
    peak_factor: int = Field(10, ge=0, le=100)
    num_lanes: int = Field(2, ge=1, le=10)
    budget: float = Field(100.0, ge=0, le=1e9)
    land_limit: float = Field(30.0, ge=0, le=1e9)
    terrain: str = Field("Flat", max_length=32)
    env_sensitivity: str = Field("Medium", max_length=32)


MethodId = Literal["wsm", "topsis", "ahp", "promethee", "vikor"]
WeightingMode = Literal["manual", "entropy", "critic", "ahp", "combined"]
# expert — the fixed expert constants; model — the constants corrected by the document-trained
# prediction model (the site rules, capacity penalty and feasibility filter run afterwards).
ValueSource = Literal["expert", "model"]


class WeightingInput(BaseModel):
    """How criterion weights are obtained.

    manual   — the slider weights in ``EvaluateRequest.weights``
    entropy  — Shannon entropy of the (feasible, adjusted) decision matrix
    critic   — CRITIC contrast/correlation weights
    ahp      — principal eigenvector of ``ahp_matrix``
    combined — alpha · subjective + (1 − alpha) · objective
    """

    mode: WeightingMode = "manual"
    # The shape is bounded in the schema so an oversized matrix fails before per-item validation.
    ahp_matrix: Optional[
        Annotated[List[Annotated[List[float], Field(max_length=4)]], Field(max_length=4)]
    ] = Field(None, description="4×4 pairwise comparison matrix in criteria order (Saaty 1/9…9)")
    subjective: Literal["manual", "ahp"] = "manual"
    objective: Literal["entropy", "critic"] = "entropy"
    alpha: float = Field(0.5, ge=0, le=1)


class EvaluateRequest(BaseModel):
    context: str = Field(max_length=64)
    weights: WeightsInput
    params: ProjectParams
    methods: List[MethodId] = Field(default_factory=lambda: ["wsm"], min_length=1, max_length=5)
    weighting: WeightingInput = Field(default_factory=WeightingInput)
    value_source: ValueSource = "expert"

    @field_validator("methods")
    @classmethod
    def _unique_methods(cls, v: List[str]) -> List[str]:
        return list(dict.fromkeys(v))


class AdjustmentNote(BaseModel):
    """A single human-readable note describing a parameter-driven adjustment."""
    kind: str   # terrain, env_sensitivity, design_speed, traffic_demand, feasibility, weighting,
    #             model
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
    value_source: str = "expert"


class ValueRangeInput(BaseModel):
    """Multiplicative uncertainty range: true value ∈ [low·x, high·x]."""

    low: float = Field(gt=0, le=1)
    high: float = Field(ge=1, le=10)
    distribution: Literal["triangular", "uniform"] = "triangular"


class UncertaintyInput(BaseModel):
    # 5000 is the UI's maximum; one SMAA iteration costs every method 1 + 3 runs.
    iterations: int = Field(1000, ge=100, le=5000)
    seed: int = Field(42, ge=0, le=2**32 - 1)
    weight_model: Literal["fixed", "perturbed", "uniform"] = "perturbed"
    concentration: float = Field(100.0, gt=0, le=10000)
    values: Dict[str, ValueRangeInput] = Field(
        default_factory=dict, max_length=4,
        description="Per-criterion overrides of the default ranges",
    )


class RobustnessRequest(EvaluateRequest):
    methods: List[MethodId] = Field(
        default_factory=lambda: ["wsm", "topsis", "ahp", "promethee", "vikor"],
        min_length=1, max_length=5,
    )
    uncertainty: UncertaintyInput = Field(default_factory=UncertaintyInput)


class SMAAAlternative(BaseModel):
    alternative_name: str
    rank_acceptability: List[float]          # index r = P(rank r + 1)
    holistic_acceptability: float
    confidence: Optional[float]              # None if never ranked first
    central_weights: Optional[Dict[str, float]]


class SMAAMethodSchema(BaseModel):
    method: str
    label: str
    alternatives: List[SMAAAlternative]      # sorted by holistic acceptability, best first


class CriterionSensitivitySchema(BaseModel):
    criterion: str
    weight: float
    lower: Optional[float]                   # winner changes below this weight (None: never)
    upper: Optional[float]                   # winner changes above this weight (None: never)
    winner_below: Optional[str]
    winner_above: Optional[str]
    min_change: Optional[float]
    grid: List[float]
    scores: Dict[str, List[float]]           # alternative → method score along the grid


class SensitivitySchema(BaseModel):
    method: str
    label: str
    winner: str
    higher_is_better: bool
    critical_criterion: Optional[str]
    critical_change: Optional[float]
    criteria: List[CriterionSensitivitySchema]


class RobustnessResponse(BaseModel):
    context: str
    alternatives: List[str]
    colors: Dict[str, str]
    colors_dark: Dict[str, str]
    weights: Dict[str, float]
    iterations: int
    seed: int
    weight_model: str
    concentration: float
    value_uncertainty: Dict[str, ValueRangeInput]
    smaa: Dict[str, SMAAMethodSchema]
    exceedance: Dict[str, Dict[str, float]]  # alternative → {criterion: P(value > limit)}
    sensitivity: Dict[str, SensitivitySchema]
    adjustments: List[AdjustmentNote] = []
    value_source: str = "expert"


# ── Prediction model (document-trained criterion values) ─────────────────────
# Criterion keys of the dicts below are the four CRITERIA names.


class ModelDocumentSchema(BaseModel):
    name: str
    kind: Literal["csv", "json", "text", "pdf"]
    synthetic: bool
    records: int
    extractor: Literal["table", "rules", "llm", "none"]
    warnings: List[str]
    size_bytes: int


class ModelCriterionSchema(BaseModel):
    """Out-of-sample accuracy of one criterion (metrics null below 3 observations)."""

    n_obs: int
    noise_sd: float
    loo_mape_expert: Optional[float]
    loo_mape_model: Optional[float]
    coverage90: Optional[float]


class ModelCoefficientSchema(BaseModel):
    feature: str
    mean: float      # posterior mean of the log-scale coefficient
    sd: float


class ModelStatus(BaseModel):
    trained_at: Optional[str]
    train_ms: float
    revision: int                 # changes on every refit; increases over time
    n_records: int
    n_synthetic: int
    documents: List[ModelDocumentSchema]
    criteria: Dict[str, ModelCriterionSchema]
    coefficients: Dict[str, List[ModelCoefficientSchema]]
    interval_level: float
    llm_available: bool
    pdf_available: bool
    editing_enabled: bool = False  # uploads, deletes and retrains are on (TDSS_ADMIN_TOKEN is set)


class PredictRequest(BaseModel):
    context: str = Field(max_length=64)
    params: ProjectParams = Field(default_factory=ProjectParams)


class PredictedValueSchema(BaseModel):
    expert: float       # expert pipeline under the request's conditions
    predicted: float    # model point prediction (posterior median)
    low: float          # prediction interval at ``interval_level``
    high: float


class PredictedAlternativeSchema(BaseModel):
    name: str
    values: Dict[str, PredictedValueSchema]


class PredictResponse(BaseModel):
    context: str
    n_records: int
    interval_level: float
    alternatives: List[PredictedAlternativeSchema]


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


# ── Phase 3: GIS site analysis ────────────────────────────────────────────────
# osm_features is real GeoJSON (a FeatureCollection, [lon, lat] coordinate order) so the frontend
# can hand it straight to Leaflet's L.geoJSON(); footprint segments below use plain [lat, lon]
# pairs instead, since they are Leaflet-only internal data, not meant for external GIS interop.


# Leaflet's Web Mercator map ends at ±85.05°, and the UI's radius slider runs 200-1500 m. Each
# request costs an Overpass query on a shared public server, so the radius stays within that range.
class SiteAnalyseRequest(BaseModel):
    lat: float = Field(ge=-85, le=85)
    lon: float = Field(ge=-180, le=180)
    bearing_lat: Optional[float] = Field(None, ge=-85, le=85)
    bearing_lon: Optional[float] = Field(None, ge=-180, le=180)
    radius_m: float = Field(500.0, ge=100, le=1500)


class RoadCorridorSchema(BaseModel):
    bearing_deg: float
    rank: int
    way_count: int


class SiteAnalyseResponse(BaseModel):
    context: str
    context_confident: bool
    corridors: List[RoadCorridorSchema]
    terrain: str
    max_grade_pct: Optional[float]
    env_sensitivity: str
    nearest_water_m: Optional[float]
    residential_share: float
    land_limit_ha: float
    building_count: int
    building_area_m2: float
    water_area_m2: float
    notes: List[str]
    radius_m: float
    osm_features: Dict[str, Any]  # GeoJSON FeatureCollection, for direct display on the map


class FootprintRequest(BaseModel):
    alternative_name: str = Field(max_length=64)
    lat: float = Field(ge=-85, le=85)
    lon: float = Field(ge=-180, le=180)
    bearing_lat: Optional[float] = Field(None, ge=-85, le=85)
    bearing_lon: Optional[float] = Field(None, ge=-180, le=180)
    radius_m: float = Field(500.0, ge=100, le=1500)
    demolition_cost_per_sqm: Optional[float] = Field(None, gt=0, le=100_000)


class FootprintSegmentSchema(BaseModel):
    id: str
    width_m: float
    kind: str = "road"  # mainline | crossroad | ramp | road
    coords: List[List[float]]  # [[lat, lon], ...]


class RightOfWaySchema(BaseModel):
    buildings_affected: int
    demolished_area_m2: float
    estimated_cost_usd: float


class FootprintResponse(BaseModel):
    available: bool
    alternative_name: str
    message: Optional[str] = None
    segments: List[FootprintSegmentSchema] = []
    right_of_way: Optional[RightOfWaySchema] = None
