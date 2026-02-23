"""
TDSS — Transport Interchange Decision Support System
=====================================================
Full-screen engineering dashboard.

Run:
    streamlit run app/ui/main.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import pandas as pd
import streamlit as st

from app.application.traffic_engine import TrafficState
from app.domain.models import InterchangeMetrics
from app.infrastructure.generators import (
    CloverleafGenerator,
    DDIGenerator,
    RoundaboutGenerator,
    SPUIGenerator,
    TurbineGenerator,
)
from app.ui.visualizations.cad_renderer import build_engineering_view
from app.ui.visualizations.radar_chart import build_radar_figure

st.set_page_config(
    page_title="TDSS: Transport Digital Twin",
    page_icon="🛣️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    html, body, [data-testid="stAppViewContainer"], .stApp {
        background-color: #12141A !important;
    }

    [data-testid="stAppViewContainer"] > .main > .block-container {
        padding-top: 0.75rem !important;
        padding-bottom: 0.5rem !important;
        padding-left:  1.5rem !important;
        padding-right: 1.5rem !important;
        max-width: 100% !important;
    }
    [data-testid="stHeader"] { display: none !important; }
    [data-testid="stDecoration"] { display: none !important; }
    [data-testid="stToolbar"] { display: none !important; }

    section[data-testid="stSidebar"] {
        background-color: #1A1D25 !important;
        border-right: 1px solid #2C2F3A;
    }
    section[data-testid="stSidebar"] * {
        color: #C8CAD4 !important;
    }
    section[data-testid="stSidebar"] .stSlider [data-baseweb="thumb"] {
        background-color: #5B8BFF !important;
    }
    section[data-testid="stSidebar"] hr {
        border-color: #2C2F3A !important;
    }

    h1 { font-size: 1.35rem !important; font-weight: 700 !important;
         color: #E8EAF0 !important; letter-spacing: 0.02em; margin-bottom: 0 !important; }
    h2, h3 { font-size: 0.95rem !important; font-weight: 600 !important;
              color: #9AA3B8 !important; text-transform: uppercase;
              letter-spacing: 0.06em; margin-top: 0.8rem !important; }
    p, li, label, .stMarkdown { color: #C8CAD4 !important; }

    [data-testid="stMetric"] {
        background: #1E2130 !important;
        border: 1px solid #2C3048 !important;
        border-radius: 8px !important;
        padding: 0.6rem 0.85rem !important;
    }
    [data-testid="stMetric"] label {
        font-size: 0.7rem !important;
        color: #6B7390 !important;
        text-transform: uppercase;
        letter-spacing: 0.07em;
    }
    [data-testid="stMetricValue"] {
        font-size: 1.15rem !important;
        font-weight: 700 !important;
        color: #E8EAF0 !important;
    }

    [data-testid="stTabs"] [role="tab"] {
        color: #6B7390 !important;
        font-size: 0.8rem !important;
        font-weight: 600 !important;
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }
    [data-testid="stTabs"] [role="tab"][aria-selected="true"] {
        color: #5B8BFF !important;
        border-bottom: 2px solid #5B8BFF !important;
    }
    [data-testid="stTabs"] { border-bottom: 1px solid #2C2F3A !important; }

    [data-testid="stDataFrame"] {
        border: 1px solid #2C2F3A !important;
        border-radius: 8px !important;
        overflow: hidden !important;
    }
    [data-testid="stDataFrame"] th {
        background-color: #1A1D25 !important;
        color: #6B7390 !important;
        font-size: 0.7rem !important;
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }
    [data-testid="stDataFrame"] td {
        background-color: #1E2130 !important;
        color: #C8CAD4 !important;
        font-size: 0.78rem !important;
    }

    iframe[title="pydeck"] {
        border-radius: 10px !important;
        border: 1px solid #2C2F3A !important;
    }

    [data-testid="stPlotlyChart"] {
        background: transparent !important;
    }

    hr { border-color: #2C2F3A !important; }

    .stCaption { color: #4A5068 !important; font-size: 0.7rem !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.sidebar.title("TDSS  |  Engineering Parameters")

interchange_type = st.sidebar.selectbox(
    "Interchange Type",
    ["Cloverleaf", "Diverging Diamond (DDI)", "Roundabout", "SPUI", "Turbine"],
)

st.sidebar.markdown("---")
st.sidebar.subheader("Geometry")

if interchange_type == "Cloverleaf":
    loop_radius     = st.sidebar.slider("Loop radius (m)",           20.0, 120.0, 50.0,  5.0)
    lane_width      = st.sidebar.slider("Lane width (m)",             2.5,   5.0,  3.5,  0.1)
    mainline_lanes  = st.sidebar.slider("Mainline lanes",                2,     6,    3)
    ramp_lanes      = st.sidebar.slider("Ramp lanes",                    1,     3,    1)
    mainline_length = st.sidebar.slider("Mainline length (m)",       200.0, 600.0,300.0, 50.0)

elif interchange_type == "Diverging Diamond (DDI)":
    crossover_angle = st.sidebar.slider("Crossover angle (°)",       15.0,  60.0, 30.0,  5.0)
    ddi_length      = st.sidebar.slider("Interchange length (m)",   100.0, 400.0,200.0, 20.0)
    lane_width      = st.sidebar.slider("Lane width (m)",             2.5,   5.0,  3.5,  0.1)
    mainline_lanes  = st.sidebar.slider("Mainline lanes",                2,     6,    3)
    arterial_lanes  = st.sidebar.slider("Arterial lanes",                1,     4,    2)

elif interchange_type == "SPUI":
    leg_length      = st.sidebar.slider("Leg length (m)",            40.0, 150.0, 80.0, 10.0)
    lane_width      = st.sidebar.slider("Lane width (m)",             2.5,   5.0,  3.5,  0.1)
    mainline_lanes  = st.sidebar.slider("Mainline lanes",                2,     6,    3)
    arterial_lanes  = st.sidebar.slider("Arterial lanes",                1,     4,    2)

elif interchange_type == "Turbine":
    spiral_radius   = st.sidebar.slider("Spiral radius (m)",         50.0, 150.0, 80.0, 10.0)
    turbine_length  = st.sidebar.slider("Mainline length (m)",       300.0, 600.0,400.0, 50.0)
    lane_width      = st.sidebar.slider("Lane width (m)",             2.5,   5.0,  3.5,  0.1)
    mainline_lanes  = st.sidebar.slider("Mainline lanes",                2,     6,    3)
    ramp_lanes      = st.sidebar.slider("Ramp lanes",                    1,     2,    1)

else:  # Roundabout
    roundabout_radius = st.sidebar.slider("Roundabout radius (m)",  15.0,  80.0, 30.0,  5.0)
    num_entries       = st.sidebar.slider("Number of entries",           3,     8,    4)
    arm_length        = st.sidebar.slider("Arm length (m)",          50.0, 200.0,100.0, 10.0)
    lane_width        = st.sidebar.slider("Lane width (m)",           2.5,   5.0,  3.5,  0.1)
    circ_lanes        = st.sidebar.slider("Circulatory lanes",           1,     3,    2)
    arm_lanes         = st.sidebar.slider("Arm lanes",                   1,     3,    2)

st.sidebar.markdown("---")
st.sidebar.subheader("Traffic Demand")
global_volume = st.sidebar.slider("Volume per segment (veh/h)", 0, 5000, 1200, 100)

st.sidebar.markdown("---")
st.sidebar.subheader("Rendering")
spline_steps = st.sidebar.slider("Curve resolution (points)", 50, 500, 200, 50)
map_zoom     = st.sidebar.slider("Initial zoom level",        10.0, 18.0, 14.5, 0.5)

# ---------------------------------------------------------------------------
# 4. Generate network + compute metrics
# ---------------------------------------------------------------------------

if interchange_type == "Cloverleaf":
    gen = CloverleafGenerator(
        radius=loop_radius, lane_width=lane_width,
        mainline_lanes=mainline_lanes, ramp_lanes=ramp_lanes,
        mainline_length=mainline_length,
    )
elif interchange_type == "Diverging Diamond (DDI)":
    gen = DDIGenerator(
        crossover_angle_deg=crossover_angle, length=ddi_length,
        lane_width=lane_width, mainline_lanes=mainline_lanes,
        arterial_lanes=arterial_lanes,
    )
elif interchange_type == "SPUI":
    gen = SPUIGenerator(
        leg_length=leg_length, lane_width=lane_width,
        mainline_lanes=mainline_lanes, arterial_lanes=arterial_lanes,
    )
elif interchange_type == "Turbine":
    gen = TurbineGenerator(
        spiral_radius=spiral_radius, mainline_length=turbine_length,
        lane_width=lane_width, mainline_lanes=mainline_lanes,
        ramp_lanes=ramp_lanes,
    )
else:
    gen = RoundaboutGenerator(
        radius=roundabout_radius, num_entries=num_entries,
        arm_length=arm_length, lane_width=lane_width,
        circulatory_lanes=circ_lanes, arm_lanes=arm_lanes,
    )

network  = gen.generate()
volumes  = {seg.id: float(global_volume) for seg in network.segments}
traffic  = TrafficState.from_network(network, volumes)
metrics  = InterchangeMetrics(network=network)

total_capacity = sum(s.capacity_veh_h for s in traffic.segment_states.values())
avg_vc = (
    sum(s.vc_ratio for s in traffic.segment_states.values())
    / max(len(traffic.segment_states), 1)
)
bridge_count = sum(1 for s in network.segments if s.is_bridge)
cost_usd     = metrics.cost_usd
footprint_ha = metrics.footprint_hectares

# ---------------------------------------------------------------------------
# 5. Page header — compact single line
# ---------------------------------------------------------------------------

st.markdown(
    f"<h1>TDSS &mdash; <span style='color:#5B8BFF'>{interchange_type}</span>"
    f"&nbsp; Interchange &nbsp;"
    f"<span style='font-size:0.75rem;font-weight:400;color:#6B7390'>"
    f"{len(network.segments)} segments &bull; "
    f"${cost_usd / 1e6:.1f} M est. cost &bull; "
    f"{footprint_ha:.1f} ha footprint</span></h1>",
    unsafe_allow_html=True,
)

st.markdown("<hr style='margin:0.4rem 0 0.6rem'>", unsafe_allow_html=True)

tab_eng, tab_analytics = st.tabs(["Engineering View", "Analytics — Client Report"])

with tab_eng:

    col_map, col_stats = st.columns([3, 1], gap="medium")

    with col_map:
        st.subheader("Top-Down Engineering View")
        deck = build_engineering_view(
            network, traffic, steps=spline_steps, zoom=map_zoom,
        )
        st.pydeck_chart(deck, use_container_width=True, height=660)

    with col_stats:
        st.subheader("Network KPIs")

        kc1, kc2 = st.columns(2)
        kc1.metric("Segments",     len(network.segments))
        kc2.metric("Bridges",      bridge_count)

        kc3, kc4 = st.columns(2)
        kc3.metric("Avg V/C",      f"{avg_vc:.2f}")
        kc4.metric("Total Cap.",   f"{int(total_capacity / 1000)}k veh/h")

        st.metric("Construction cost", f"${cost_usd / 1e6:.2f} M")
        st.metric("Land footprint",    f"{footprint_ha:.2f} ha")

        st.markdown("---")
        st.subheader("Level of Service (LOS)")

        los_df = pd.DataFrame(traffic.summary_table())
        los_slim = los_df[["Segment", "V/C", "LOS", "Delay (min)"]].copy()

        LOS_STYLE = {
            "A": "background-color:#00573A;color:#AFFFDE",
            "B": "background-color:#1A5C1A;color:#AFFFC0",
            "C": "background-color:#5C4B00;color:#FFE9A0",
            "D": "background-color:#7A3000;color:#FFD0A0",
            "E": "background-color:#7A1000;color:#FFB8A0",
            "F": "background-color:#3D006E;color:#E8AEFF",
        }

        def _style_los(val: str) -> str:
            return LOS_STYLE.get(val, "")

        styled = los_slim.style.map(_style_los, subset=["LOS"])
        st.dataframe(styled, use_container_width=True, hide_index=True, height=320)

        st.markdown("---")
        st.subheader("Conflict Points")
        conflicts = network.find_intersections(spline_steps)
        if conflicts:
            st.warning(f"{len(conflicts)} conflict point(s) detected.")
        else:
            st.success("No geometric conflicts detected.")


with tab_analytics:

    kc1, kc2, kc3, kc4, kc5 = st.columns(5)
    kc1.metric("Total Segments",     len(network.segments))
    kc2.metric("Bridge Structures",  bridge_count)
    kc3.metric("Est. Cost",          f"${cost_usd / 1e6:.2f} M")
    kc4.metric("Land Footprint",     f"{footprint_ha:.2f} ha")
    kc5.metric("Avg V/C Ratio",      f"{avg_vc:.2f}")

    st.markdown("---")

    col_radar, col_los = st.columns([1, 1], gap="large")

    with col_radar:
        st.subheader("Performance Radar")
        st.caption(
            "Axes normalised 0–100. All dimensions: higher = better. "
            "Cost (Inverse) and Land Use (Inverse) penalise expensive / large interchanges."
        )
        fig = build_radar_figure(interchange_type, metrics, traffic)
        st.plotly_chart(fig, use_container_width=True)

    with col_los:
        st.subheader("Full LOS Table")
        st.caption("BPR link performance function — Highway Capacity Manual grades.")
        full_df = pd.DataFrame(traffic.summary_table())
        styled_full = full_df.style.map(_style_los, subset=["LOS"])
        st.dataframe(styled_full, use_container_width=True, hide_index=True, height=420)

st.markdown(
    "<p style='font-size:0.68rem;color:#3A3F55;text-align:center;margin-top:1rem'>"
    "TDSS v0.2.0 &nbsp;|&nbsp; "
    "Geometry: SciPy cubic splines + Cubic Bézier (G1) + Shapely &nbsp;|&nbsp; "
    "Rendering: Deck.gl via PyDeck &nbsp;|&nbsp; "
    "Traffic model: BPR link performance function &nbsp;|&nbsp; "
    "Cost model: AASHTO-aligned unit cost estimation"
    "</p>",
    unsafe_allow_html=True,
)
