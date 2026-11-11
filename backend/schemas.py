"""Pydantic request/response schemas for the TDSS API."""

from __future__ import annotations

from typing import Annotated, Any, Dict, List, Literal, Optional, Tuple

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


class StudyParams(BaseModel):
    """Design-life inputs of the engineering and economic analyses (engineering_defaults.py)."""

    opening_year: int = Field(2027, ge=2000, le=2100)
    design_years: int = Field(20, ge=1, le=50)
    growth_pct: float = Field(2.0, ge=-5, le=15)
    directional_split: float = Field(55, ge=50, le=100)
    heavy_pct: float = Field(10.0, ge=0, le=60)
    turning_pct: float = Field(25.0, ge=0, le=100)
    discount_pct: float = Field(4.0, ge=0, le=20)
    value_of_time: float = Field(18.0, ge=0, le=500)
    maintenance_pct: float = Field(1.0, ge=0, le=10)


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


class Model3DSegmentSchema(BaseModel):
    id: str
    kind: str                  # mainline | crossroad | ramp
    lanes: int
    width_m: float
    speed_kmh: float
    points: List[List[float]]  # [[x east, y north, z up], ...] in metres, in travel direction


class Model3DResponse(BaseModel):
    name: str
    extent_m: float            # half the side of the square the plan fits in
    level_step_m: float
    levels: int                # the ground level included
    max_height_m: float
    max_grade: float           # steepest gradient, as a fraction
    fill_below_m: float        # decks lower than this stand on fill, higher ones on piers
    segments: List[Model3DSegmentSchema]
    piers: List[List[float]]   # [[x, y, top z, width], ...]


class ContextListResponse(BaseModel):
    contexts: List[str]


# ── Phase 3: GIS site analysis ────────────────────────────────────────────────
# osm_features is real GeoJSON (a FeatureCollection, [lon, lat] coordinate order) so the frontend
# can hand it straight to Leaflet's L.geoJSON(); footprint segments below use plain [lat, lon]
# pairs instead, since they are Leaflet-only internal data, not meant for external GIS interop.


# Leaflet's Web Mercator map ends at ±85.05°, and the UI's radius slider runs 200-1500 m. Each
# request costs an Overpass query on a shared public server, so the radius stays within that range.
# Tags the server classifies OSM ways by (see app.infrastructure.gis.overpass._CLASSIFIERS); a
# browser-fetched way carries only these.
OsmTagKey = Literal["highway", "building", "natural", "waterway", "leisure", "boundary", "landuse"]
LatLon = Tuple[Annotated[float, Field(ge=-90, le=90)], Annotated[float, Field(ge=-180, le=180)]]


class OsmWayInput(BaseModel):
    """One OSM way that the browser fetched from Overpass itself (see ``osm`` below)."""

    id: int
    tags: Dict[OsmTagKey, Annotated[str, Field(max_length=64)]] = Field(max_length=7)
    coords: List[LatLon] = Field(min_length=1, max_length=2000)  # [[lat, lon], ...]


class SiteAnalyseRequest(BaseModel):
    lat: float = Field(ge=-85, le=85)
    lon: float = Field(ge=-180, le=180)
    bearing_lat: Optional[float] = Field(None, ge=-85, le=85)
    bearing_lon: Optional[float] = Field(None, ge=-180, le=180)
    radius_m: float = Field(500.0, ge=100, le=1500)
    # OSM ways the browser fetched from a public Overpass server when this server could not reach
    # one. Used instead of the server's own query for this request only; never cached. The total
    # node count is capped in the route (MAX_CLIENT_OSM_NODES).
    osm: Optional[List[OsmWayInput]] = Field(None, max_length=20_000)


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
    osm: Optional[List[OsmWayInput]] = Field(None, max_length=20_000)  # as in SiteAnalyseRequest


class OverpassQueryResponse(BaseModel):
    """What the browser needs to ask a public Overpass server itself."""

    query: str
    endpoints: List[str]


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


# ── Professional analyses: engineering (traffic and safety) ──────────────────


class EngineeringRequest(BaseModel):
    context: str = Field(max_length=64)
    params: ProjectParams = Field(default_factory=ProjectParams)
    study: StudyParams = Field(default_factory=StudyParams)


class ElementStateSchema(BaseModel):
    id: str
    label: str
    kind: str                 # loop | ramp | weave | merge | signal
    capacity_pcph: float
    volume_pcph: float
    vc: float
    los: str
    delay_s: float
    shared: bool = False      # mainline merge, the same for every alternative


class AlternativeEngineeringSchema(BaseModel):
    name: str
    color: str = ""
    color_dark: str = ""
    feasible: bool = True
    opening: List[ElementStateSchema]
    design: List[ElementStateSchema]
    critical_element: str
    vc_series: List[float]
    mainline_vc_series: List[float]
    delay_vehh: List[float]
    crashes: List[float]
    fi_crashes: List[float]
    year_los_e: Optional[int]
    year_capacity: Optional[int]
    cmf_speed: float
    crashes_total: float
    fi_total: float
    delay_total_vehh: float


class EngineeringResponse(BaseModel):
    context: str
    study: StudyParams
    years: List[int]
    peak_hour_veh: float
    peak_direction_pcph: float
    turning_pcph: float
    lane_capacity_pcph: float
    hv_factor: float
    alternatives: List[AlternativeEngineeringSchema]


# ── Professional analyses: economics and break-even (Phase 2) ────────────────


class AlternativeEconomicsSchema(BaseModel):
    """Present values in M USD over the design life (DOCUMENTATION.md §3.15)."""

    name: str
    color: str = ""
    color_dark: str = ""
    feasible: bool
    construction_mln: float
    pv_maintenance: float
    pv_residual: float
    pv_delay: float
    pv_crash: float
    pv_agency: float
    pv_user: float
    pv_total: float
    cumulative_total: List[float]
    is_base: bool
    incremental_cost: Optional[float]
    benefits: Optional[float]
    npv: Optional[float]
    bcr: Optional[float]
    dominant: bool
    payback_year: Optional[int]


class EconomicsResponse(BaseModel):
    context: str
    study: StudyParams
    years: List[int]
    base: str
    best_lcc: str
    crash_cost_fi: float
    crash_cost_pdo: float
    alternatives: List[AlternativeEconomicsSchema]


class BreakEvenItemSchema(BaseModel):
    alternative: str
    criterion: str
    current: float
    value: Optional[float]           # None: not reachable within ×20 / ÷20 (or the scale's end)
    change_pct: Optional[float]
    kind: Literal["overtake", "hold"]
    new_winner: Optional[str] = None


class BreakEvenMethodSchema(BaseModel):
    method: str
    label: str
    winner: str
    items: List[BreakEvenItemSchema]


class BreakEvenResponse(BaseModel):
    context: str
    alternatives: List[str]
    methods: Dict[str, BreakEvenMethodSchema]
    adjustments: List[AdjustmentNote] = []


# ── Professional analyses: group decision (Phase 3) ──────────────────────────


class StakeholderInput(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    influence: float = Field(1.0, gt=0, le=10)
    weights: WeightsInput


class GroupRequest(EvaluateRequest):
    stakeholders: List[StakeholderInput] = Field(min_length=2, max_length=8)


class StakeholderResultSchema(BaseModel):
    name: str
    influence: float
    weights: Dict[str, float]          # normalised
    ranking: List[str]                 # best first
    utility: Dict[str, float]
    winner: str
    kendall: Optional[float]           # τ against the group ranking


class GroupResponse(BaseModel):
    context: str
    alternatives: List[str]
    criteria: List[str]
    basis: str                         # a method id, or "consensus" for several methods
    group_weights: Dict[str, float]
    group_ranking: List[str]
    group_utility: Dict[str, float]
    group_winner: str
    stakeholders: List[StakeholderResultSchema]
    winner_share: Dict[str, float]     # alternative → influence share of stakeholders it wins for
    adjustments: List[AdjustmentNote] = []
