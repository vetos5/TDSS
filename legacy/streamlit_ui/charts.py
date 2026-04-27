"""
Chart Generation Layer
======================
Stateless Plotly figure factories.  Each function accepts plain Python data
and an optional ``dark`` flag so the colour scheme tracks the UI theme.

Light palette  — deep teal primary, coral accent, dark slate text on white.
Dark palette   — same hues lightened for legibility on dark backgrounds.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import plotly.graph_objects as go

from app.application.dss_engine import EvaluationResult


# ---------------------------------------------------------------------------
# Theme-aware palette
# ---------------------------------------------------------------------------

def _palette(dark: bool) -> dict:
    if dark:
        return {
            "bg":          "#1e293b",
            "card":        "#1e293b",
            "grid":        "#334155",
            "text":        "#e2e8f0",
            "subtext":     "#94a3b8",
            "teal":        "#2dd4bf",    # teal-400 — visible on dark
            "orange":      "#fb923c",    # orange-400
            "violet":      "#a78bfa",    # violet-400
            "blue":        "#60a5fa",    # blue-400
            "fill_teal":   "rgba(45,212,191,0.18)",
            "fill_orange": "rgba(251,146,60,0.18)",
            "fill_violet": "rgba(167,139,250,0.18)",
            "fill_blue":   "rgba(96,165,250,0.18)",
        }
    return {
        "bg":          "#f8fafc",
        "card":        "#ffffff",
        "grid":        "#cbd5e1",       # slate-300 — darker grid for light bg
        "text":        "#0f172a",       # slate-900
        "subtext":     "#334155",       # slate-700 — much darker for readability
        "teal":        "#0f766e",
        "orange":      "#ea580c",
        "violet":      "#7c3aed",
        "blue":        "#1d4ed8",
        "fill_teal":   "rgba(15,118,110,0.15)",
        "fill_orange": "rgba(234,88,12,0.15)",
        "fill_violet": "rgba(124,58,237,0.15)",
        "fill_blue":   "rgba(29,78,216,0.15)",
    }


def _base_layout(title: str, p: dict) -> dict:
    return dict(
        title=dict(
            text=title,
            font=dict(size=15, color=p["text"], family="Inter, system-ui, sans-serif"),
            x=0.02,
            xanchor="left",
        ),
        paper_bgcolor=p["bg"],
        plot_bgcolor=p["bg"],
        font=dict(family="Inter, system-ui, sans-serif", color=p["text"], size=12),
        margin=dict(l=16, r=16, t=48, b=16),
    )


# ---------------------------------------------------------------------------
# Public chart functions
# ---------------------------------------------------------------------------

def create_wsm_bar_chart(
    results: List[EvaluationResult],
    colors: Dict[str, str],
    dark: bool = False,
) -> go.Figure:
    """
    Horizontal bar chart of WSM composite scores, best alternative at top.
    """
    p       = _palette(dark)
    ordered = sorted(results, key=lambda r: r.total_score)

    names       = [r.alternative_name for r in ordered]
    scores      = [r.total_score      for r in ordered]
    bar_colors  = [colors.get(n, p["teal"]) for n in names]

    # In dark mode lighten the brand colours slightly so they read on dark bg
    if dark:
        bar_colors = [_lighten_for_dark(c) for c in bar_colors]

    text_labels = [f"  #{r.rank}  {r.total_score:.4f}" for r in ordered]

    fig = go.Figure(
        go.Bar(
            x=scores,
            y=names,
            orientation="h",
            marker=dict(
                color=bar_colors,
                line=dict(color="rgba(0,0,0,0.08)", width=1),
                opacity=0.92,
            ),
            text=text_labels,
            textposition="outside",
            textfont=dict(size=11, color=p["text"]),
            cliponaxis=False,
            hovertemplate=(
                "<b>%{y}</b><br>"
                "WSM Score: <b>%{x:.4f}</b><extra></extra>"
            ),
        )
    )

    fig.update_layout(
        **_base_layout("WSM Score Ranking", p),
        xaxis=dict(
            title=dict(
                text="WSM Composite Score  S<sub>i</sub>",
                font=dict(color=p["subtext"]),
            ),
            range=[0, 1.22],
            gridcolor=p["grid"],
            zeroline=True,
            zerolinecolor=p["grid"],
            showline=True,
            linecolor=p["grid"],
            tickfont=dict(size=11, color=p["subtext"]),
        ),
        yaxis=dict(
            gridcolor=p["grid"],
            showline=False,
            tickfont=dict(size=12, color=p["text"]),
        ),
        height=300,
        showlegend=False,
    )
    return fig


def create_radar_chart(
    results: List[EvaluationResult],
    criterion_labels: Dict[str, str],
    colors: Dict[str, str],
    top_n: int = 2,
    dark: bool = False,
) -> go.Figure:
    """
    Radar (spider) chart — normalised criterion profile for the top-N alternatives.
    """
    p          = _palette(dark)
    top        = results[:top_n]
    crit_keys  = list(results[0].normalised_values.keys())
    axes       = [criterion_labels.get(k, k) for k in crit_keys]
    axes_closed = axes + [axes[0]]

    fill_keys = ["fill_teal", "fill_orange", "fill_violet", "fill_blue"]
    line_keys = ["teal",      "orange",      "violet",      "blue"]

    fig = go.Figure()

    for idx, res in enumerate(top):
        vals        = [res.normalised_values[k] for k in crit_keys]
        vals_closed = vals + [vals[0]]
        line_color  = colors.get(res.alternative_name, p[line_keys[idx % 4]])
        if dark:
            line_color = _lighten_for_dark(line_color)
        fill_color  = p[fill_keys[idx % 4]]

        fig.add_trace(
            go.Scatterpolar(
                r=vals_closed,
                theta=axes_closed,
                fill="toself",
                fillcolor=fill_color,
                line=dict(color=line_color, width=2.5),
                name=f"#{res.rank}  {res.alternative_name}",
                hovertemplate=(
                    f"<b>{res.alternative_name}</b><br>"
                    "%{theta}: <b>%{r:.3f}</b><extra></extra>"
                ),
            )
        )

    fig.update_layout(
        **_base_layout(f"Normalised Criterion Profile — Top {top_n} Alternatives", p),
        polar=dict(
            bgcolor=p["card"],
            radialaxis=dict(
                visible=True,
                range=[0, 1],
                tickvals=[0.25, 0.5, 0.75, 1.0],
                tickfont=dict(size=10, color=p["subtext"]),
                gridcolor=p["grid"],
                linecolor=p["grid"],
            ),
            angularaxis=dict(
                tickfont=dict(size=11, color=p["text"]),
                gridcolor=p["grid"],
                linecolor=p["grid"],
                rotation=90,
                direction="clockwise",
            ),
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=-0.18,
            xanchor="center",
            x=0.5,
            font=dict(size=12, color=p["text"]),
            bgcolor="rgba(0,0,0,0)",
        ),
        height=420,
    )
    return fig


def create_contribution_stacked_bar(
    results: List[EvaluationResult],
    criterion_labels: Dict[str, str],
    dark: bool = False,
) -> go.Figure:
    """
    Stacked horizontal bar — per-criterion weighted contributions summing to WSM score.
    """
    p         = _palette(dark)
    crit_keys = ["teal", "orange", "violet", "blue"]
    colors    = [p[k] for k in crit_keys]

    ordered   = sorted(results, key=lambda r: r.total_score)
    alt_names = [r.alternative_name for r in ordered]
    keys      = list(results[0].weighted_scores.keys())

    fig = go.Figure()

    for i, key in enumerate(keys):
        label  = criterion_labels.get(key, key)
        values = [r.weighted_scores[key] for r in ordered]

        fig.add_trace(
            go.Bar(
                name=label,
                x=values,
                y=alt_names,
                orientation="h",
                marker=dict(
                    color=colors[i % len(colors)],
                    opacity=0.88,
                    line=dict(color="rgba(255,255,255,0.4)", width=0.8),
                ),
                hovertemplate=(
                    f"<b>{label}</b><br>"
                    "Contribution: <b>%{x:.4f}</b><extra></extra>"
                ),
            )
        )

    fig.update_layout(
        **_base_layout("Weighted Contribution Breakdown  (w\u2C7c · x\u0305\u1D62\u2C7c)", p),
        barmode="stack",
        xaxis=dict(
            title=dict(
                text="Summed Weighted Contribution",
                font=dict(color=p["subtext"]),
            ),
            range=[0, 1.08],
            gridcolor=p["grid"],
            zeroline=False,
            tickfont=dict(size=11, color=p["subtext"]),
        ),
        yaxis=dict(
            gridcolor=p["grid"],
            showline=False,
            tickfont=dict(size=12, color=p["text"]),
        ),
        # Place legend above the plot area so it never overlaps the x-axis title
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="center",
            x=0.5,
            font=dict(size=11, color=p["text"]),
            bgcolor="rgba(0,0,0,0)",
        ),
        height=340,
    )
    # Override margin separately to avoid duplicate-key conflict with _base_layout
    fig.update_layout(margin=dict(l=16, r=16, t=88, b=32))
    return fig


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

_DARK_OVERRIDES: Dict[str, str] = {
    "#0f766e": "#2dd4bf",   # teal
    "#ea580c": "#fb923c",   # orange
    "#7c3aed": "#a78bfa",   # violet
    "#1d4ed8": "#60a5fa",   # blue
}


def _lighten_for_dark(hex_color: str) -> str:
    """Return a lighter variant of a brand colour for use on dark backgrounds."""
    return _DARK_OVERRIDES.get(hex_color.lower(), hex_color)
