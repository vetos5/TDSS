"""
TDSS — Transport Interchange Decision Support System
=====================================================
Streamlit dashboard with engineering-grade parametric visualisation.

Run:
    streamlit run app/ui/main.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the project root is on sys.path so that `app.*` imports resolve
# regardless of how Streamlit is launched.
_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import streamlit as st
import pandas as pd

from app.application.traffic_engine import TrafficState
from app.infrastructure.generators import (
    CloverleafGenerator,
    DDIGenerator,
    RoundaboutGenerator,
)
from app.ui.visualizations.cad_renderer import build_engineering_view

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="TDSS — Transport Interchange DSS",
    page_icon="🛣️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Custom CSS for CAD-like dark theme
# ---------------------------------------------------------------------------

st.markdown(
    """
    <style>
    .stApp {
        background-color: #181A1E;
    }
    section[data-testid="stSidebar"] {
        background-color: #1E2028;
    }
    h1, h2, h3, .stMarkdown p, .stMarkdown li, label {
        color: #E0E0E0 !important;
    }
    .stMetric label { color: #A0A0A0 !important; }
    .stMetric [data-testid="stMetricValue"] { color: #FFFFFF !important; }
    .stDataFrame { background-color: #23252B; }
    div[data-testid="stDecoration"] { display: none; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Sidebar — Engineering Parameters
# ---------------------------------------------------------------------------

st.sidebar.title("⚙️ Engineering Parameters")

interchange_type = st.sidebar.selectbox(
    "Interchange Type",
    ["Cloverleaf", "Diverging Diamond (DDI)", "Roundabout"],
    index=0,
)

st.sidebar.markdown("---")
st.sidebar.subheader("Geometry")

if interchange_type == "Cloverleaf":
    loop_radius = st.sidebar.slider("Loop radius (m)", 20.0, 120.0, 50.0, 5.0)
    lane_width = st.sidebar.slider("Lane width (m)", 2.5, 5.0, 3.5, 0.1)
    mainline_lanes = st.sidebar.slider("Mainline lanes", 2, 6, 3)
    ramp_lanes = st.sidebar.slider("Ramp lanes", 1, 3, 1)
    mainline_length = st.sidebar.slider("Mainline length (m)", 200.0, 600.0, 300.0, 50.0)

elif interchange_type == "Diverging Diamond (DDI)":
    crossover_angle = st.sidebar.slider("Crossover angle (°)", 15.0, 60.0, 30.0, 5.0)
    ddi_length = st.sidebar.slider("Interchange length (m)", 100.0, 400.0, 200.0, 20.0)
    lane_width = st.sidebar.slider("Lane width (m)", 2.5, 5.0, 3.5, 0.1)
    mainline_lanes = st.sidebar.slider("Mainline lanes", 2, 6, 3)
    arterial_lanes = st.sidebar.slider("Arterial lanes", 1, 4, 2)

else:  # Roundabout
    roundabout_radius = st.sidebar.slider("Roundabout radius (m)", 15.0, 80.0, 30.0, 5.0)
    num_entries = st.sidebar.slider("Number of entries", 3, 8, 4)
    arm_length = st.sidebar.slider("Arm length (m)", 50.0, 200.0, 100.0, 10.0)
    lane_width = st.sidebar.slider("Lane width (m)", 2.5, 5.0, 3.5, 0.1)
    circ_lanes = st.sidebar.slider("Circulatory lanes", 1, 3, 2)
    arm_lanes = st.sidebar.slider("Arm lanes", 1, 3, 2)

st.sidebar.markdown("---")
st.sidebar.subheader("Traffic Demand")
global_volume = st.sidebar.slider(
    "Volume per segment (veh/h)", 0, 5000, 1200, 100
)

st.sidebar.markdown("---")
st.sidebar.subheader("Rendering")
spline_steps = st.sidebar.slider("Curve resolution (points)", 50, 500, 200, 50)
map_zoom = st.sidebar.slider("Initial zoom level", 10.0, 18.0, 14.5, 0.5)

# ---------------------------------------------------------------------------
# Generate network
# ---------------------------------------------------------------------------

if interchange_type == "Cloverleaf":
    gen = CloverleafGenerator(
        radius=loop_radius,
        lane_width=lane_width,
        mainline_lanes=mainline_lanes,
        ramp_lanes=ramp_lanes,
        mainline_length=mainline_length,
    )
elif interchange_type == "Diverging Diamond (DDI)":
    gen = DDIGenerator(
        crossover_angle_deg=crossover_angle,
        length=ddi_length,
        lane_width=lane_width,
        mainline_lanes=mainline_lanes,
        arterial_lanes=arterial_lanes,
    )
else:
    gen = RoundaboutGenerator(
        radius=roundabout_radius,
        num_entries=num_entries,
        arm_length=arm_length,
        lane_width=lane_width,
        circulatory_lanes=circ_lanes,
        arm_lanes=arm_lanes,
    )

network = gen.generate()

# Apply uniform traffic volume to all segments
volumes = {seg.id: float(global_volume) for seg in network.segments}
traffic = TrafficState.from_network(network, volumes)

# ---------------------------------------------------------------------------
# Main view — title + map
# ---------------------------------------------------------------------------

st.title(f"🛣️ TDSS — {interchange_type} Interchange")

col_map, col_info = st.columns([7, 3])

with col_map:
    st.subheader("Engineering View")
    deck = build_engineering_view(
        network, traffic, steps=spline_steps, zoom=map_zoom,
    )
    st.pydeck_chart(deck, use_container_width=True, height=620)

with col_info:
    st.subheader("Network Summary")

    total_capacity = sum(s.capacity_veh_h for s in traffic.segment_states.values())
    avg_vc = (
        sum(s.vc_ratio for s in traffic.segment_states.values())
        / max(len(traffic.segment_states), 1)
    )
    total_segments = len(network.segments)
    conflicts = network.find_intersections(spline_steps)

    c1, c2 = st.columns(2)
    c1.metric("Segments", total_segments)
    c2.metric("Conflict Points", len(conflicts))

    c3, c4 = st.columns(2)
    c3.metric("Avg V/C", f"{avg_vc:.2f}")
    c4.metric("Total Capacity", f"{int(total_capacity):,} veh/h")

    st.markdown("---")
    st.subheader("Level of Service (LOS)")

    los_df = pd.DataFrame(traffic.summary_table())
    if not los_df.empty:
        def _highlight_los(val):
            colours = {
                "A": "background-color: #00C853; color: black",
                "B": "background-color: #64DD17; color: black",
                "C": "background-color: #FFD600; color: black",
                "D": "background-color: #FF6D00; color: white",
                "E": "background-color: #DD2C00; color: white",
                "F": "background-color: #6A1B9A; color: white",
            }
            return colours.get(val, "")

        styled = los_df.style.applymap(_highlight_los, subset=["LOS"])
        st.dataframe(styled, use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

st.markdown("---")
st.caption(
    "TDSS v0.1.0 — Transport Interchange Decision Support System  •  "
    "Geometry: SciPy cubic splines + Shapely  •  "
    "Rendering: Deck.gl via PyDeck  •  "
    "Traffic model: BPR link performance function"
)
