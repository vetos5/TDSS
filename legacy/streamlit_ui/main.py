"""
TDSS v3 — Transport Interchange Decision Support System
=======================================================
Streamlit VIEW layer (Decoupled Architecture).

Responsibilities of this module
--------------------------------
1. Collect weight preferences via sidebar sliders.
2. Invoke the WSM engine (DecisionSupportSystem.evaluate).
3. Render Plotly charts from app.ui.charts.
4. Display static SVG blueprints as Base64-encoded <img> tags.

Run
---
    streamlit run app/ui/main.py
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd
import streamlit as st

from app.application.dss_engine import DecisionSupportSystem, EvaluationResult
from app.data.interchange_data import (
    ALTERNATIVE_COLORS,
    ALTERNATIVE_COLORS_DARK,
    BLUEPRINT_PATHS,
    CRITERIA,
    CRITERION_LABELS,
    DETAILED_INTERCHANGE_INFO,
    INTERCHANGE_DATA,
    get_alternatives_for_context,
)
from app.ui.charts import (
    create_contribution_stacked_bar,
    create_radar_chart,
    create_wsm_bar_chart,
)

import folium
from streamlit_folium import st_folium

# ---------------------------------------------------------------------------
# Page configuration
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="TDSS — Transport Interchange DSS",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Theme — must be resolved before any CSS or widget rendering
# ---------------------------------------------------------------------------

if "dark_mode" not in st.session_state:
    st.session_state["dark_mode"] = False
if "selected_detail" not in st.session_state:
    st.session_state["selected_detail"] = None

# Theme toggle — icon button at the very top of the sidebar
with st.sidebar:
    _icon_col, _btn_col = st.columns([5, 1])
    with _btn_col:
        _icon = "☀️" if st.session_state["dark_mode"] else "🌙"
        if st.button(_icon, key="theme_btn"):
            st.session_state["dark_mode"] = not st.session_state["dark_mode"]
            st.rerun()

dark_mode: bool = st.session_state["dark_mode"]

# ---------------------------------------------------------------------------
# Theme colour tokens (used both in injected CSS and in inline HTML)
# ---------------------------------------------------------------------------

if dark_mode:
    T = {
        "page_bg":      "#0f172a",
        "sidebar_bg":   "#1e293b",
        "card_bg":      "#1e293b",
        "card_border":  "#334155",
        "text":         "#e2e8f0",
        "subtext":      "#94a3b8",
        "muted":        "#475569",
        "accent":       "#2dd4bf",   # teal-400
        "accent_light": "#0d3a35",
        "divider":      "#334155",
        "input_bg":     "#1e293b",
        "winner_bg":    "#0d2d2a",
        "winner_border":"#2dd4bf",
        "tab_active":   "#2dd4bf",
        "metric_val":   "#e2e8f0",
        "df_bg":        "#1e293b",
    }
else:
    T = {
        "page_bg":      "#f8fafc",
        "sidebar_bg":   "#ffffff",
        "card_bg":      "#ffffff",
        "card_border":  "#e2e8f0",
        "text":         "#0f172a",
        "subtext":      "#334155",   # slate-700 — strong enough on white
        "muted":        "#64748b",
        "accent":       "#0f766e",   # teal-700
        "accent_light": "#f0fdfa",
        "divider":      "#e2e8f0",
        "input_bg":     "#f8fafc",
        "winner_bg":    "#f0fdfa",
        "winner_border":"#0f766e",
        "tab_active":   "#0f766e",
        "metric_val":   "#0f172a",
        "df_bg":        "#ffffff",
    }


# ---------------------------------------------------------------------------
# CSS — theme-aware, responsive typography
# ---------------------------------------------------------------------------

def _build_css(t: dict) -> str:
    return f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
    html, body, [class*="css"] {{ font-family: 'Inter', system-ui, sans-serif; }}

    /* ── Backgrounds ── */
    .stApp                               {{ background-color: {t["page_bg"]} !important; }}
    section[data-testid="stSidebar"]     {{ background-color: {t["sidebar_bg"]} !important;
                                            border-right: 1px solid {t["card_border"]} !important; }}

    /* ── Responsive headings ── */
    h1 {{ font-size: clamp(1.3rem, 3vw, 1.9rem)    !important; color: {t["text"]}    !important;
          font-weight: 800 !important; line-height: 1.2 !important; }}
    h2 {{ font-size: clamp(1.05rem, 2.2vw, 1.35rem) !important; color: {t["text"]}   !important;
          font-weight: 700 !important; }}
    h3 {{ font-size: clamp(0.9rem, 1.7vw, 1.1rem)   !important; color: {t["subtext"]} !important;
          font-weight: 600 !important; }}
    p, li {{ color: {t["subtext"]} !important;
             font-size: clamp(0.82rem, 1.4vw, 0.95rem) !important; }}
    label {{ color: {t["subtext"]} !important; font-size: 0.88rem !important; }}

    /* ── Metric widgets ── */
    [data-testid="stMetric"] {{
        background: {t["card_bg"]} !important;
        border: 1px solid {t["card_border"]} !important;
        border-radius: 10px; padding: 12px 14px;
    }}
    [data-testid="stMetricLabel"] {{ color: {t["muted"]}    !important; font-size: 0.78rem !important; }}
    [data-testid="stMetricValue"] {{ color: {t["metric_val"]} !important; font-weight: 700 !important; }}

    /* ── DataFrames ── */
    .stDataFrame  {{ background: {t["df_bg"]} !important; border-radius: 8px;
                     border: 1px solid {t["card_border"]} !important; }}
    [data-testid="stDataFrame"] td, [data-testid="stDataFrame"] th {{
        color: {t["text"]} !important;
    }}

    /* ── Tabs ── */
    button[data-baseweb="tab"]                       {{ color: {t["muted"]}  !important; font-weight: 500 !important; }}
    button[data-baseweb="tab"][aria-selected="true"] {{ color: {t["accent"]} !important; font-weight: 700 !important;
                                                        border-bottom: 2px solid {t["accent"]} !important; }}

    /* ── Streamlit caption & info ── */
    [data-testid="stCaptionContainer"] p {{ color: {t["muted"]} !important; font-size: 0.82rem !important; }}
    [data-testid="stNotification"] {{ background: {t["card_bg"]} !important; }}

    /* ── Sidebar toggle label ── */
    [data-testid="stToggleLabel"] {{ color: {t["subtext"]} !important; }}

    /* ── Rank cards ── */
    .rank-card {{
        background: {t["card_bg"]}; border: 1px solid {t["card_border"]};
        border-radius: 14px 14px 0 0; padding: 18px 10px 14px; text-align: center;
        box-shadow: 0 1px 4px rgba(0,0,0,0.06);
        transition: box-shadow 0.3s, transform 0.3s, border-color 0.3s, opacity 0.3s;
        position: relative;
        border-bottom: none;
    }}
    .rank-card:hover {{
        box-shadow: 0 8px 28px rgba(15,118,110,0.22);
        transform: translateY(-4px);
        border-color: {t["accent"]};
    }}
    .rank-card.winner {{
        border-color: {t["winner_border"]}; border-width: 2px;
        transform: scale(1.03);
        box-shadow: 0 4px 24px rgba(45,212,191,0.18);
    }}
    .rank-card.winner:hover {{
        transform: scale(1.05) translateY(-3px);
        box-shadow: 0 10px 36px rgba(45,212,191,0.28);
    }}

    /* Active / selected card */
    .rank-card.selected {{
        border-color: {t["accent"]} !important; border-width: 2px;
        border-bottom: none !important;
        box-shadow: 0 4px 24px rgba(45,212,191,0.30);
        transform: scale(1.03);
    }}

    /* Dim non-selected cards when one IS selected */
    .rank-card.dimmed {{
        opacity: 0.5;
        filter: grayscale(30%);
    }}
    .rank-card.dimmed:hover {{
        opacity: 0.85;
        filter: grayscale(0%);
    }}

    /* ── Card-action buttons (footer strip below each rank card) ── */
    [data-testid="stMainBlockContainer"] [data-testid="stButton"] button {{
        min-height: 34px !important;
        border: 1.5px solid {t["card_border"]} !important;
        border-radius: 0 0 12px 12px !important;
        background: {t["card_bg"]} !important;
        color: {t["accent"]} !important;
        font-size: 0.72rem !important;
        font-weight: 600 !important;
        letter-spacing: 0.04em !important;
        padding: 5px 0 !important;
        cursor: pointer !important;
        transition: background 0.2s, border-color 0.2s, color 0.2s !important;
        box-shadow: none !important;
    }}
    [data-testid="stMainBlockContainer"] [data-testid="stButton"] button:hover {{
        background: {t["accent"]} !important;
        border-color: {t["accent"]} !important;
        color: {t["page_bg"]} !important;
    }}
    [data-testid="stMainBlockContainer"] [data-testid="stButton"] button:focus {{
        box-shadow: none !important;
    }}

    /* ── Score progress bar ── */
    .score-bar-bg {{
        width: 80%; height: 5px; background: {t["card_border"]};
        border-radius: 3px; overflow: hidden; margin: 6px auto 0;
    }}
    .score-bar-fill {{ height: 100%; border-radius: 3px; transition: width 0.4s ease; }}

    /* ── Rank badge ── */
    .rank-badge {{
        display: inline-flex; align-items: center; justify-content: center;
        gap: 3px; padding: 3px 10px; border-radius: 20px;
        font-size: 0.72rem; font-weight: 700; letter-spacing: 0.06em;
        text-transform: uppercase; line-height: 1.4;
    }}

    /* ── Blueprint cards ── */
    .bp-card {{
        background: {t["card_bg"]}; border: 1px solid {t["card_border"]};
        border-radius: 12px; padding: 16px; text-align: center;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        transition: box-shadow 0.25s, transform 0.25s, border-color 0.25s;
    }}
    .bp-card:hover {{
        box-shadow: 0 6px 20px rgba(15,118,110,0.16);
        transform: translateY(-2px);
        border-color: {t["accent"]};
    }}

    /* ── Sidebar weight bars ── */
    .w-row  {{ display:flex; align-items:center; gap:8px; margin:4px 0;
               font-size:0.82rem; color:{t["subtext"]}; }}
    .w-bg   {{ flex:1; height:6px; background:{t["card_border"]}; border-radius:3px; overflow:hidden; }}
    .w-fill {{ height:100%; border-radius:3px; }}

    /* ── Theme icon button (moon / sun) ── */
    section[data-testid="stSidebar"] [data-testid="stButton"] button {{
        background: transparent !important;
        border: 1.5px solid {t["card_border"]} !important;
        border-radius: 8px !important;
        padding: 2px 6px !important;
        font-size: 1.1rem !important;
        line-height: 1.4 !important;
        min-height: 32px !important;
        width: 100% !important;
        color: {t["text"]} !important;
        box-shadow: none !important;
        transition: background 0.15s, border-color 0.15s !important;
    }}
    section[data-testid="stSidebar"] [data-testid="stButton"] button:hover {{
        background: {t["card_border"]} !important;
        border-color: {t["accent"]} !important;
    }}

    /* ── Detailed Analytical View ── */
    .detail-section {{
        background: {t["card_bg"]};
        border: 2px solid {t["accent"]};
        border-radius: 14px;
        padding: 24px 28px;
        margin-top: 8px;
    }}
    .detail-header {{
        display: flex;
        align-items: center;
        gap: 12px;
        margin-bottom: 0;
        padding-bottom: 14px;
        border-bottom: 1px solid {t["divider"]};
    }}
    .detail-header-title {{
        font-size: clamp(1rem, 2vw, 1.25rem);
        font-weight: 700;
        color: {t["text"]};
        flex: 1;
    }}
    .detail-header-badge {{
        display: inline-flex;
        align-items: center;
        gap: 4px;
        padding: 3px 10px;
        border-radius: 20px;
        font-size: 0.72rem;
        font-weight: 700;
        letter-spacing: 0.05em;
    }}
    .pros-cons-grid {{
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 14px;
        margin-top: 12px;
    }}
    .pros-cons-col {{
        background: {t["page_bg"]};
        border: 1px solid {t["card_border"]};
        border-radius: 10px;
        padding: 14px 16px;
    }}
    .pros-cons-col h4 {{
        font-size: 0.82rem;
        font-weight: 700;
        margin: 0 0 10px 0;
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }}
    .pros-cons-col ul {{
        margin: 0;
        padding-left: 18px;
    }}
    .pros-cons-col li {{
        font-size: 0.82rem !important;
        color: {t["text"]} !important;
        line-height: 1.55;
        margin-bottom: 4px;
    }}
    .eng-desc p {{
        color: {t["text"]} !important;
        font-size: 0.88rem !important;
        line-height: 1.6 !important;
    }}
    .eng-desc strong {{
        color: {t["accent"]} !important;
    }}

    /* ── Misc ── */
    div[data-testid="stDecoration"] {{ display: none; }}
    footer {{ display: none; }}
    </style>
    """


st.markdown(_build_css(T), unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Helper — load SVG blueprint as Base64 <img> (display only, never parsed)
# ---------------------------------------------------------------------------

def _svg_img(name: str, width: str = "100%", max_h: str = "180px") -> str:
    path = _ROOT / BLUEPRINT_PATHS.get(name, "")
    if path.exists():
        mime = "image/png" if path.suffix.lower() == ".png" else "image/svg+xml"
        b64 = base64.b64encode(path.read_bytes()).decode()
        return (
            f'<img src="data:{mime};base64,{b64}" '
            f'width="{width}" style="max-height:{max_h};object-fit:contain;" '
            f'alt="{name} schematic"/>'
        )
    return f'<p style="color:{T["muted"]};font-size:0.78rem">Blueprint not found</p>'


def _alt_color(name: str) -> str:
    """Return the alternative colour appropriate for the active theme."""
    if dark_mode:
        return ALTERNATIVE_COLORS_DARK.get(name, "#e2e8f0")
    return ALTERNATIVE_COLORS.get(name, "#0f766e")


_RANK_BADGE_COLORS = {
    1: ("#fbbf24", "#78350f"),  # gold bg, dark text
    2: ("#cbd5e1", "#1e293b"),  # silver bg, dark text
    3: ("#d6a06c", "#422006"),  # bronze bg, dark text
}
_RANK_ICONS = {1: "\U0001F3C6", 2: "\U0001F948", 3: "\U0001F949"}


# ---------------------------------------------------------------------------
# Sidebar — criteria weight sliders (continued after theme toggle)
# ---------------------------------------------------------------------------

with st.sidebar:
    # ── Context selector ─────────────────────────────────────────────────────
    st.markdown(
        f"<hr style='margin:10px 0;border-color:{T['divider']}'>"
        f"<p style='color:{T['text']};font-weight:700;font-size:1rem;margin-bottom:4px'>"
        "Task Context</p>"
        f"<p style='color:{T['muted']};font-size:0.78rem;margin-bottom:8px'>"
        "Select the interchange type category to compare alternatives.</p>",
        unsafe_allow_html=True,
    )
    selected_context: str = st.selectbox(
        "Select task context",
        options=list(INTERCHANGE_DATA.keys()),
        label_visibility="collapsed",
    )

    # ── Criteria weights ─────────────────────────────────────────────────────
    st.markdown(
        f"<hr style='margin:10px 0;border-color:{T['divider']}'>"
        f"<p style='color:{T['text']};font-weight:700;font-size:1rem;margin-bottom:4px'>"
        "Criteria Weights</p>"
        f"<p style='color:{T['muted']};font-size:0.78rem;margin-bottom:12px'>"
        "Adjust slider values. Weights are auto-normalised to sum to 1.0.</p>",
        unsafe_allow_html=True,
    )

    w_cost = st.slider("Construction Cost  —  Minimize",      0, 100, 30, 5, format="%d%%")
    w_area = st.slider("Land Area  —  Minimize",              0, 100, 20, 5, format="%d%%")
    w_cap  = st.slider("Throughput / Capacity  —  Maximize",  0, 100, 25, 5, format="%d%%")
    w_safe = st.slider("Safety Index  —  Maximize",           0, 100, 25, 5, format="%d%%")

    raw_w: dict[str, float] = {
        "construction_cost_mln": float(w_cost),
        "land_area_hectares":    float(w_area),
        "throughput_vph":        float(w_cap),
        "safety_index":          float(w_safe),
    }
    total_raw = sum(raw_w.values())

    if total_raw == 0.0:
        st.warning("All weights are zero — set at least one above 0.")
        norm_w: dict[str, float] = {k: 0.25 for k in raw_w}
    else:
        norm_w = {k: v / total_raw for k, v in raw_w.items()}

    # ── Project Parameters ────────────────────────────────────────────────
    st.markdown(
        f"<hr style='margin:10px 0;border-color:{T['divider']}'>"
        f"<p style='color:{T['text']};font-weight:700;font-size:1rem;margin-bottom:4px'>"
        "Project Parameters</p>"
        f"<p style='color:{T['muted']};font-size:0.78rem;margin-bottom:12px'>"
        "Define site-specific constraints and traffic characteristics.</p>",
        unsafe_allow_html=True,
    )

    param_design_speed = st.select_slider(
        "Design Speed (km/h)",
        options=[60, 80, 100, 120, 140],
        value=100,
    )
    param_aadt = st.number_input(
        "AADT (Annual Average Daily Traffic)",
        min_value=1_000,
        max_value=200_000,
        value=45_000,
        step=5_000,
        help="Estimated average daily traffic volume on the main route.",
    )
    param_peak_factor = st.slider(
        "Peak Hour Factor (K-factor %)",
        min_value=5,
        max_value=20,
        value=10,
        step=1,
        format="%d%%",
        help="Percentage of AADT occurring during the peak hour.",
    )
    param_num_lanes = st.select_slider(
        "Number of Through Lanes (per direction)",
        options=[1, 2, 3, 4, 5],
        value=2,
    )
    param_budget = st.number_input(
        "Budget Constraint (M USD)",
        min_value=0.0,
        max_value=500.0,
        value=100.0,
        step=5.0,
        help="Maximum allowable construction budget.",
    )
    param_land_limit = st.number_input(
        "Available Land (ha)",
        min_value=0.0,
        max_value=100.0,
        value=30.0,
        step=1.0,
        help="Maximum available right-of-way area.",
    )
    param_terrain = st.selectbox(
        "Terrain Type",
        options=["Flat", "Rolling", "Mountainous"],
        index=0,
    )
    param_env_sensitivity = st.select_slider(
        "Environmental Sensitivity",
        options=["Low", "Medium", "High", "Critical"],
        value="Medium",
        help="Level of environmental constraints at the project site.",
    )

    st.markdown(
        f"<hr style='margin:10px 0;border-color:{T['divider']}'>"
        f"<p style='color:{T['muted']};font-size:0.78rem;margin-bottom:6px'>"
        "Normalised weights (sum = 1.0)</p>",
        unsafe_allow_html=True,
    )

    _BAR_COLORS = {
        "construction_cost_mln": "#0f766e",
        "land_area_hectares":    "#ea580c",
        "throughput_vph":        "#7c3aed",
        "safety_index":          "#1d4ed8",
    }
    for key, nw in norm_w.items():
        pct   = int(nw * 100)
        label = CRITERION_LABELS[key]
        color = _BAR_COLORS[key]
        st.markdown(
            f"<div class='w-row'>"
            f"<span style='min-width:118px;white-space:nowrap;overflow:hidden'>{label}</span>"
            f"<div class='w-bg'><div class='w-fill' style='width:{pct}%;background:{color}'></div></div>"
            f"<span style='min-width:34px;text-align:right'>{nw:.2f}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

    total_pct = sum(raw_w.values())
    pct_color = T["accent"] if abs(total_pct - 100) <= 1 else "#ea580c"
    st.markdown(
        f"<p style='font-size:0.8rem;color:{pct_color};margin-top:8px'>"
        f"Raw slider total: {total_pct:.0f}%</p>",
        unsafe_allow_html=True,
    )

    st.markdown(f"<hr style='border-color:{T['divider']}'>", unsafe_allow_html=True)
    st.caption("Data: FHWA (2023) · HCM 7th Ed. · PIARC Road Safety Manual (2022).")

# ---------------------------------------------------------------------------
# Build filtered alternatives and run WSM evaluation
# ---------------------------------------------------------------------------

filtered_alternatives = get_alternatives_for_context(selected_context)

if st.session_state.get("_prev_context") != selected_context:
    st.session_state["selected_detail"] = None
    st.session_state["_prev_context"] = selected_context

dss     = DecisionSupportSystem(CRITERIA)
results: list[EvaluationResult] = dss.evaluate(filtered_alternatives, weights=norm_w)

_ORDINALS = ["1st", "2nd", "3rd", "4th", "5th", "6th", "7th", "8th"]
_RANKS = _ORDINALS[: len(results)]

# ---------------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------------

st.markdown(
    f"<h1 style='color:{T['text']}'>Transport Interchange Decision Support System</h1>"
    f"<p style='color:{T['muted']};font-size:0.88rem;margin-top:-6px;margin-bottom:20px'>"
    "Multi-Criteria Decision Analysis (MCDA)  ·  Weighted Sum Model (WSM)"
    "</p>",
    unsafe_allow_html=True,
)

# keep selected_context in scope for tab blocks below  (already set in sidebar)

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

tab_eval, tab_gallery, tab_method = st.tabs(
    ["DSS Evaluation", "Blueprint Gallery", "Methodology"]
)

# ===========================================================================
# TAB 1 — DSS Evaluation
# ===========================================================================

with tab_eval:

    # ── Context badge + winner success banner ────────────────────────────────
    _winner      = results[0]
    _winner_color = _alt_color(_winner.alternative_name)
    st.markdown(
        f"<div style='display:inline-block;background:{T['accent_light']};"
        f"border:1px solid {T['winner_border']};border-radius:8px;"
        f"padding:4px 12px;margin-bottom:10px'>"
        f"<span style='color:{T['muted']};font-size:0.78rem;font-weight:600;"
        f"letter-spacing:0.05em;text-transform:uppercase'>Context: </span>"
        f"<span style='color:{T['accent']};font-weight:700;font-size:0.88rem'>"
        f"{selected_context}</span></div>",
        unsafe_allow_html=True,
    )
    st.success(
        f"**Recommended: {_winner.alternative_name}** — "
        f"WSM Score {_winner.total_score:.4f}  "
        f"(rank #1 of {len(results)} alternatives in \"{selected_context}\")"
    )

    # ── Project parameters summary row ────────────────────────────────────────
    _p_cols = st.columns(4)
    _p_cols[0].metric("Design Speed", f"{param_design_speed} km/h")
    _p_cols[1].metric("AADT", f"{param_aadt:,}")
    _p_cols[2].metric("Budget Limit", f"${param_budget:.0f}M")
    _p_cols[3].metric("Land Limit", f"{param_land_limit:.0f} ha")

    _p_cols2 = st.columns(4)
    _p_cols2[0].metric("Peak Hour Factor", f"{param_peak_factor}%")
    _p_cols2[1].metric("Lanes / Direction", str(param_num_lanes))
    _p_cols2[2].metric("Terrain", param_terrain)
    _p_cols2[3].metric("Env. Sensitivity", param_env_sensitivity)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Ranking banner ───────────────────────────────────────────────────────
    st.subheader("WSM Score Ranking")
    st.caption("Click any card to view its detailed engineering profile, metrics, and real-world map.")

    _max_score = results[0].total_score if results else 1.0
    _current_sel = st.session_state.get("selected_detail")
    _any_selected = _current_sel is not None
    rank_cols = st.columns(len(results))

    for col, res, rank_label in zip(rank_cols, results, _RANKS):
        color      = _alt_color(res.alternative_name)
        _is_active = (_current_sel == res.alternative_name)
        bp_html    = _svg_img(res.alternative_name, width="92%", max_h="140px")
        bar_pct    = int((res.total_score / _max_score) * 100) if _max_score > 0 else 0

        card_class = "rank-card"
        if res.rank == 1:
            card_class += " winner"
        if _is_active:
            card_class += " selected"
        elif _any_selected:
            card_class += " dimmed"

        badge_bg, badge_fg = _RANK_BADGE_COLORS.get(res.rank, (T["card_border"], T["subtext"]))
        badge_icon = _RANK_ICONS.get(res.rank, "")
        badge_html = (
            f"<span class='rank-badge' style='background:{badge_bg};color:{badge_fg}'>"
            f"{badge_icon} {rank_label}</span>"
        )

        with col:
            st.markdown(
                f"<div class='{card_class}'>"
                f"<div style='margin-bottom:6px'>{badge_html}</div>"
                f"<div style='color:{color};font-weight:700;font-size:0.95rem;margin:4px 0 8px'>"
                f"{res.alternative_name}</div>"
                f"{bp_html}"
                f"<div style='color:{T['text']};font-size:1.35rem;font-weight:800;margin-top:10px'>"
                f"{res.total_score:.4f}</div>"
                f"<div style='color:{T['muted']};font-size:0.7rem'>WSM Score</div>"
                f"<div class='score-bar-bg'>"
                f"<div class='score-bar-fill' style='width:{bar_pct}%;background:{color}'></div>"
                f"</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

            _btn_label = "\u2716  Close Details" if _is_active else "\u2192  Detailed Analysis"
            if st.button(_btn_label, key=f"card_btn_{res.alternative_name}", use_container_width=True):
                if _is_active:
                    st.session_state["selected_detail"] = None
                else:
                    st.session_state["selected_detail"] = res.alternative_name
                st.rerun()

    # ── Detailed Analytical View — full-width, OUTSIDE the columns ────────────
    _selected_name = st.session_state.get("selected_detail")
    if _selected_name and _selected_name in [r.alternative_name for r in results]:
        _sel_res: EvaluationResult = next(
            r for r in results if r.alternative_name == _selected_name
        )
        _sel_info: dict = DETAILED_INTERCHANGE_INFO.get(_selected_name, {})
        _sel_color = _alt_color(_selected_name)
        _sel_rank_lbl = (
            _RANKS[_sel_res.rank - 1] if _sel_res.rank <= len(_RANKS)
            else f"#{_sel_res.rank}"
        )
        _d_badge_bg, _d_badge_fg = _RANK_BADGE_COLORS.get(
            _sel_res.rank, (T["card_border"], T["subtext"])
        )
        _d_badge_icon = _RANK_ICONS.get(_sel_res.rank, "")

        with st.container():
            st.markdown(
                f"<div class='detail-section'>"
                f"<div class='detail-header'>"
                f"<span class='detail-header-badge' "
                f"style='background:{_d_badge_bg};color:{_d_badge_fg}'>"
                f"{_d_badge_icon} {_sel_rank_lbl}</span>"
                f"<span class='detail-header-title' style='color:{_sel_color}'>"
                f"Detailed Analysis: {_selected_name}</span>"
                f"</div></div>",
                unsafe_allow_html=True,
            )

            # ── Row 1: criterion breakdown (full-width) ──────────────────
            _crit_cols = st.columns(len(dss.criterion_names()))
            for _ci, key in enumerate(dss.criterion_names()):
                crit_obj = next(c for c in CRITERIA if c.name == key)
                w_score  = _sel_res.weighted_scores[key]
                n_score  = _sel_res.normalised_values[key]
                raw_val  = _sel_res.raw_values[key]
                c_pct    = int(n_score * 100)
                with _crit_cols[_ci]:
                    st.markdown(
                        f"<div style='background:{T['card_bg']};border:1px solid {T['card_border']};"
                        f"border-radius:10px;padding:12px 14px'>"
                        f"<div style='color:{T['muted']};font-size:0.68rem;font-weight:600;"
                        f"text-transform:uppercase;letter-spacing:0.05em;margin-bottom:6px'>"
                        f"{CRITERION_LABELS[key]}</div>"
                        f"<div style='color:{T['text']};font-size:1.1rem;font-weight:700'>"
                        f"{raw_val} {crit_obj.unit}</div>"
                        f"<div class='score-bar-bg' style='width:100%;margin:8px 0 4px'>"
                        f"<div class='score-bar-fill' "
                        f"style='width:{c_pct}%;background:{_sel_color}'></div></div>"
                        f"<div style='display:flex;justify-content:space-between;"
                        f"font-size:0.65rem;color:{T['muted']}'>"
                        f"<span>norm {n_score:.3f}</span>"
                        f"<span>w\u00b7x\u0305 = {w_score:.4f}</span></div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )

            # ── Row 2: key metrics ───────────────────────────────────────
            _m1, _m2, _m3, _m4, _m5, _m6 = st.columns(6)
            _m1.metric("WSM Score", f"{_sel_res.total_score:.4f}")
            _m2.metric("Cost", f"${_sel_res.raw_values['construction_cost_mln']:.1f}M")
            _m3.metric("Throughput", f"{int(_sel_res.raw_values['throughput_vph']):,} vph")
            _m4.metric("Safety", f"{_sel_res.raw_values['safety_index']:.1f} / 10")
            _m5.metric("Land Area", f"{_sel_res.raw_values['land_area_hectares']:.1f} ha")
            _budget_ok = _sel_res.raw_values["construction_cost_mln"] <= param_budget
            _land_ok = _sel_res.raw_values["land_area_hectares"] <= param_land_limit
            _feas_text = "Feasible" if (_budget_ok and _land_ok) else "Over limit"
            _m6.metric("Feasibility", _feas_text)

            # ── Row 3: description + pros/cons (left) | map (right) ──────
            _col_info, _col_map = st.columns([3, 2], gap="large")

            with _col_info:
                st.markdown(
                    f"<p style='color:{T['muted']};font-size:0.7rem;font-weight:600;"
                    f"text-transform:uppercase;letter-spacing:0.06em;"
                    f"margin-bottom:8px'>Engineering Description</p>",
                    unsafe_allow_html=True,
                )
                if _sel_info.get("engineering_desc"):
                    st.markdown(
                        f"<div class='eng-desc'>"
                        f"{_sel_info['engineering_desc']}</div>",
                        unsafe_allow_html=True,
                    )
                else:
                    _alt_obj = next(
                        (a for a in filtered_alternatives
                         if a.name == _selected_name),
                        None,
                    )
                    if _alt_obj:
                        st.markdown(
                            f"<div class='eng-desc'>"
                            f"{_alt_obj.description}</div>",
                            unsafe_allow_html=True,
                        )

                _pros = _sel_info.get("pros", [])
                _cons = _sel_info.get("cons", [])
                if _pros or _cons:
                    _pros_li = "".join(f"<li>{p}</li>" for p in _pros)
                    _cons_li = "".join(f"<li>{c}</li>" for c in _cons)
                    st.markdown(
                        f"<div class='pros-cons-grid'>"
                        f"<div class='pros-cons-col'>"
                        f"<h4 style='color:{T['accent']}'>Advantages</h4>"
                        f"<ul>{_pros_li}</ul></div>"
                        f"<div class='pros-cons-col'>"
                        f"<h4 style='color:#ef4444'>Limitations</h4>"
                        f"<ul>{_cons_li}</ul></div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )

            with _col_map:
                _lat = _sel_info.get("lat", 40.0)
                _lon = _sel_info.get("lon", -74.0)
                _example = _sel_info.get("example_name", "Example location")

                _fmap = folium.Map(
                    location=[_lat, _lon],
                    zoom_start=15,
                    tiles=(
                        "https://server.arcgisonline.com/ArcGIS/rest/services"
                        "/World_Imagery/MapServer/tile/{z}/{y}/{x}"
                    ),
                    attr="Esri World Imagery",
                )
                folium.Marker(
                    [_lat, _lon],
                    popup=folium.Popup(
                        f"<b>{_selected_name}</b><br>{_example}",
                        max_width=260,
                    ),
                    tooltip=_example,
                    icon=folium.Icon(color="green", icon="road", prefix="fa"),
                ).add_to(_fmap)
                folium.CircleMarker(
                    [_lat, _lon],
                    radius=50,
                    color="#2dd4bf",
                    fill=True,
                    fill_opacity=0.10,
                    weight=2,
                ).add_to(_fmap)

                st_folium(
                    _fmap, height=400,
                    use_container_width=True, returned_objects=[],
                )

                st.markdown(
                    f"<p style='color:{T['text']};font-size:0.82rem;margin-top:6px'>"
                    f"<b>Real-world example:</b> {_example}</p>"
                    f"<p style='color:{T['muted']};font-size:0.75rem'>"
                    f"Coordinates: {_lat:.4f}\u00b0N, "
                    f"{abs(_lon):.4f}\u00b0{'W' if _lon < 0 else 'E'}"
                    f" \u00b7 Satellite imagery (Esri)</p>",
                    unsafe_allow_html=True,
                )

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Charts: radar (left) + score bar (right) ─────────────────────────────
    col_radar, col_bar = st.columns([5, 5], gap="medium")

    with col_radar:
        st.plotly_chart(
            create_radar_chart(
                results, CRITERION_LABELS, ALTERNATIVE_COLORS,
                top_n=min(2, len(results)), dark=dark_mode,
            ),
            use_container_width=True,
        )

    with col_bar:
        st.plotly_chart(
            create_wsm_bar_chart(results, ALTERNATIVE_COLORS, dark=dark_mode),
            use_container_width=True,
        )

    # ── Contribution breakdown ────────────────────────────────────────────────
    st.plotly_chart(
        create_contribution_stacked_bar(results, CRITERION_LABELS, dark=dark_mode),
        use_container_width=True,
    )

    st.markdown(f"<hr style='border-color:{T['divider']}'>", unsafe_allow_html=True)

    # ── Raw expert data table ─────────────────────────────────────────────────
    st.subheader("Criterion Values")

    raw_rows = []
    for res in results:
        rv = res.raw_values
        raw_rows.append({
            "Rank":               f"#{res.rank}",
            "Alternative":        res.alternative_name,
            "Cost (M USD)":       f"${rv['construction_cost_mln']:.1f} M",
            "Land Area (ha)":     f"{rv['land_area_hectares']:.1f} ha",
            "Throughput (vph)":   f"{int(rv['throughput_vph']):,}",
            "Safety Index":       f"{rv['safety_index']:.1f} / 10",
        })

    st.dataframe(
        pd.DataFrame(raw_rows).set_index("Rank"),
        use_container_width=True,
    )

    st.markdown(f"<hr style='border-color:{T['divider']}'>", unsafe_allow_html=True)

    # ── Normalised scores + weighted contributions table ──────────────────────
    st.subheader("Normalised Scores and Weighted Contributions")
    st.caption(
        "Min-Max normalisation maps each raw value to [0, 1].  "
        "Minimize criteria are inverted so 1.0 denotes the best performer on that criterion.  "
        "Cell format: normalised x\u0305\u1D62\u2C7c \u2192 weighted contribution w\u2C7c \xb7 x\u0305\u1D62\u2C7c."
    )

    score_rows = []
    for res in results:
        row: dict = {"Rank": f"#{res.rank}", "Alternative": res.alternative_name}
        for key in dss.criterion_names():
            crit_obj  = next(c for c in CRITERIA if c.name == key)
            dir_sym   = "Max" if crit_obj.direction == "maximize" else "Min"
            w_str     = f"{norm_w[key]:.2f}"
            col_label = f"{CRITERION_LABELS[key]}  [{dir_sym}, w={w_str}]"
            row[col_label] = (
                f"{res.normalised_values[key]:.3f}  \u2192  {res.weighted_scores[key]:.3f}"
            )
        row["WSM Score  S\u1D62"] = f"{res.total_score:.4f}"
        score_rows.append(row)

    st.dataframe(
        pd.DataFrame(score_rows).set_index("Rank"),
        use_container_width=True,
    )

# ===========================================================================
# TAB 2 — Blueprint Gallery
# ===========================================================================

with tab_gallery:

    st.subheader("Interchange Schematic Blueprints")

    # ── Project parameters summary ────────────────────────────────────────────
    st.markdown(
        f"<div style='background:{T['card_bg']};border:1px solid {T['card_border']};"
        f"border-radius:10px;padding:14px 18px;margin-bottom:18px'>"
        f"<div style='color:{T['muted']};font-size:0.72rem;font-weight:600;"
        f"letter-spacing:0.08em;text-transform:uppercase;margin-bottom:8px'>Project Parameters</div>"
        f"<div style='display:flex;flex-wrap:wrap;gap:16px'>"
        f"<span style='color:{T['subtext']};font-size:0.82rem'>Design Speed: <b style='color:{T['text']}'>{param_design_speed} km/h</b></span>"
        f"<span style='color:{T['subtext']};font-size:0.82rem'>AADT: <b style='color:{T['text']}'>{param_aadt:,}</b></span>"
        f"<span style='color:{T['subtext']};font-size:0.82rem'>Peak Factor: <b style='color:{T['text']}'>{param_peak_factor}%</b></span>"
        f"<span style='color:{T['subtext']};font-size:0.82rem'>Lanes: <b style='color:{T['text']}'>{param_num_lanes}/dir</b></span>"
        f"<span style='color:{T['subtext']};font-size:0.82rem'>Budget: <b style='color:{T['text']}'>${param_budget:.0f}M</b></span>"
        f"<span style='color:{T['subtext']};font-size:0.82rem'>Land: <b style='color:{T['text']}'>{param_land_limit:.0f} ha</b></span>"
        f"<span style='color:{T['subtext']};font-size:0.82rem'>Terrain: <b style='color:{T['text']}'>{param_terrain}</b></span>"
        f"<span style='color:{T['subtext']};font-size:0.82rem'>Env. Sensitivity: <b style='color:{T['text']}'>{param_env_sensitivity}</b></span>"
        f"</div></div>",
        unsafe_allow_html=True,
    )

    # ── Winner spotlight ──────────────────────────────────────────────────────
    winner     = results[0]
    winner_alt = next(a for a in filtered_alternatives if a.name == winner.alternative_name)
    w_color    = _alt_color(winner.alternative_name)

    _budget_ok = winner.raw_values["construction_cost_mln"] <= param_budget
    _land_ok   = winner.raw_values["land_area_hectares"] <= param_land_limit
    _feasibility = "Feasible" if (_budget_ok and _land_ok) else "Exceeds constraints"
    _feas_color  = T["accent"] if (_budget_ok and _land_ok) else "#ef4444"

    col_w, col_detail = st.columns([2, 5], gap="large")

    with col_w:
        st.markdown(
            f"<div style='background:{T['winner_bg']};border:2px solid {T['winner_border']};"
            f"border-radius:14px;padding:20px;text-align:center'>"
            f"<div style='color:{T['muted']};font-size:0.72rem;font-weight:600;"
            f"letter-spacing:0.08em;text-transform:uppercase;margin-bottom:4px'>Recommended</div>"
            f"<div style='color:{w_color};font-size:1.15rem;font-weight:800;margin-bottom:2px'>"
            f"{winner.alternative_name}</div>"
            f"<div style='color:{T['text']};font-size:1.6rem;font-weight:700'>WSM {winner.total_score:.4f}</div>"
            f"<div style='margin:14px 0'>{_svg_img(winner.alternative_name, '100%', '260px')}</div>"
            f"<div style='color:{_feas_color};font-size:0.78rem;font-weight:600;margin-top:6px'>"
            f"{_feasibility}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

    with col_detail:
        st.markdown(f"**{winner.alternative_name}** — Criterion Detail")
        st.markdown(
            f"<p style='color:{T['subtext']};font-size:0.87rem'>{winner_alt.description}</p>",
            unsafe_allow_html=True,
        )
        detail_rows = []
        for key in dss.criterion_names():
            crit_obj = next(c for c in CRITERIA if c.name == key)
            detail_rows.append({
                "Criterion":    CRITERION_LABELS[key],
                "Direction":    "Maximize" if crit_obj.direction == "maximize" else "Minimize",
                "Raw Value":    f"{winner.raw_values[key]} {crit_obj.unit}",
                "Normalised":   f"{winner.normalised_values[key]:.3f}",
                "Weight":       f"{norm_w[key]:.2f}",
                "Contribution": f"{winner.weighted_scores[key]:.4f}",
            })
        st.dataframe(
            pd.DataFrame(detail_rows),
            use_container_width=True,
            hide_index=True,
        )

    st.markdown(f"<hr style='border-color:{T['divider']}'>", unsafe_allow_html=True)

    # ── All alternatives in a responsive grid (max 4 cols) ───────────────────
    st.markdown(
        f"<p style='color:{T['subtext']};font-weight:600;margin-bottom:12px'>All Alternatives</p>",
        unsafe_allow_html=True,
    )
    _n_cols = min(len(results), 4)
    bp_cols = st.columns(_n_cols, gap="small")

    _gal_max_score = results[0].total_score if results else 1.0

    for col, res in zip(bp_cols, results):
        color    = _alt_color(res.alternative_name)
        rank_lbl = _RANKS[res.rank - 1]
        alt_obj  = next(a for a in filtered_alternatives if a.name == res.alternative_name)
        bar_pct  = int((res.total_score / _gal_max_score) * 100) if _gal_max_score > 0 else 0

        _b_ok = res.raw_values["construction_cost_mln"] <= param_budget
        _l_ok = res.raw_values["land_area_hectares"] <= param_land_limit
        _feas_badge = (
            f"<div style='color:{T['accent']};font-size:0.65rem;margin-top:4px'>&#10003; Feasible</div>"
            if (_b_ok and _l_ok)
            else f"<div style='color:#ef4444;font-size:0.65rem;margin-top:4px'>&#10007; Exceeds limits</div>"
        )

        badge_bg, badge_fg = _RANK_BADGE_COLORS.get(res.rank, (T["card_border"], T["subtext"]))
        badge_icon = _RANK_ICONS.get(res.rank, "")
        badge_html = (
            f"<span class='rank-badge' style='background:{badge_bg};color:{badge_fg}'>"
            f"{badge_icon} {rank_lbl}</span>"
        )

        with col:
            st.markdown(
                f"<div class='bp-card'>"
                f"<div style='margin-bottom:4px'>{badge_html}</div>"
                f"<div style='color:{color};font-weight:700;font-size:0.88rem;margin:4px 0'>"
                f"{res.alternative_name}</div>"
                f"<div style='color:{T['subtext']};font-size:0.75rem;margin-bottom:10px'>"
                f"WSM: <b style='color:{T['text']}'>{res.total_score:.4f}</b></div>"
                f"{_svg_img(res.alternative_name, '100%', '210px')}"
                f"<div class='score-bar-bg' style='margin-top:8px'>"
                f"<div class='score-bar-fill' style='width:{bar_pct}%;background:{color}'></div>"
                f"</div>"
                f"{_feas_badge}"
                f"<div style='color:{T['muted']};font-size:0.7rem;margin-top:6px'>"
                f"{alt_obj.description[:90]}\u2026"
                f"</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

# ===========================================================================
# TAB 3 — Methodology
# ===========================================================================

with tab_method:

    col_m1, col_m2 = st.columns([6, 4], gap="large")

    with col_m1:
        st.markdown(
            f"""
<span style="color:{T['text']}">

## Weighted Sum Model (WSM)

The composite priority score for alternative $i$ is computed as the weighted
sum of normalised criterion values:

$$S_i = \\sum_{{j=1}}^{{n}} w_j \\cdot \\bar{{x}}_{{ij}}$$

| Symbol | Definition |
|---|---|
| $S_i$ | Composite WSM score for alternative $i$, $S_i \\in [0, 1]$ |
| $n$ | Number of evaluation criteria |
| $w_j$ | Normalised weight for criterion $j$, with $\\sum_{{j=1}}^{{n}} w_j = 1$ |
| $\\bar{{x}}_{{ij}}$ | Min-Max normalised value of criterion $j$ for alternative $i$ |

---

## Min-Max Normalisation

Raw criterion values are mapped to the unit interval $[0, 1]$ according to
the direction of preference.

**Maximize** — higher raw value is preferred (e.g. throughput, safety):

$$\\bar{{x}}_{{ij}} = \\frac{{x_{{ij}} - \\min_j}}{{\\max_j - \\min_j}}$$

**Minimize** — lower raw value is preferred (e.g. cost, land area).
The scale is inverted so that a normalised score of 1.0 always represents
the best-performing alternative on that criterion:

$$\\bar{{x}}_{{ij}} = \\frac{{\\max_j - x_{{ij}}}}{{\\max_j - \\min_j}}$$

where $\\min_j$ and $\\max_j$ denote the minimum and maximum observed values
of criterion $j$ across all alternatives.

*Edge case:* when $\\max_j = \\min_j$ (all alternatives equal on criterion $j$),
the normalised score is set to $0.5$ to avoid division by zero without
introducing bias.

---

## Criteria and Data Sources

| Criterion | Direction | Unit | Source |
|---|---|---|---|
| Construction Cost | Minimize | M USD | FHWA Interchange Justification Report Guidelines (2023) |
| Land Area | Minimize | ha | TRB NCHRP Report 659 — Geometric Design of Freeway Ramps |
| Throughput | Maximize | veh/hr | HCM 7th Edition, Chapter 14 (Freeway Interchanges) |
| Safety Index | Maximize | 1–10 | PIARC Road Safety Manual (2019); AASHTO HSM (2022) |

---

## References

- Fishburn, P. C. (1967). Additive utilities with incomplete product sets.
  *Operations Research*, 15(3), 537–542.
- Triantaphyllou, E. (2000). *Multi-Criteria Decision Making Methods: A Comparative Study.*
  Kluwer Academic Publishers, Dordrecht.
- Transportation Research Board (2022). *Highway Capacity Manual, 7th Edition.*
- FHWA (2023). *Interchange Justification Report Guidelines.*
- PIARC (2019). *Road Safety Manual.*
- AASHTO (2022). *Highway Safety Manual, 2nd Edition.*

</span>
"""
        )

    with col_m2:
        st.markdown(
            f"<p style='font-weight:600;color:{T['text']};margin-bottom:8px'>Active Weight Profile</p>",
            unsafe_allow_html=True,
        )
        st.dataframe(
            pd.DataFrame([
                {"Criterion": CRITERION_LABELS[k], "Weight": f"{v:.0%}"}
                for k, v in norm_w.items()
            ]),
            use_container_width=True,
            hide_index=True,
        )

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown(
            f"<p style='font-weight:600;color:{T['text']};margin-bottom:8px'>Current Ranking</p>",
            unsafe_allow_html=True,
        )

        for res in results:
            color    = _alt_color(res.alternative_name)
            rank_lbl = _RANKS[res.rank - 1]
            badge_bg, badge_fg = _RANK_BADGE_COLORS.get(res.rank, (T["card_border"], T["subtext"]))
            badge_icon = _RANK_ICONS.get(res.rank, "")
            st.markdown(
                f"<div style='display:flex;align-items:center;gap:10px;"
                f"background:{T['card_bg']};border:1px solid {T['card_border']};"
                f"border-radius:8px;padding:9px 14px;margin-bottom:6px'>"
                f"<span class='rank-badge' style='background:{badge_bg};color:{badge_fg};font-size:0.68rem'>"
                f"{badge_icon} {rank_lbl}</span>"
                f"<span style='color:{color};font-weight:700;flex:1'>{res.alternative_name}</span>"
                f"<span style='color:{T['text']};font-weight:700'>{res.total_score:.4f}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

st.markdown(f"<hr style='border-color:{T['divider']}'>", unsafe_allow_html=True)
st.caption(
    "TDSS v3.0  ·  MCDA Engine: Weighted Sum Model (WSM)  ·  "
    "Charts: Plotly  ·  Data: FHWA / HCM 7th Ed. / PIARC 2022"
)
