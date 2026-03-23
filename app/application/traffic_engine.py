"""
Macroscopic traffic-physics engine.

Implements the **BPR (Bureau of Public Roads) link performance function** to
translate demand volumes into travel-time delays and a normalised stress index
suitable for colour-mapping.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from pydantic import BaseModel, Field

from app.domain.geometry import RoadNetwork, RoadSegment


def bpr_travel_time(
    free_flow_time: float,
    volume: float,
    capacity: float,
    alpha: float = 0.15,
    beta: float = 4.0,
) -> float:
    """
    BPR link performance function.

        t = t_0 * [1 + α * (V/C)^β]

    Returns the congested travel time for the link.
    """
    if capacity <= 0:
        return free_flow_time * 100.0
    vc_ratio = volume / capacity
    return free_flow_time * (1.0 + alpha * (vc_ratio ** beta))


def stress_level(volume: float, capacity: float) -> float:
    """
    Normalised stress index = V / C.

    - 0.0 – 0.5  : free flow
    - 0.5 – 0.85 : moderate
    - 0.85 – 1.0 : approaching capacity
    - > 1.0      : oversaturated / gridlock
    """
    if capacity <= 0:
        return 999.0
    return volume / capacity


def los_grade(vc: float) -> str:
    """Highway Capacity Manual Level-of-Service letter grade."""
    if vc <= 0.35:
        return "A"
    if vc <= 0.54:
        return "B"
    if vc <= 0.77:
        return "C"
    if vc <= 0.93:
        return "D"
    if vc <= 1.0:
        return "E"
    return "F"


def stress_to_rgba(vc: float) -> Tuple[int, int, int, int]:
    """
    Map V/C ratio to an RGBA colour for the traffic heatmap layer.

    Gradient:  green -> yellow -> red -> purple
    """
    a = 200
    if vc <= 0.0:
        return (0, 255, 0, a)
    elif vc <= 0.5:
        t = vc / 0.5
        return (int(255 * t), 255, 0, a)
    elif vc <= 0.85:
        t = (vc - 0.5) / 0.35
        return (255, int(255 * (1 - t)), 0, a)
    elif vc <= 1.0:
        t = (vc - 0.85) / 0.15
        r = int(255 - (255 - 128) * t)
        b = int(128 * t)
        return (r, 0, b, a)
    else:
        return (128, 0, 128, a)
class SegmentTrafficState(BaseModel):
    segment_id: str
    volume_veh_h: float = Field(ge=0, description="Demand volume (veh/h)")
    capacity_veh_h: float = Field(gt=0)
    free_flow_speed_kmh: float = Field(gt=0)
    length_km: float = Field(gt=0)

    @property
    def free_flow_time_min(self) -> float:
        return (self.length_km / self.free_flow_speed_kmh) * 60.0

    @property
    def vc_ratio(self) -> float:
        return stress_level(self.volume_veh_h, self.capacity_veh_h)

    @property
    def congested_time_min(self) -> float:
        return bpr_travel_time(self.free_flow_time_min, self.volume_veh_h, self.capacity_veh_h)

    @property
    def delay_min(self) -> float:
        return self.congested_time_min - self.free_flow_time_min

    @property
    def los(self) -> str:
        return los_grade(self.vc_ratio)

    @property
    def colour_rgba(self) -> Tuple[int, int, int, int]:
        return stress_to_rgba(self.vc_ratio)
class TrafficState(BaseModel):
    """Aggregated traffic state for an entire road network."""

    segment_states: Dict[str, SegmentTrafficState] = Field(default_factory=dict)

    @classmethod
    def from_network(
        cls,
        network: RoadNetwork,
        volumes: Dict[str, float],
    ) -> "TrafficState":
        """
        Build a full traffic state from a network definition and a mapping of
        segment_id -> demand volume (veh/h).
        """
        states: Dict[str, SegmentTrafficState] = {}
        for seg in network.segments:
            line = seg.as_shapely_line()
            length_km = line.length / 1000.0 if line.length > 0 else 0.001
            vol = volumes.get(seg.id, 0.0)
            states[seg.id] = SegmentTrafficState(
                segment_id=seg.id,
                volume_veh_h=vol,
                capacity_veh_h=seg.capacity_veh_per_hour(),
                free_flow_speed_kmh=seg.speed_limit_kmh,
                length_km=length_km,
            )
        return cls(segment_states=states)

    def summary_table(self) -> List[Dict]:
        """Return a list of dicts suitable for rendering as a Streamlit table."""
        rows = []
        for sid, st in self.segment_states.items():
            rows.append(
                {
                    "Segment": sid,
                    "Volume (veh/h)": int(st.volume_veh_h),
                    "Capacity (veh/h)": int(st.capacity_veh_h),
                    "V/C": round(st.vc_ratio, 2),
                    "LOS": st.los,
                    "Free-flow (min)": round(st.free_flow_time_min, 2),
                    "Travel time (min)": round(st.congested_time_min, 2),
                    "Delay (min)": round(st.delay_min, 2),
                }
            )
        return rows
