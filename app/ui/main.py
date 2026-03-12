"""
TDSS — Transport Interchange Decision Support System
=====================================================
Streamlit dashboard implementing a Multi-Criteria Decision Analysis (MCDA)
model based on the Weighted Sum Method (WSM) for evaluating competing
interchange design alternatives.

Academic context
----------------
The system evaluates four alternatives (two real-world SVG blueprints and
two parametrically-generated designs) against four criteria:

    1. Construction Cost  (Minimize) — derived from parsed SVG geometry
    2. Land Area Footprint (Minimize) — derived from SVG bounding box
    3. Traffic Throughput  (Maximize) — expert-preset value (PCU/h)
    4. Safety Factor       (Maximize) — expert-preset value (1–10 scale)

Criteria weights are set interactively by the decision-maker via sliders.
The engine automatically normalises weights and applies Min-Max
normalisation before computing the weighted sum scores.

Run
---
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

from app.application.dss_engine import (
    Alternative,
    Criterion,
    DecisionSupportSystem,
    EvaluationResult,
)
from app.application.traffic_engine import TrafficState
from app.domain.geometry import RoadNetwork
from app.infrastructure.generators import (
    CloverleafGenerator,
    DDIGenerator,
    RoundaboutGenerator,
)
from app.infrastructure.metrics import compute_land_area_m2, compute_total_road_length_m
from app.infrastructure.svg_parser import SVGInterchangeGenerator
from app.ui.visualizations.cad_renderer import build_engineering_view

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ASSETS_DIR = Path(__file__).resolve().parents[2] / "assets"

# Construction cost constant: €/metre/lane — a representative unit rate for
# highway-grade interchange construction in Central/Eastern Europe.
COST_PER_METRE_LANE: float = 2_000.0

# ---------------------------------------------------------------------------
# Interchange alternative definitions
# ---------------------------------------------------------------------------
# Each entry defines one design alternative.  SVG-based entries derive their
# geometry metrics dynamically; parametric entries use the procedural generators.
# "throughput_pcu_h" and "safety_score" are expert-preset values drawn from
# published interchange design guidance (TRB Highway Capacity Manual, 2022;
# PIARC Road Safety Manual, 2019).

_ALTERNATIVES_CFG: dict[str, dict] = {
    "Cloverleaf (Blueprint)": {
        "svg": str(_ASSETS_DIR / "Cloverleaf_interchange.svg"),
        "skip_ids": ["path3232"],
        "skip_fills": ["#c4cddb"],
        "scale_factor": 0.00025,
        "meters_per_pixel": 0.5,
        "default_lanes": 2,
        # Expert presets — source: HCM 7th edition, Chapter 14
        "throughput_pcu_h": 3_000,
        "safety_score": 4.0,  # Low: weaving sections create merging conflicts
        "description": "Classic 4-loop cloverleaf derived from real SVG blueprint",
        "color": "#E74C3C",
    },
    "Cloverleaf DE (Blueprint)": {
        "svg": str(_ASSETS_DIR / "AK-Kleeblatt.svg"),
        "skip_ids": [],
        "skip_fills": [],
        "scale_factor": 0.00025,
        "meters_per_pixel": 0.317,   # 1260 px ≈ 400 m real-world span → 0.317 m/px
        "default_lanes": 2,
        # German Autobahn variant — same type, similar performance profile
        "throughput_pcu_h": 3_000,
        "safety_score": 4.0,
        "description": "German Autobahn Kleeblatt (Inkscape SVG blueprint)",
        "color": "#E67E22",
    },
    "Roundabout": {
        "svg": None,
        "default_lanes": 2,
        "throughput_pcu_h": 1_500,
        "safety_score": 8.5,  # High: single conflict point type, low-speed entry
        "description": "Modern 4-arm roundabout (parametric geometry)",
        "color": "#27AE60",
    },
    "Diverging Diamond (DDI)": {
        "svg": None,
        "default_lanes": 3,
        "throughput_pcu_h": 2_000,
        "safety_score": 8.0,  # Good: eliminates left-turn conflicts with freeway
        "description": "Diverging Diamond Interchange (parametric geometry)",
        "color": "#2980B9",
    },
}

# ---------------------------------------------------------------------------
# DSS criteria definitions
# ---------------------------------------------------------------------------

_CRITERIA: list[Criterion] = [
    Criterion(name="Construction Cost", direction="minimize", unit="€", weight=0.30),
    Criterion(name="Land Area",         direction="minimize", unit="m²",  weight=0.20),
    Criterion(name="Throughput",        direction="maximize", unit="PCU/h", weight=0.25),
    Criterion(name="Safety",            direction="maximize", unit="/10",  weight=0.25),
]

# ---------------------------------------------------------------------------
# Network loading — cached so SVG parsing only runs once per session
# ---------------------------------------------------------------------------

@st.cache_resource(show_spinner="Parsing SVG blueprints and generating networks…")
def _load_all_networks() -> dict[str, RoadNetwork]:
    """Load/generate every interchange network once and cache the result."""
    networks: dict[str, RoadNetwork] = {}
    for name, cfg in _ALTERNATIVES_CFG.items():
        if cfg["svg"] is not None:
            gen = SVGInterchangeGenerator(
                filepath=cfg["svg"],
                num_points=50,
                scale_factor=cfg["scale_factor"],
                num_lanes=cfg["default_lanes"],
                skip_ids=cfg.get("skip_ids", []),
                skip_fill_colors=cfg.get("skip_fills", []),
            )
            net = gen.generate()
            if not net.segments:
                # Fallback: parametric cloverleaf if SVG parse fails
                net = CloverleafGenerator(mainline_lanes=cfg["default_lanes"]).generate()
        else:
            if "Roundabout" in name:
                net = RoundaboutGenerator(
                    radius=30.0, num_entries=4, arm_length=100.0,
                    circulatory_lanes=cfg["default_lanes"],
                    arm_lanes=cfg["default_lanes"],
                ).generate()
            else:  # DDI
                net = DDIGenerator(
                    mainline_lanes=cfg["default_lanes"],
                    arterial_lanes=cfg["default_lanes"] - 1,
                ).generate()
        networks[name] = net
    return networks


# ---------------------------------------------------------------------------
# Page configuration
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="TDSS — Transport Interchange DSS",
    page_icon="🛣️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Custom CSS — dark engineering theme
# ---------------------------------------------------------------------------

st.markdown(
    """
    <style>
    .stApp { background-color: #181A1E; }
    section[data-testid="stSidebar"] { background-color: #1E2028; }
    h1, h2, h3, .stMarkdown p, .stMarkdown li, label {
        color: #E0E0E0 !important;
    }
    .stMetric label { color: #A0A0A0 !important; }
    .stMetric [data-testid="stMetricValue"] { color: #FFFFFF !important; }
    .stDataFrame { background-color: #23252B; }
    div[data-testid="stDecoration"] { display: none; }
    .rank-badge {
        display: inline-block;
        padding: 3px 10px;
        border-radius: 12px;
        font-weight: 700;
        font-size: 0.9rem;
    }
    .rank-1 { background: #1A3A1A; color: #4CAF50; border: 1px solid #4CAF50; }
    .rank-2 { background: #1A2A3A; color: #2196F3; border: 1px solid #2196F3; }
    .rank-3 { background: #3A2A1A; color: #FF9800; border: 1px solid #FF9800; }
    .rank-4 { background: #2A1A1A; color: #F44336; border: 1px solid #F44336; }
    .weight-warning { color: #FF9800; font-size: 0.85rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Sidebar — DSS criteria weight controls
# ---------------------------------------------------------------------------

st.sidebar.markdown(
    "<h2 style='color:#E0E0E0;margin-bottom:4px'>⚖️ Criteria Weights</h2>"
    "<p style='color:#888;font-size:0.82rem'>"
    "Set the relative importance of each criterion.<br>"
    "Weights are automatically normalised to sum to 1.0."
    "</p>",
    unsafe_allow_html=True,
)

w_cost       = st.sidebar.slider("💰 Construction Cost (Minimize)", 0.0, 1.0, 0.30, 0.05)
w_area       = st.sidebar.slider("🗺️ Land Area (Minimize)",         0.0, 1.0, 0.20, 0.05)
w_throughput = st.sidebar.slider("🚗 Throughput / Capacity (Maximize)", 0.0, 1.0, 0.25, 0.05)
w_safety     = st.sidebar.slider("🛡️ Safety Factor (Maximize)",     0.0, 1.0, 0.25, 0.05)

raw_weights = {
    "Construction Cost": w_cost,
    "Land Area": w_area,
    "Throughput": w_throughput,
    "Safety": w_safety,
}
total_raw = sum(raw_weights.values())

if total_raw == 0.0:
    st.sidebar.markdown(
        "<p class='weight-warning'>⚠️ All weights are zero — set at least one above 0.</p>",
        unsafe_allow_html=True,
    )
    normalised_weights = {k: 0.25 for k in raw_weights}
else:
    normalised_weights = {k: v / total_raw for k, v in raw_weights.items()}

# Display the normalised weights as a mini-summary
st.sidebar.markdown("---")
st.sidebar.markdown(
    "<p style='color:#888;font-size:0.78rem;margin-bottom:2px'>Normalised weights (sum = 1.0):</p>",
    unsafe_allow_html=True,
)
for cname, nw in normalised_weights.items():
    bar_pct = int(nw * 100)
    st.sidebar.markdown(
        f"<p style='color:#CCC;font-size:0.8rem;margin:1px 0'>"
        f"<b>{cname[:12]}</b>: {nw:.2f} "
        f"<span style='color:#5BA4CF'>{'█' * (bar_pct // 5)}{'░' * (20 - bar_pct // 5)}</span>"
        f"</p>",
        unsafe_allow_html=True,
    )

st.sidebar.markdown("---")
st.sidebar.markdown(
    "<p style='color:#888;font-size:0.78rem'>Advanced Options</p>",
    unsafe_allow_html=True,
)
cost_per_m = st.sidebar.number_input(
    "Cost per metre per lane (€)", min_value=100, max_value=50_000, value=2_000, step=100
)
st.sidebar.markdown("---")

# Blueprint explorer controls (used in Tab 2)
st.sidebar.markdown(
    "<h3 style='color:#E0E0E0;font-size:0.95rem'>🗺️ Blueprint Explorer</h3>",
    unsafe_allow_html=True,
)
explorer_choice = st.sidebar.selectbox(
    "Select alternative to inspect",
    list(_ALTERNATIVES_CFG.keys()),
    index=0,
)
spline_steps = st.sidebar.slider("Curve resolution", 50, 300, 150, 50)
map_zoom     = st.sidebar.slider("Map zoom level", 10.0, 18.0, 14.5, 0.5)

# ---------------------------------------------------------------------------
# Load networks + build DSS alternatives
# ---------------------------------------------------------------------------

networks = _load_all_networks()

dss_alternatives: list[Alternative] = []
for alt_name, cfg in _ALTERNATIVES_CFG.items():
    net = networks[alt_name]
    sf  = cfg.get("scale_factor", 0.00025)
    mpp = cfg.get("meters_per_pixel", 0.5)
    lanes = cfg["default_lanes"]

    # --- Dynamically-computed metrics from the SVG / parametric geometry ---
    road_length_m = compute_total_road_length_m(net.segments, sf, mpp)
    land_area_m2  = compute_land_area_m2(net.segments, sf, mpp)

    # Construction cost: total centreline length × lanes × cost per lane-metre.
    # This approximation is consistent with pre-feasibility cost estimation
    # methods where lane-kilometres are the primary cost driver.
    construction_cost = road_length_m * lanes * cost_per_m

    alt = Alternative(
        name=alt_name,
        description=cfg["description"],
        raw_values={
            "Construction Cost": construction_cost,
            "Land Area":         land_area_m2,
            "Throughput":        float(cfg["throughput_pcu_h"]),
            "Safety":            cfg["safety_score"],
        },
    )
    dss_alternatives.append(alt)

# Run the WSM evaluation
dss = DecisionSupportSystem(_CRITERIA)
results: list[EvaluationResult] = dss.evaluate(dss_alternatives, weights=normalised_weights)

# ---------------------------------------------------------------------------
# Page layout — tabs
# ---------------------------------------------------------------------------

st.markdown(
    "<h1 style='color:#E0E0E0;margin-bottom:4px'>"
    "🛣️ TDSS — Transport Interchange Decision Support System"
    "</h1>"
    "<p style='color:#888;font-size:0.9rem;margin-top:0'>"
    "Multi-Criteria Decision Analysis (MCDA) · Weighted Sum Model (WSM)"
    "</p>",
    unsafe_allow_html=True,
)

tab_dss, tab_explorer = st.tabs(["📊 DSS Evaluation", "🗺️ Blueprint Explorer"])

# ===========================================================================
# TAB 1: DSS Evaluation
# ===========================================================================

with tab_dss:

    # ------------------------------------------------------------------
    # Ranking banner
    # ------------------------------------------------------------------

    st.subheader("Ranking Summary")
    rank_cols = st.columns(len(results))
    rank_labels = ["🥇", "🥈", "🥉", "4️⃣"]
    for col, res, medal in zip(rank_cols, results, rank_labels):
        with col:
            cfg = _ALTERNATIVES_CFG[res.alternative_name]
            st.markdown(
                f"<div style='background:#23252B;border-radius:8px;padding:12px;text-align:center'>"
                f"<div style='font-size:1.6rem'>{medal}</div>"
                f"<div style='color:{cfg['color']};font-weight:700;font-size:0.9rem'>"
                f"{res.alternative_name}</div>"
                f"<div style='color:#FFF;font-size:1.5rem;font-weight:700'>{res.total_score:.3f}</div>"
                f"<div style='color:#888;font-size:0.75rem'>WSM Score</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

    st.markdown("---")

    # ------------------------------------------------------------------
    # Raw values table
    # ------------------------------------------------------------------

    st.subheader("Criterion Values — Raw Data")
    st.caption(
        "Construction Cost and Land Area are computed dynamically from the parsed SVG geometry.  "
        "Throughput and Safety are expert-preset values from published design guidance."
    )

    raw_rows = []
    for res in results:
        row = {
            "Rank": f"#{res.rank}",
            "Alternative": res.alternative_name,
            "Cost (€)":    f"{res.raw_values['Construction Cost']:,.0f}",
            "Land Area (m²)": f"{res.raw_values['Land Area']:,.0f}",
            "Throughput (PCU/h)": int(res.raw_values["Throughput"]),
            "Safety (/10)":  res.raw_values["Safety"],
        }
        raw_rows.append(row)

    raw_df = pd.DataFrame(raw_rows).set_index("Rank")
    st.dataframe(raw_df, use_container_width=True)

    st.markdown("---")

    # ------------------------------------------------------------------
    # Normalised values & weighted scores table
    # ------------------------------------------------------------------

    st.subheader("MCDA Scoring Table — Normalised Values & Weighted Contributions")
    st.caption(
        "Min-Max normalisation maps each raw criterion value to [0, 1].  "
        "For Minimize criteria the scale is inverted so that 1.0 always represents "
        "the best-performing alternative on that criterion.  "
        "The WSM score S_i = Σ(w_j · x̄_ij) is the sum of weighted contributions."
    )

    crit_names = dss.criterion_names()
    score_rows = []
    for res in results:
        row: dict = {
            "Rank": f"#{res.rank}",
            "Alternative": res.alternative_name,
        }
        for cname in crit_names:
            crit_obj = next(c for c in _CRITERIA if c.name == cname)
            direction_icon = "▲" if crit_obj.direction == "maximize" else "▼"
            w_str = f"{normalised_weights[cname]:.2f}"
            col_label = f"{direction_icon} {cname} [w={w_str}]"
            x_norm = res.normalised_values[cname]
            w_score = res.weighted_scores[cname]
            row[col_label] = f"{x_norm:.3f}  →  {w_score:.3f}"
        row["WSM Score S_i"] = f"**{res.total_score:.4f}**"
        score_rows.append(row)

    score_df = pd.DataFrame(score_rows).set_index("Rank")
    st.dataframe(score_df, use_container_width=True)

    st.markdown("---")

    # ------------------------------------------------------------------
    # Score bar chart
    # ------------------------------------------------------------------

    st.subheader("WSM Score Comparison")

    chart_data = pd.DataFrame(
        {
            "Alternative": [r.alternative_name for r in results],
            "WSM Score":   [r.total_score for r in results],
        }
    ).sort_values("WSM Score", ascending=True)

    st.bar_chart(
        chart_data.set_index("Alternative"),
        use_container_width=True,
        height=260,
    )

    # ------------------------------------------------------------------
    # Per-criterion contribution breakdown
    # ------------------------------------------------------------------

    st.subheader("Weighted Contribution Breakdown")
    st.caption(
        "Each bar shows the per-criterion weighted contribution w_j · x̄_ij "
        "for every alternative.  The stacked total equals the WSM score S_i."
    )

    breakdown_rows = []
    for res in results:
        for cname, ws in res.weighted_scores.items():
            breakdown_rows.append(
                {
                    "Alternative": res.alternative_name,
                    "Criterion":   cname,
                    "Contribution": ws,
                }
            )
    breakdown_df = pd.DataFrame(breakdown_rows)
    pivot_df = breakdown_df.pivot(index="Alternative", columns="Criterion", values="Contribution")

    # Re-order rows by rank
    ordered_alts = [r.alternative_name for r in results]
    pivot_df = pivot_df.reindex(ordered_alts)

    st.bar_chart(pivot_df, use_container_width=True, height=280)

    # ------------------------------------------------------------------
    # Geometry metrics summary
    # ------------------------------------------------------------------

    st.markdown("---")
    st.subheader("Geometry Metrics (Dynamic)")

    geo_cols = st.columns(len(dss_alternatives))
    for col, alt in zip(geo_cols, dss_alternatives):
        net = networks[alt.name]
        cfg = _ALTERNATIVES_CFG[alt.name]
        road_len = alt.raw_values["Construction Cost"] / (cfg["default_lanes"] * cost_per_m)
        with col:
            st.markdown(
                f"<div style='background:#23252B;border-radius:6px;padding:10px'>"
                f"<b style='color:{cfg['color']}'>{alt.name}</b><br>"
                f"<span style='color:#AAA;font-size:0.78rem'>{cfg['description']}</span><br><br>"
                f"<span style='color:#CCC'>Road Length:</span> "
                f"<b style='color:#FFF'>{road_len:,.0f} m</b><br>"
                f"<span style='color:#CCC'>Land Footprint:</span> "
                f"<b style='color:#FFF'>{alt.raw_values['Land Area']:,.0f} m²</b><br>"
                f"<span style='color:#CCC'>Segments:</span> "
                f"<b style='color:#FFF'>{len(net.segments)}</b>"
                f"</div>",
                unsafe_allow_html=True,
            )

    # ------------------------------------------------------------------
    # Methodology note
    # ------------------------------------------------------------------

    with st.expander("📖 Methodology Notes (for coursework report)"):
        st.markdown(
            """
### Multi-Criteria Decision Analysis (MCDA) — Weighted Sum Method (WSM)

**Formal definition**

The WSM composite score for alternative *i* is defined as:

$$S_i = \\sum_{j=1}^{n} w_j \\cdot \\bar{x}_{ij}$$

where $n$ is the number of criteria, $w_j$ is the normalised weight for criterion
$j$ (with $\\sum_j w_j = 1$), and $\\bar{x}_{ij}$ is the Min-Max normalised value.

**Min-Max normalisation**

For a *Maximize* criterion (higher is better):
$$\\bar{x}_{ij} = \\frac{x_{ij} - \\min_j}{\\max_j - \\min_j}$$

For a *Minimize* criterion (lower is better) the scale is inverted:
$$\\bar{x}_{ij} = \\frac{\\max_j - x_{ij}}{\\max_j - \\min_j}$$

**Criteria derivation**

| Criterion | Type | Source |
|---|---|---|
| Construction Cost | Minimize | Dynamic: road_length × lanes × €/m/lane |
| Land Area | Minimize | Dynamic: SVG bounding box (m²) |
| Throughput | Maximize | Expert preset (HCM 7th Ed., Ch. 14) |
| Safety Factor | Maximize | Expert preset (PIARC Road Safety Manual 2019) |

**References**
- Fishburn, P.C. (1967). *Additive utilities with incomplete product sets*. Operations Research, 15(3).
- Triantaphyllou, E. (2000). *Multi-Criteria Decision Making Methods*. Kluwer Academic Publishers.
- TRB (2022). *Highway Capacity Manual, 7th Edition*. Transportation Research Board.
            """
        )

# ===========================================================================
# TAB 2: Blueprint Explorer
# ===========================================================================

with tab_explorer:

    st.subheader(f"Blueprint Explorer — {explorer_choice}")
    cfg_ex = _ALTERNATIVES_CFG[explorer_choice]
    net_ex = networks[explorer_choice]

    st.caption(
        f"**{cfg_ex['description']}**  ·  "
        f"{len(net_ex.segments)} road segments  ·  "
        f"{'SVG Blueprint' if cfg_ex['svg'] else 'Parametric Generator'}"
    )

    col_map, col_info = st.columns([7, 3])

    with col_map:
        if net_ex.segments:
            volumes_ex = {seg.id: 1_200.0 for seg in net_ex.segments}
            traffic_ex = TrafficState.from_network(net_ex, volumes_ex)
            deck_ex = build_engineering_view(net_ex, traffic_ex, steps=spline_steps, zoom=map_zoom)
            st.pydeck_chart(deck_ex, use_container_width=True, height=580)
        else:
            st.warning("No segments loaded for this alternative.")

    with col_info:
        st.subheader("Interchange Metrics")

        sf_ex  = cfg_ex.get("scale_factor", 0.00025)
        mpp_ex = cfg_ex.get("meters_per_pixel", 0.5)

        road_len_ex   = compute_total_road_length_m(net_ex.segments, sf_ex, mpp_ex)
        land_area_ex  = compute_land_area_m2(net_ex.segments, sf_ex, mpp_ex)
        cost_ex       = road_len_ex * cfg_ex["default_lanes"] * cost_per_m

        c1, c2 = st.columns(2)
        c1.metric("Road Length", f"{road_len_ex:,.0f} m")
        c2.metric("Land Area",   f"{land_area_ex:,.0f} m²")

        c3, c4 = st.columns(2)
        c3.metric("Est. Cost",   f"€{cost_ex:,.0f}")
        c4.metric("Segments",    len(net_ex.segments))

        c5, c6 = st.columns(2)
        c5.metric("Throughput",  f"{cfg_ex['throughput_pcu_h']:,} PCU/h")
        c6.metric("Safety",      f"{cfg_ex['safety_score']}/10")

        st.markdown("---")

        # Show the DSS result for this alternative
        result_ex = next(r for r in results if r.alternative_name == explorer_choice)
        rank_icon = ["🥇", "🥈", "🥉", "4️⃣"][result_ex.rank - 1]
        st.markdown(
            f"<div style='background:#23252B;border-radius:8px;padding:12px;text-align:center'>"
            f"<div style='font-size:1.1rem;color:#CCC'>DSS Ranking</div>"
            f"<div style='font-size:2.5rem'>{rank_icon}</div>"
            f"<div style='color:#FFF;font-weight:700;font-size:1.4rem'>"
            f"WSM Score: {result_ex.total_score:.4f}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

        st.markdown("---")
        st.markdown("**Criterion Contributions**")
        contrib_rows = [
            {"Criterion": k, "Normalised": f"{v:.3f}", "Weighted": f"{result_ex.weighted_scores[k]:.3f}"}
            for k, v in result_ex.normalised_values.items()
        ]
        st.dataframe(pd.DataFrame(contrib_rows), use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

st.markdown("---")
st.caption(
    "TDSS v2.0 — Transport Interchange Decision Support System  •  "
    "MCDA engine: Weighted Sum Model (WSM)  •  "
    "Geometry: SVG blueprints + SciPy cubic splines + Shapely  •  "
    "Rendering: Deck.gl via PyDeck"
)
