"""
TDSS v3 — Transport Interchange Decision Support System
=======================================================
Decoupled Architecture: Streamlit VIEW layer.

This module is a *pure view*.  Its only responsibilities are:
  1. Collect weight preferences from the user (sliders).
  2. Call the Logic Layer (DecisionSupportSystem.evaluate).
  3. Render charts from the Chart Layer (app.ui.charts).
  4. Display static SVG blueprints as Base64-encoded <img> tags.

What this module does NOT do:
  - Parse SVG files for coordinates or geometry.
  - Compute road lengths, land areas, or construction costs.
  - Call svgpathtools, scipy, or shapely.

SVG files in ``assets/blueprints/`` are treated identically to JPEG
photographs — they are loaded as binary blobs and shown for visual context
only, with zero influence on any calculation.

Run
---
    streamlit run app/ui/main.py
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

# Ensure the project root is importable regardless of how Streamlit is launched.
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
    page_icon="🛣️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# CSS — modern light palette, responsive typography, mobile-friendly cards
# ---------------------------------------------------------------------------

st.markdown(
    """
    <style>
    /* ── Fonts & global reset ── */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', system-ui, sans-serif; }

    /* ── Page backgrounds ── */
    .stApp                                  { background-color: #f8fafc; }
    section[data-testid="stSidebar"]        { background-color: #ffffff;
                                              border-right: 1px solid #e2e8f0; }

    /* ── Responsive headings (clamp: min | fluid | max) ── */
    h1 { font-size: clamp(1.3rem, 3vw, 2rem)   !important;
         color: #0f172a !important; font-weight: 800 !important;
         line-height: 1.2 !important; }
    h2 { font-size: clamp(1.05rem, 2.2vw, 1.35rem) !important;
         color: #1e293b !important; font-weight: 700 !important; }
    h3 { font-size: clamp(0.9rem,  1.7vw, 1.1rem)  !important;
         color: #334155 !important; font-weight: 600 !important; }
    p, li, label { color: #475569 !important; font-size: clamp(0.82rem, 1.4vw, 0.95rem) !important; }

    /* ── Metric widgets ── */
    [data-testid="stMetric"] {
        background: #ffffff; border: 1px solid #e2e8f0;
        border-radius: 10px; padding: 12px 14px;
    }
    [data-testid="stMetricLabel"] { color: #64748b !important; font-size: 0.78rem !important; }
    [data-testid="stMetricValue"] { color: #0f172a !important; font-weight: 700 !important; }

    /* ── DataFrames ── */
    .stDataFrame { background: #ffffff; border-radius: 8px; border: 1px solid #e2e8f0; }

    /* ── Tab nav ── */
    button[data-baseweb="tab"]                         { color: #64748b !important; font-weight: 500 !important; }
    button[data-baseweb="tab"][aria-selected="true"]   { color: #0f766e !important; font-weight: 700 !important;
                                                          border-bottom: 2px solid #0f766e !important; }

    /* ── Rank cards ── */
    .rank-card {
        background: #ffffff; border: 1px solid #e2e8f0;
        border-radius: 14px; padding: 18px 12px;
        text-align: center;
        box-shadow: 0 1px 4px rgba(15,23,42,0.06);
        transition: box-shadow 0.2s, transform 0.2s;
    }
    .rank-card:hover { box-shadow: 0 6px 20px rgba(15,118,110,0.14); transform: translateY(-2px); }
    .rank-card.winner { border-color: #0f766e; border-width: 2px;
                        box-shadow: 0 4px 16px rgba(15,118,110,0.18); }

    /* ── Blueprint cards ── */
    .bp-card {
        background: #ffffff; border: 1px solid #e2e8f0;
        border-radius: 12px; padding: 16px; text-align: center;
        box-shadow: 0 1px 3px rgba(15,23,42,0.05);
    }

    /* ── Sidebar weight bars ── */
    .w-row   { display:flex; align-items:center; gap:8px; margin:4px 0;
               font-size:0.82rem; color:#334155; }
    .w-bg    { flex:1; height:6px; background:#e2e8f0; border-radius:3px; overflow:hidden; }
    .w-fill  { height:100%; border-radius:3px; }

    /* ── Alert / info box ── */
    .arch-note {
        background: #f0fdfa; border-left: 4px solid #0f766e;
        border-radius: 6px; padding: 10px 14px; margin-bottom: 14px;
        font-size: 0.85rem; color: #134e4a;
    }

    /* ── Misc chrome hiding ── */
    div[data-testid="stDecoration"] { display: none; }
    footer { display: none; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Helper — load an SVG file as a Base64 <img> tag (display only, no parsing)
# ---------------------------------------------------------------------------

def _svg_img(name: str, width: str = "100%", max_h: str = "180px") -> str:
    """
    Return an HTML <img> element embedding the named blueprint SVG as Base64.
    The file is opened as a binary blob; its path data is never interpreted.
    """
    rel  = BLUEPRINT_PATHS.get(name, "")
    path = _ROOT / rel
    if path.exists():
        b64 = base64.b64encode(path.read_bytes()).decode()
        return (
            f'<img src="data:image/svg+xml;base64,{b64}" '
            f'width="{width}" style="max-height:{max_h};object-fit:contain;" '
            f'alt="{name} schematic blueprint"/>'
        )
    return (
        f'<p style="color:#94a3b8;font-size:0.78rem;padding:20px 0">'
        f'Blueprint not found:<br><code>{rel}</code></p>'
    )


# ---------------------------------------------------------------------------
# Sidebar — criteria weight controls
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown(
        "<h2 style='color:#0f172a;font-size:1.05rem;margin-bottom:2px'>⚖️ Criteria Weights</h2>"
        "<p style='color:#94a3b8;font-size:0.78rem;margin-bottom:14px'>"
        "Adjust slider values. Weights are auto-normalised so they always sum to 1.0.</p>",
        unsafe_allow_html=True,
    )

    w_cost = st.slider("💰 Construction Cost  ▼  Minimize", 0, 100, 30, 5, format="%d%%")
    w_area = st.slider("🗺️  Land Area  ▼  Minimize",        0, 100, 20, 5, format="%d%%")
    w_cap  = st.slider("🚗 Throughput / Capacity  ▲  Maximize", 0, 100, 25, 5, format="%d%%")
    w_safe = st.slider("🛡️  Safety Index  ▲  Maximize",     0, 100, 25, 5, format="%d%%")

    raw_w: dict[str, float] = {
        "construction_cost_mln": float(w_cost),
        "land_area_hectares":    float(w_area),
        "throughput_vph":        float(w_cap),
        "safety_index":          float(w_safe),
    }
    total_raw = sum(raw_w.values())

    if total_raw == 0.0:
        st.warning("All weights are zero — set at least one above 0.", icon="⚠️")
        norm_w: dict[str, float] = {k: 0.25 for k in raw_w}
    else:
        norm_w = {k: v / total_raw for k, v in raw_w.items()}

    st.markdown("<hr style='margin:12px 0;border-color:#e2e8f0'>", unsafe_allow_html=True)
    st.markdown(
        "<p style='color:#94a3b8;font-size:0.78rem;margin-bottom:6px'>"
        "Normalised weights (Σ = 1.0)</p>",
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
            f"<span style='min-width:118px;overflow:hidden;white-space:nowrap'>{label}</span>"
            f"<div class='w-bg'><div class='w-fill' style='width:{pct}%;background:{color}'></div></div>"
            f"<span style='min-width:34px;text-align:right'>{nw:.2f}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

    total_pct  = sum(raw_w.values())
    pct_color  = "#0f766e" if abs(total_pct - 100) <= 1 else "#ea580c"
    st.markdown(
        f"<p style='font-size:0.8rem;color:{pct_color};margin-top:8px'>"
        f"Raw slider total: {total_pct:.0f}%</p>",
        unsafe_allow_html=True,
    )

    st.markdown("<hr style='border-color:#e2e8f0'>", unsafe_allow_html=True)
    st.caption(
        "Data: FHWA (2023) · HCM 7th Ed. · PIARC Road Safety Manual (2022).\n"
        "All values are expert-preset constants — no SVG parsing is performed."
    )

# ---------------------------------------------------------------------------
# Run WSM evaluation (pure Logic Layer call)
# ---------------------------------------------------------------------------

dss     = DecisionSupportSystem(CRITERIA)
results: list[EvaluationResult] = dss.evaluate(ALTERNATIVES, weights=norm_w)

_MEDALS = ["🥇", "🥈", "🥉", "4️⃣"]

# ---------------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------------

st.markdown(
    "<h1>🛣️ Transport Interchange Decision Support System</h1>"
    "<p style='color:#64748b;font-size:0.88rem;margin-top:-6px;margin-bottom:18px'>"
    "Multi-Criteria Decision Analysis (MCDA)  ·  Weighted Sum Model (WSM)  "
    "·  <b style=\"color:#0f766e\">Decoupled Architecture</b>"
    "</p>",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

tab_eval, tab_gallery, tab_method = st.tabs(
    ["📊 DSS Evaluation", "🖼️ Blueprint Gallery", "📖 Methodology"]
)

# ===========================================================================
# TAB 1 — DSS Evaluation
# ===========================================================================

with tab_eval:

    # ── Ranking banner ───────────────────────────────────────────────────────
    st.subheader("WSM Score Ranking")
    rank_cols = st.columns(len(results))

    for col, res, medal in zip(rank_cols, results, _MEDALS):
        color      = ALTERNATIVE_COLORS.get(res.alternative_name, "#0f766e")
        card_class = "rank-card winner" if res.rank == 1 else "rank-card"
        alt_obj    = next(a for a in ALTERNATIVES if a.name == res.alternative_name)
        bp_html    = _svg_img(res.alternative_name, width="90%", max_h="100px")

        with col:
            st.markdown(
                f"<div class='{card_class}'>"
                f"<div style='font-size:1.6rem'>{medal}</div>"
                f"<div style='color:{color};font-weight:700;font-size:0.88rem;margin:4px 0'>"
                f"{res.alternative_name}</div>"
                f"{bp_html}"
                f"<div style='color:#0f172a;font-size:1.4rem;font-weight:800;margin-top:8px'>"
                f"{res.total_score:.4f}</div>"
                f"<div style='color:#94a3b8;font-size:0.7rem'>WSM Score</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Charts: radar (left) + score bar (right) ─────────────────────────────
    col_radar, col_bar = st.columns([5, 5], gap="medium")

    with col_radar:
        top_n = min(2, len(results))
        st.plotly_chart(
            create_radar_chart(results, CRITERION_LABELS, ALTERNATIVE_COLORS, top_n=top_n),
            use_container_width=True,
        )

    with col_bar:
        st.plotly_chart(
            create_wsm_bar_chart(results, ALTERNATIVE_COLORS),
            use_container_width=True,
        )

    # ── Contribution breakdown ────────────────────────────────────────────────
    st.plotly_chart(
        create_contribution_stacked_bar(results, CRITERION_LABELS),
        use_container_width=True,
    )

    st.markdown("---")

    # ── Raw expert data table ─────────────────────────────────────────────────
    st.subheader("Expert-Sourced Criterion Values")
    st.markdown(
        "<div class='arch-note'>"
        "All values below are <b>predefined expert constants</b> from published design guidance. "
        "No SVG geometry parsing is performed at any point in this application."
        "</div>",
        unsafe_allow_html=True,
    )

    raw_rows = []
    for res in results:
        rv = res.raw_values
        raw_rows.append({
            "Rank":               f"#{res.rank}  {_MEDALS[res.rank - 1]}",
            "Alternative":        res.alternative_name,
            "Cost (M USD) ▼":     f"${rv['construction_cost_mln']:.1f} M",
            "Land Area (ha) ▼":   f"{rv['land_area_hectares']:.1f} ha",
            "Throughput (vph) ▲": f"{int(rv['throughput_vph']):,} vph",
            "Safety Index ▲":     f"{rv['safety_index']:.1f} / 10",
        })

    st.dataframe(
        pd.DataFrame(raw_rows).set_index("Rank"),
        use_container_width=True,
    )

    st.markdown("---")

    # ── Normalised scores + weighted contributions table ──────────────────────
    st.subheader("MCDA Normalised Scores & Weighted Contributions")
    st.caption(
        "Min-Max normalisation maps each raw value to [0, 1].  "
        "Minimize criteria are inverted so 1.0 always denotes the best performer.  "
        "Cell format: normalised x̄_ij  →  weighted contribution w_j · x̄_ij."
    )

    score_rows = []
    for res in results:
        row: dict = {"Rank": f"#{res.rank}", "Alternative": res.alternative_name}
        for key in dss.criterion_names():
            crit_obj  = next(c for c in CRITERIA if c.name == key)
            dir_icon  = "▲" if crit_obj.direction == "maximize" else "▼"
            w_str     = f"{norm_w[key]:.2f}"
            col_label = f"{dir_icon} {CRITERION_LABELS[key]} [w={w_str}]"
            row[col_label] = (
                f"{res.normalised_values[key]:.3f}  →  {res.weighted_scores[key]:.3f}"
            )
        row["WSM Score  S_i"] = f"{res.total_score:.4f}"
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
    st.markdown(
        "<div class='arch-note'>"
        "SVG files are loaded as <code>Base64-encoded &lt;img&gt;</code> tags and shown "
        "for <b>visual context only</b>. They are never parsed, measured, or used in "
        "any formula — a strict boundary of the Decoupled Architecture."
        "</div>",
        unsafe_allow_html=True,
    )

    # ── Winner spotlight ──────────────────────────────────────────────────────
    winner      = results[0]
    winner_alt  = next(a for a in ALTERNATIVES if a.name == winner.alternative_name)
    winner_col  = ALTERNATIVE_COLORS.get(winner.alternative_name, "#0f766e")

    col_w, col_detail = st.columns([2, 5], gap="large")

    with col_w:
        st.markdown(
            f"<div style='background:#f0fdfa;border:2px solid {winner_col};"
            f"border-radius:14px;padding:20px;text-align:center'>"
            f"<div style='font-size:2.4rem'>🥇</div>"
            f"<div style='color:{winner_col};font-size:1.15rem;font-weight:800;margin-bottom:2px'>"
            f"{winner.alternative_name}</div>"
            f"<div style='color:#0f172a;font-size:1.7rem;font-weight:700'>WSM {winner.total_score:.4f}</div>"
            f"<div style='color:#64748b;font-size:0.78rem;margin-bottom:14px'>Recommended Alternative</div>"
            f"{_svg_img(winner.alternative_name, '100%', '160px')}"
            f"</div>",
            unsafe_allow_html=True,
        )

    with col_detail:
        st.markdown(f"**{winner.alternative_name}** — Full Criterion Detail")
        st.markdown(
            f"<p style='color:#64748b;font-size:0.87rem'>{winner_alt.description}</p>",
            unsafe_allow_html=True,
        )
        detail_rows = []
        for key in dss.criterion_names():
            crit_obj = next(c for c in CRITERIA if c.name == key)
            detail_rows.append({
                "Criterion":    CRITERION_LABELS[key],
                "Direction":    "▲ Maximize" if crit_obj.direction == "maximize" else "▼ Minimize",
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

    st.markdown("---")

    # ── All four alternatives in a responsive 4-column grid ───────────────────
    st.markdown("**All Alternatives — Schematic Overview**")
    bp_cols = st.columns(4, gap="small")

    for col, res in zip(bp_cols, results):
        color   = ALTERNATIVE_COLORS.get(res.alternative_name, "#0f766e")
        medal   = _MEDALS[res.rank - 1]
        alt_obj = next(a for a in ALTERNATIVES if a.name == res.alternative_name)

        with col:
            st.markdown(
                f"<div class='bp-card'>"
                f"<div style='font-size:1.3rem'>{medal}</div>"
                f"<div style='color:{color};font-weight:700;font-size:0.88rem;margin:4px 0'>"
                f"{res.alternative_name}</div>"
                f"<div style='color:#475569;font-size:0.75rem;margin-bottom:10px'>"
                f"WSM: <b>{res.total_score:.4f}</b></div>"
                f"{_svg_img(res.alternative_name, '100%', '140px')}"
                f"<div style='color:#94a3b8;font-size:0.7rem;margin-top:8px;'>"
                f"{alt_obj.description[:90]}…"
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
            """
## Decoupled Architecture

This system enforces a **strict three-layer separation** between data,
logic, and presentation:

| Layer | Module | Responsibility |
|---|---|---|
| **Data** | `app/data/interchange_data.py` | Expert constants; zero I/O |
| **Logic** | `app/application/dss_engine.py` | Pure WSM maths; zero UI / data |
| **View** | `app/ui/main.py` | Streamlit rendering; zero calculations |
| **Charts** | `app/ui/charts.py` | Plotly figures; stateless functions |

SVG files in `assets/blueprints/` are **static visual assets** — loaded
via `base64.b64encode` and displayed as `<img>` tags.  They are never
parsed, measured, or supplied as inputs to any formula.  This mirrors
how a published academic report uses a figure: the diagram illustrates
the text, but the numbers come from cited data sources.

---

## Weighted Sum Model (WSM)

The composite priority score for alternative *i* is:

$$S_i = \\sum_{j=1}^{n} w_j \\cdot \\bar{x}_{ij}$$

where $w_j$ is the normalised weight for criterion $j$
($\\sum_j w_j = 1$), and $\\bar{x}_{ij}$ is the Min-Max normalised value.

### Min-Max Normalisation

**Maximize** criterion (higher raw value = better outcome):

$$\\bar{x}_{ij} = \\frac{x_{ij} - \\min_j}{\\max_j - \\min_j}$$

**Minimize** criterion (lower raw value = better outcome — scale inverted):

$$\\bar{x}_{ij} = \\frac{\\max_j - x_{ij}}{\\max_j - \\min_j}$$

*Edge case:* if $\\max_j = \\min_j$ (all alternatives identical on one
criterion), the normalised score is set to $0.5$ (neutral midpoint) to
prevent division-by-zero without introducing artificial bias.

---

## Data Sources

| Criterion | Unit | Source |
|---|---|---|
| Construction Cost | M USD | FHWA Interchange Justification Report Guidelines (2023) |
| Land Area | hectares | TRB NCHRP Report 659 — Geometric Design of Freeway Ramps |
| Throughput | veh/hr | HCM 7th Edition, Chapter 14 (Freeway Interchanges) |
| Safety Index | 1–10 | PIARC Road Safety Manual (2019); AASHTO HSM (2022) |

## References

- Fishburn, P. C. (1967). *Additive utilities with incomplete product sets.*  
  Operations Research, 15(3), 537–542.
- Triantaphyllou, E. (2000). *Multi-Criteria Decision Making Methods.*  
  Kluwer Academic Publishers.
- TRB (2022). *Highway Capacity Manual, 7th Edition.*
- FHWA (2023). *Interchange Justification Report Guidelines.*
- PIARC (2019). *Road Safety Manual.*
- AASHTO (2022). *Highway Safety Manual, 2nd Edition.*
"""
        )

    with col_m2:
        st.markdown("**Active Weight Profile**")
        st.dataframe(
            pd.DataFrame([
                {"Criterion": CRITERION_LABELS[k], "Normalised Weight": f"{v:.0%}"}
                for k, v in norm_w.items()
            ]),
            use_container_width=True,
            hide_index=True,
        )

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("**Current Ranking**")

        for res in results:
            color = ALTERNATIVE_COLORS.get(res.alternative_name, "#0f766e")
            medal = _MEDALS[res.rank - 1]
            st.markdown(
                f"<div style='display:flex;align-items:center;gap:10px;"
                f"background:#ffffff;border:1px solid #e2e8f0;border-radius:8px;"
                f"padding:9px 14px;margin-bottom:6px'>"
                f"<span style='font-size:1.2rem'>{medal}</span>"
                f"<span style='color:{color};font-weight:700;flex:1'>{res.alternative_name}</span>"
                f"<span style='color:#0f172a;font-weight:700'>{res.total_score:.4f}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

        st.markdown("<br>", unsafe_allow_html=True)
        st.info(
            "Adjust the sidebar sliders to explore how different weight "
            "profiles change the ranking.  The WSM engine re-computes "
            "instantly on every interaction.",
            icon="💡",
        )

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

st.markdown("---")
st.caption(
    "TDSS v3.0  ·  Decoupled Architecture  ·  "
    "MCDA Engine: Weighted Sum Model (WSM)  ·  "
    "Charts: Plotly  ·  "
    "Data: Expert-preset constants (FHWA / HCM 7th Ed. / PIARC 2022)"
)
