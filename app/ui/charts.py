"""
Decoupled Architecture: Chart Generation Layer
================================================
All visualisation logic is isolated here.  Functions accept plain Python
data structures and return Plotly ``Figure`` objects — they know nothing
about Streamlit, SVG files, or the data layer.

Colour palette
--------------
Background   #f8fafc  — very light slate (matches page bg)
Card         #ffffff
Grid lines   #e2e8f0  — cool grey
Body text    #1e293b  — dark slate
Subtext      #64748b
Teal         #0f766e  — primary accent (Deep Teal)
Orange       #ea580c  — secondary accent (Coral / Burnt Orange)
Violet       #7c3aed
Blue         #1d4ed8
"""

from __future__ import annotations

from typing import Dict, List, Optional

import plotly.graph_objects as go

from app.application.dss_engine import EvaluationResult

# ---------------------------------------------------------------------------
# Shared palette
# ---------------------------------------------------------------------------

_P = {
    "bg":           "#f8fafc",
    "card":         "#ffffff",
    "grid":         "#e2e8f0",
    "text":         "#1e293b",
    "subtext":      "#64748b",
    "teal":         "#0f766e",
    "orange":       "#ea580c",
    "violet":       "#7c3aed",
    "blue":         "#1d4ed8",
    # Semi-transparent fills for radar polygons
    "fill_teal":    "rgba(15,118,110,0.18)",
    "fill_orange":  "rgba(234,88,12,0.18)",
    "fill_violet":  "rgba(124,58,237,0.18)",
    "fill_blue":    "rgba(29,78,216,0.18)",
}

_LINE_FILLS = [
    (_P["teal"],   _P["fill_teal"]),
    (_P["orange"], _P["fill_orange"]),
    (_P["violet"], _P["fill_violet"]),
    (_P["blue"],   _P["fill_blue"]),
]

_CRIT_COLORS = [_P["teal"], _P["orange"], _P["violet"], _P["blue"]]


def _base_layout(title: str) -> dict:
    """Common Plotly layout kwargs shared by all chart functions."""
    return dict(
        title=dict(
            text=title,
            font=dict(size=15, color=_P["text"], family="Inter, system-ui, sans-serif"),
            x=0.02,
            xanchor="left",
        ),
        paper_bgcolor=_P["bg"],
        plot_bgcolor=_P["bg"],
        font=dict(family="Inter, system-ui, sans-serif", color=_P["text"], size=12),
        margin=dict(l=16, r=16, t=48, b=16),
    )


# ---------------------------------------------------------------------------
# Public chart functions
# ---------------------------------------------------------------------------

def create_wsm_bar_chart(
    results: List[EvaluationResult],
    colors: Dict[str, str],
) -> go.Figure:
    """
    Horizontal bar chart of WSM composite scores sorted best → worst (top).

    Parameters
    ----------
    results : ranked list of EvaluationResult (rank-1 first)
    colors  : alternative_name → hex colour string
    """
    # Ascending sort so rank-1 sits at the top of the horizontal chart
    ordered = sorted(results, key=lambda r: r.total_score)

    names       = [r.alternative_name for r in ordered]
    scores      = [r.total_score      for r in ordered]
    bar_colors  = [colors.get(n, _P["teal"]) for n in names]
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
            textfont=dict(size=11, color=_P["text"]),
            cliponaxis=False,
            hovertemplate=(
                "<b>%{y}</b><br>"
                "WSM Score: <b>%{x:.4f}</b><extra></extra>"
            ),
        )
    )

    fig.update_layout(
        **_base_layout("WSM Score Ranking"),
        xaxis=dict(
            title="WSM Composite Score  S<sub>i</sub>",
            range=[0, 1.22],
            gridcolor=_P["grid"],
            zeroline=True,
            zerolinecolor=_P["grid"],
            showline=True,
            linecolor=_P["grid"],
            tickfont=dict(size=11),
        ),
        yaxis=dict(
            gridcolor=_P["grid"],
            showline=False,
            tickfont=dict(size=12),
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
) -> go.Figure:
    """
    Radar (spider) chart showing the normalised criterion profile for the
    top-N alternatives.  Highlights trade-off patterns at a glance.

    Parameters
    ----------
    results          : full ranked list (rank-1 first)
    criterion_labels : criterion key → human-readable label
    colors           : alternative_name → hex colour
    top_n            : how many top alternatives to overlay (default 2)
    """
    top        = results[:top_n]
    crit_keys  = list(results[0].normalised_values.keys())
    axes       = [criterion_labels.get(k, k) for k in crit_keys]
    axes_closed = axes + [axes[0]]           # Close the polygon

    fig = go.Figure()

    for idx, res in enumerate(top):
        vals        = [res.normalised_values[k] for k in crit_keys]
        vals_closed = vals + [vals[0]]
        line_color, fill_color = _LINE_FILLS[idx % len(_LINE_FILLS)]
        # Override line color with the alternative's brand color if available
        line_color = colors.get(res.alternative_name, line_color)

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
        **_base_layout(f"Normalised Criterion Profile — Top {top_n} Alternatives"),
        polar=dict(
            bgcolor=_P["card"],
            radialaxis=dict(
                visible=True,
                range=[0, 1],
                tickvals=[0.25, 0.5, 0.75, 1.0],
                tickfont=dict(size=9, color=_P["subtext"]),
                gridcolor=_P["grid"],
                linecolor=_P["grid"],
            ),
            angularaxis=dict(
                tickfont=dict(size=11, color=_P["text"]),
                gridcolor=_P["grid"],
                linecolor=_P["grid"],
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
            font=dict(size=12),
            bgcolor="rgba(0,0,0,0)",
        ),
        height=420,
    )
    return fig


def create_contribution_stacked_bar(
    results: List[EvaluationResult],
    criterion_labels: Dict[str, str],
    crit_colors: Optional[List[str]] = None,
) -> go.Figure:
    """
    Stacked horizontal bar chart — per-criterion weighted contributions
    that sum to the WSM score for each alternative.

    Parameters
    ----------
    results          : ranked list of EvaluationResult
    criterion_labels : criterion key → label
    crit_colors      : optional list of hex colours for each criterion
    """
    if crit_colors is None:
        crit_colors = _CRIT_COLORS

    ordered   = sorted(results, key=lambda r: r.total_score)
    alt_names = [r.alternative_name for r in ordered]
    crit_keys = list(results[0].weighted_scores.keys())

    fig = go.Figure()

    for i, key in enumerate(crit_keys):
        label  = criterion_labels.get(key, key)
        values = [r.weighted_scores[key] for r in ordered]
        color  = crit_colors[i % len(crit_colors)]

        fig.add_trace(
            go.Bar(
                name=label,
                x=values,
                y=alt_names,
                orientation="h",
                marker=dict(
                    color=color,
                    opacity=0.88,
                    line=dict(color="rgba(255,255,255,0.5)", width=0.8),
                ),
                hovertemplate=(
                    f"<b>{label}</b><br>"
                    "Weighted contribution: <b>%{x:.4f}</b><extra></extra>"
                ),
            )
        )

    fig.update_layout(
        **_base_layout("Weighted Contribution Breakdown  (w<sub>j</sub> · x̄<sub>ij</sub>)"),
        barmode="stack",
        xaxis=dict(
            title="Summed Weighted Contribution",
            range=[0, 1.08],
            gridcolor=_P["grid"],
            zeroline=False,
            tickfont=dict(size=11),
        ),
        yaxis=dict(
            gridcolor=_P["grid"],
            showline=False,
            tickfont=dict(size=12),
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=-0.32,
            xanchor="center",
            x=0.5,
            font=dict(size=11),
            bgcolor="rgba(0,0,0,0)",
        ),
        height=310,
    )
    return fig
