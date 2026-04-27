"""Pydantic request/response schemas for the TDSS API."""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


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


class EvaluateRequest(BaseModel):
    context: str
    weights: WeightsInput
    params: ProjectParams


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


class EvaluateResponse(BaseModel):
    context: str
    results: List[EvaluationResultSchema]
    criteria: List[CriterionSchema]
    criterion_labels: Dict[str, str]
    normalised_weights: Dict[str, float]
    adjustments: List[AdjustmentNote] = []


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
