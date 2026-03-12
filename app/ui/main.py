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
    ALTERNATIVES,
    BLUEPRINT_PATHS,
    CRITERIA,
    CRITERION_LABELS,
)
from app.ui.charts import (
    create_contribution_stacked_bar,
    create_radar_chart,
    create_wsm_bar_chart,
)

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
        border-radius: 14px; padding: 18px 10px; text-align: center;
        box-shadow: 0 1px 4px rgba(0,0,0,0.06);
        transition: box-shadow 0.2s, transform 0.2s;
    }}
    .rank-card:hover {{ box-shadow: 0 6px 20px rgba(15,118,110,0.16); transform: translateY(-2px); }}
    .rank-card.winner {{ border-color: {t["winner_border"]}; border-width: 2px; }}

    /* ── Blueprint cards ── */
    .bp-card {{
        background: {t["card_bg"]}; border: 1px solid {t["card_border"]};
        border-radius: 12px; padding: 16px; text-align: center;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
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
        b64 = base64.b64encode(path.read_bytes()).decode()
        return (
            f'<img src="data:image/svg+xml;base64,{b64}" '
            f'width="{width}" style="max-height:{max_h};object-fit:contain;" '
            f'alt="{name} schematic"/>'
        )
    return f'<p style="color:{T["muted"]};font-size:0.78rem">Blueprint not found</p>'


# ---------------------------------------------------------------------------
# Sidebar — criteria weight sliders (continued after theme toggle)
# ---------------------------------------------------------------------------

with st.sidebar:
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
# Run WSM evaluation
# ---------------------------------------------------------------------------

dss     = DecisionSupportSystem(CRITERIA)
results: list[EvaluationResult] = dss.evaluate(ALTERNATIVES, weights=norm_w)

_RANKS = ["1st", "2nd", "3rd", "4th"]

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

    # ── Ranking banner ───────────────────────────────────────────────────────
    st.subheader("WSM Score Ranking")
    rank_cols = st.columns(len(results))

    for col, res, rank_label in zip(rank_cols, results, _RANKS):
        color      = ALTERNATIVE_COLORS.get(res.alternative_name, T["accent"])
        card_class = "rank-card winner" if res.rank == 1 else "rank-card"
        bp_html    = _svg_img(res.alternative_name, width="88%", max_h="96px")

        with col:
            st.markdown(
                f"<div class='{card_class}'>"
                f"<div style='font-size:0.75rem;font-weight:600;color:{T['muted']};letter-spacing:0.05em;text-transform:uppercase'>"
                f"{rank_label}</div>"
                f"<div style='color:{color};font-weight:700;font-size:0.92rem;margin:6px 0 8px'>"
                f"{res.alternative_name}</div>"
                f"{bp_html}"
                f"<div style='color:{T['text']};font-size:1.35rem;font-weight:800;margin-top:10px'>"
                f"{res.total_score:.4f}</div>"
                f"<div style='color:{T['muted']};font-size:0.7rem'>WSM Score</div>"
                f"</div>",
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

    # ── Winner spotlight ──────────────────────────────────────────────────────
    winner     = results[0]
    winner_alt = next(a for a in ALTERNATIVES if a.name == winner.alternative_name)
    w_color    = ALTERNATIVE_COLORS.get(winner.alternative_name, T["accent"])

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
            f"<div style='margin:14px 0'>{_svg_img(winner.alternative_name, '100%', '160px')}</div>"
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

    # ── All four alternatives in a 4-column grid ──────────────────────────────
    st.markdown(
        f"<p style='color:{T['subtext']};font-weight:600;margin-bottom:12px'>All Alternatives</p>",
        unsafe_allow_html=True,
    )
    bp_cols = st.columns(4, gap="small")

    for col, res in zip(bp_cols, results):
        color   = ALTERNATIVE_COLORS.get(res.alternative_name, T["accent"])
        rank_lbl = _RANKS[res.rank - 1]
        alt_obj  = next(a for a in ALTERNATIVES if a.name == res.alternative_name)

        with col:
            st.markdown(
                f"<div class='bp-card'>"
                f"<div style='color:{T['muted']};font-size:0.7rem;font-weight:600;"
                f"letter-spacing:0.06em;text-transform:uppercase'>{rank_lbl}</div>"
                f"<div style='color:{color};font-weight:700;font-size:0.88rem;margin:4px 0'>"
                f"{res.alternative_name}</div>"
                f"<div style='color:{T['subtext']};font-size:0.75rem;margin-bottom:10px'>"
                f"WSM: <b style='color:{T['text']}'>{res.total_score:.4f}</b></div>"
                f"{_svg_img(res.alternative_name, '100%', '130px')}"
                f"<div style='color:{T['muted']};font-size:0.7rem;margin-top:8px'>"
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
            color    = ALTERNATIVE_COLORS.get(res.alternative_name, T["accent"])
            rank_lbl = _RANKS[res.rank - 1]
            st.markdown(
                f"<div style='display:flex;align-items:center;gap:10px;"
                f"background:{T['card_bg']};border:1px solid {T['card_border']};"
                f"border-radius:8px;padding:9px 14px;margin-bottom:6px'>"
                f"<span style='color:{T['muted']};font-size:0.78rem;min-width:28px'>{rank_lbl}</span>"
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
