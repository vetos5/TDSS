"""
High-fidelity "Engineering View" renderer using PyDeck (Deck.gl / WebGL).

Produces a layered map with:
  1. Asphalt base layer — dark road surface at true lane width.
  2. Traffic-flow overlay — colour-coded by BPR stress level.
  3. Conflict markers — warning circles at geometric intersection points.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import pydeck as pdk

from app.application.traffic_engine import TrafficState, stress_to_rgba
from app.domain.geometry import RoadNetwork


# ---------------------------------------------------------------------------
# Colour / style constants
# ---------------------------------------------------------------------------

ASPHALT_COLOUR = [44, 44, 44, 240]        # #2C2C2C near-opaque
LANE_MARKING_COLOUR = [200, 200, 200, 80]  # faint white dashes
CONFLICT_COLOUR = [255, 200, 0, 220]       # warning yellow
BACKGROUND_COLOUR = [24, 26, 30]           # dark canvas

METRES_TO_PIXELS_SCALE = 1.0  # 1:1 for metre-based coordinate system


def _centreline_to_path(coords: List[Tuple[float, float]]) -> List[List[float]]:
    """Convert (x, y) tuples to [[x, y]] for pydeck."""
    return [[c[0], c[1]] for c in coords]


# ---------------------------------------------------------------------------
# Layer builders
# ---------------------------------------------------------------------------

def build_asphalt_layer(
    network: RoadNetwork,
    steps: int = 200,
) -> pdk.Layer:
    """
    Layer 1 — the physical road surface.
    Each segment is drawn at its full paved width in dark asphalt grey.
    """
    data = []
    for seg in network.segments:
        coords = seg.generate_centreline(steps)
        data.append(
            {
                "path": _centreline_to_path(coords),
                "width": seg.road_width(),
                "colour": ASPHALT_COLOUR,
            }
        )
    return pdk.Layer(
        "PathLayer",
        data=data,
        get_path="path",
        get_width="width",
        get_color="colour",
        width_scale=1,
        width_min_pixels=4,
        width_units="'meters'",
        rounded=True,
        billboard=False,
    )


def build_traffic_layer(
    network: RoadNetwork,
    traffic: TrafficState,
    steps: int = 200,
) -> pdk.Layer:
    """
    Layer 2 — traffic-flow overlay.
    Slightly narrower than the asphalt, coloured by V/C stress.
    """
    data = []
    for seg in network.segments:
        coords = seg.generate_centreline(steps)
        st = traffic.segment_states.get(seg.id)
        colour = list(stress_to_rgba(st.vc_ratio)) if st else [0, 255, 0, 180]
        overlay_width = seg.road_width() * 0.7
        data.append(
            {
                "path": _centreline_to_path(coords),
                "width": overlay_width,
                "colour": colour,
            }
        )
    return pdk.Layer(
        "PathLayer",
        data=data,
        get_path="path",
        get_width="width",
        get_color="colour",
        width_scale=1,
        width_min_pixels=2,
        width_units="'meters'",
        rounded=True,
        billboard=False,
    )


def build_conflict_layer(
    network: RoadNetwork,
    steps: int = 200,
) -> pdk.Layer:
    """
    Layer 3 — conflict / intersection markers.
    Small warning circles at detected geometric intersections.
    """
    points = network.find_intersections(steps)
    data = [{"position": [p[0], p[1]], "radius": 5} for p in points]
    if not data:
        data = [{"position": [0, 0], "radius": 0}]
    return pdk.Layer(
        "ScatterplotLayer",
        data=data,
        get_position="position",
        get_radius="radius",
        get_fill_color=CONFLICT_COLOUR,
        opacity=0.9,
        stroked=True,
        get_line_color=[255, 255, 255, 200],
        line_width_min_pixels=1,
    )


# ---------------------------------------------------------------------------
# Composite deck builder
# ---------------------------------------------------------------------------

def build_engineering_view(
    network: RoadNetwork,
    traffic: TrafficState,
    steps: int = 200,
    view_center: Tuple[float, float] | None = None,
    zoom: float = 14,
) -> pdk.Deck:
    """
    Assemble the full layered engineering view as a pydeck.Deck object
    ready for rendering in Streamlit via `st.pydeck_chart`.
    """
    if view_center is None:
        all_pts = []
        for seg in network.segments:
            all_pts.extend(seg.generate_centreline(steps))
        if all_pts:
            cx = sum(p[0] for p in all_pts) / len(all_pts)
            cy = sum(p[1] for p in all_pts) / len(all_pts)
            view_center = (cx, cy)
        else:
            view_center = (0.0, 0.0)

    view_state = pdk.ViewState(
        longitude=view_center[0],
        latitude=view_center[1],
        zoom=zoom,
        pitch=0,
        bearing=0,
    )

    layers = [
        build_asphalt_layer(network, steps),
        build_traffic_layer(network, traffic, steps),
        build_conflict_layer(network, steps),
    ]

    return pdk.Deck(
        layers=layers,
        initial_view_state=view_state,
        map_style="mapbox://styles/mapbox/dark-v11",
    )
