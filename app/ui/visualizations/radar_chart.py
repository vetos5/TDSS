"""
Radar (spider) chart for interchange comparison.

Axes: Safety, Capacity, Cost (Inverse), Land Use (Inverse), Traffic Flow Speed.
Scores normalized 0–100 for consistent comparison across interchange types.
"""

from __future__ import annotations

from typing import Any, Dict

import plotly.graph_objects as go

from app.application.traffic_engine import TrafficState
from app.domain.models import InterchangeMetrics


def _normalize(x: float, x_min: float, x_max: float, inverse: bool = False) -> float:
    """Map x from [x_min, x_max] to [0, 100]. If inverse, high x -> low score."""
    if x_max <= x_min:
        return 50.0
    t = (x - x_min) / (x_max - x_min)
    t = max(0.0, min(1.0, t))
    if inverse:
        t = 1.0 - t
    return t * 100.0

def compute_radar_scores(
    interchange_type: str,
    metrics: InterchangeMetrics,
    traffic: TrafficState,
) -> Dict[str, float]:
    """
    Return 0–100 scores for Safety, Capacity, Cost (Inverse), Land Use (Inverse), Speed.
    """
    cost = metrics.calculate_cost()
    footprint = metrics.calculate_footprint()
    total_capacity = sum(s.capacity_veh_h for s in traffic.segment_states.values())
    avg_speed = 0.0
    n = len(traffic.segment_states)
    if n:
        avg_speed = sum(s.free_flow_speed_kmh for s in traffic.segment_states.values()) / n

    cost_lo, cost_hi = 1e6, 50e6
    foot_lo, foot_hi = 1.0, 50.0
    cap_lo, cap_hi = 2000, 25000
    speed_lo, speed_hi = 30, 120

    capacity_score = _normalize(total_capacity, cap_lo, cap_hi, inverse=False)
    cost_score = _normalize(cost, cost_lo, cost_hi, inverse=True)
    land_score = _normalize(footprint, foot_lo, foot_hi, inverse=True)
    speed_score = _normalize(avg_speed, speed_lo, speed_hi, inverse=False)

    safety_heuristic = {
        "Cloverleaf": 55,
        "Diverging Diamond (DDI)": 88,
        "Roundabout": 75,
        "SPUI": 72,
        "Turbine": 82,
    }
    safety_score = safety_heuristic.get(interchange_type, 60)

    return {
        "Safety": safety_score,
        "Capacity": capacity_score,
        "Cost (Inverse)": cost_score,
        "Land Use (Inverse)": land_score,
        "Traffic Flow Speed": speed_score,
    }


def build_radar_figure(
    interchange_type: str,
    metrics: InterchangeMetrics,
    traffic: TrafficState,
) -> go.Figure:
    """Build a Plotly radar chart for the given interchange metrics and traffic state."""
    scores = compute_radar_scores(interchange_type, metrics, traffic)
    categories = list(scores.keys())
    values = [scores[k] for k in categories]

    fig = go.Figure(
        data=go.Scatterpolar(
            r=values + [values[0]],
            theta=categories + [categories[0]],
            fill="toself",
            name=interchange_type,
            line=dict(color="rgb(100, 180, 255)"),
            fillcolor="rgba(100, 180, 255, 0.3)",
        )
    )
    fig.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 100], tickfont=dict(color="#E0E0E0")),
            angularaxis=dict(tickfont=dict(color="#E0E0E0")),
            bgcolor="#1E2028",
        ),
        paper_bgcolor="#181A1E",
        font=dict(color="#E0E0E0"),
        title=dict(text="Interchange comparison", font=dict(size=16)),
        showlegend=False,
        height=420,
    )
    return fig
