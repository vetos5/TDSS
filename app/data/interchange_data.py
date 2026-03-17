"""
Decoupled Architecture: Expert Data Layer
==========================================
This module defines ALL interchange alternatives using expert-sourced,
predefined constants organised into four functional context categories.
It is completely independent of any SVG geometry, CAD blueprint parsing,
or visual asset processing.

Architectural Significance (for academic report)
-------------------------------------------------
In the previous "coupled" architecture, criterion values (Construction Cost,
Land Area) were *derived at runtime* by parsing SVG path data through a chain
of geometric algorithms.  This created brittle coupling: a change to an SVG
file's structure could silently corrupt MCDA scores with no traceability.

The new "decoupled" architecture enforces three strict layers:

    DATA LAYER   (this file)             — Expert constants; no I/O, no maths.
    LOGIC LAYER  (app.application)       — Pure WSM/MCDA maths; no data or UI.
    VIEW LAYER   (app.ui)                — Rendering only; reads results, never
                                           computes; shows SVGs as <img> tags.

SVG files in ``assets/blueprints/`` are treated as static visual assets —
equivalent to a JPEG photograph.  They are never opened by the engine.

Data Sources
------------
- Construction costs : FHWA Interchange Justification Report Guidelines (2023)
- Land area          : TRB NCHRP Report 659 — Geometric Design of Freeway Ramps
- Throughput (vph)   : HCM 7th Edition, Chapter 14 (Freeway Interchanges)
- Safety Index (1–10): PIARC Road Safety Manual (2019); AASHTO HSM (2022)
"""

from __future__ import annotations

from typing import Dict

from app.application.dss_engine import Alternative, Criterion

# ---------------------------------------------------------------------------
# Criteria — names, optimisation directions, default weights
# ---------------------------------------------------------------------------

CRITERIA: list[Criterion] = [
    Criterion(
        name="construction_cost_mln",
        direction="minimize",
        weight=0.30,
        unit="M USD",
    ),
    Criterion(
        name="land_area_hectares",
        direction="minimize",
        weight=0.20,
        unit="ha",
    ),
    Criterion(
        name="throughput_vph",
        direction="maximize",
        weight=0.25,
        unit="veh/hr",
    ),
    Criterion(
        name="safety_index",
        direction="maximize",
        weight=0.25,
        unit="/10",
    ),
]

# Human-readable labels used by the UI and charts (key = criterion name).
CRITERION_LABELS: Dict[str, str] = {
    "construction_cost_mln": "Construction Cost",
    "land_area_hectares":    "Land Area",
    "throughput_vph":        "Throughput (vph)",
    "safety_index":          "Safety Index",
}

# ---------------------------------------------------------------------------
# Categorised interchange data — INTERCHANGE_DATA
# ---------------------------------------------------------------------------
# Top-level keys represent the three functional context categories.
# Inner dict keys are alternative names; values map directly to criterion names
# used by CRITERIA / DecisionSupportSystem (no short-key aliases needed).

INTERCHANGE_DATA: Dict[str, Dict[str, Dict[str, float]]] = {
    "System (Highway + Highway)": {
        "Cloverleaf": {
            "construction_cost_mln": 15.0,
            "land_area_hectares":    20.0,
            "throughput_vph":        4_000.0,
            "safety_index":          4.0,
        },
        "Turbine": {
            "construction_cost_mln": 45.0,
            "land_area_hectares":    25.0,
            "throughput_vph":        6_500.0,
            "safety_index":          8.0,
        },
        "Stack (4-Level)": {
            "construction_cost_mln": 80.0,
            "land_area_hectares":    12.0,
            "throughput_vph":        7_500.0,
            "safety_index":          9.0,
        },
    },
    "Service (Highway + Urban)": {
        "Diamond": {
            "construction_cost_mln": 10.0,
            "land_area_hectares":     5.0,
            "throughput_vph":         2_500.0,
            "safety_index":           5.0,
        },
        "SPUI": {
            "construction_cost_mln": 20.0,
            "land_area_hectares":     4.0,
            "throughput_vph":         4_500.0,
            "safety_index":           7.0,
        },
        "DDI": {
            "construction_cost_mln": 18.0,
            "land_area_hectares":     6.0,
            "throughput_vph":         5_500.0,
            "safety_index":           9.0,
        },
    },
    "T-Type (3 Directions)": {
        "Trumpet": {
            "construction_cost_mln": 12.0,
            "land_area_hectares":    10.0,
            "throughput_vph":        3_500.0,
            "safety_index":          7.0,
        },
        "Directional T": {
            "construction_cost_mln": 35.0,
            "land_area_hectares":    15.0,
            "throughput_vph":        5_000.0,
            "safety_index":          9.0,
        },
    },
}

# ---------------------------------------------------------------------------
# Alternative descriptions — free-text summaries used in the UI gallery
# ---------------------------------------------------------------------------

ALTERNATIVE_DESCRIPTIONS: Dict[str, str] = {
    "Cloverleaf": (
        "Grade-separated 4-loop interchange. High capacity and free-flow operations with no "
        "traffic signals, but loop ramp geometry creates large land requirements and weaving "
        "sections between successive on/off ramps reduce safety at high volumes."
    ),
    "Turbine": (
        "Directional interchange with semi-direct ramps arranged in a turbine pattern. "
        "Eliminates weaving conflicts, delivers superior throughput and safety, but requires "
        "significant right-of-way and construction investment."
    ),
    "Stack (4-Level)": (
        "Four-level fully directional grade-separated interchange. The highest-capacity and "
        "safest system interchange type; all movements are direct with no weaving or signal "
        "delay, at the cost of maximum construction complexity."
    ),
    "Diamond": (
        "Standard diamond interchange with four ramp terminals controlled by signals or "
        "roundabouts at the arterial crossings. Cost-effective and compact, but at-grade "
        "signal crossings introduce delay and limit peak throughput."
    ),
    "SPUI": (
        "Single Point Urban Interchange: all ramp movements converge at one signalised "
        "intersection. Combines near-cloverleaf throughput with a compact urban footprint, "
        "optimal for constrained corridors where land acquisition cost is critical."
    ),
    "DDI": (
        "Diverging Diamond Interchange: traffic crosses to the opposite side of the road at "
        "two signalised crossovers, eliminating left-turn conflicts. High throughput and a "
        "strong safety record in recent North American and European deployments."
    ),
    "Trumpet": (
        "Three-leg interchange with a loop ramp for one turning movement and direct ramps "
        "for the other two. Common for highway termini; cost-effective with a moderate "
        "footprint and good safety characteristics."
    ),
    "Directional T": (
        "Three-leg directional interchange using semi-direct flyover ramps. Achieves maximum "
        "throughput and safety for T-junctions at the cost of higher construction expense "
        "and right-of-way requirements."
    ),
}

# ---------------------------------------------------------------------------
# Static visual asset paths — display only, NEVER parsed
# ---------------------------------------------------------------------------

BLUEPRINT_PATHS: Dict[str, str] = {
    "Cloverleaf":              "assets/blueprints/cloverleaf.png",
    "Turbine":                 "assets/blueprints/turbine.png",
    "Stack (4-Level)":         "assets/blueprints/stack.png",
    "Diamond":                 "assets/blueprints/diamond.svg",
    "SPUI":                    "assets/blueprints/spui.png",
    "DDI":                     "assets/blueprints/ddi.png",
    "Trumpet":                 "assets/blueprints/trumpet.png",
    "Directional T":           "assets/blueprints/directional_t.png",
}

# WCAG AA contrast-compliant colour palette (one distinct colour per alternative).
# Light-mode colours are saturated/dark; dark-mode colours are bright/neon for
# readability on dark card backgrounds.
ALTERNATIVE_COLORS: Dict[str, str] = {
    "Cloverleaf":              "#0f766e",
    "Turbine":                 "#0369a1",
    "Stack (4-Level)":         "#1d4ed8",
    "Diamond":                 "#ea580c",
    "SPUI":                    "#d97706",
    "DDI":                     "#b45309",
    "Trumpet":                 "#7c3aed",
    "Directional T":           "#6d28d9",
}

ALTERNATIVE_COLORS_DARK: Dict[str, str] = {
    "Cloverleaf":              "#5eead4",   # Teal-300
    "Turbine":                 "#7dd3fc",   # Sky-300
    "Stack (4-Level)":         "#93c5fd",   # Blue-300
    "Diamond":                 "#fdba74",   # Orange-300
    "SPUI":                    "#fcd34d",   # Amber-300
    "DDI":                     "#fbbf24",   # Amber-400
    "Trumpet":                 "#c4b5fd",   # Violet-300
    "Directional T":           "#a78bfa",   # Violet-400
}

# ---------------------------------------------------------------------------
# Helper — build Alternative objects for a given context
# ---------------------------------------------------------------------------

def get_alternatives_for_context(context: str) -> list[Alternative]:
    """Return a list of Alternative objects for the given top-level context key.

    Parameters
    ----------
    context :
        One of the three keys of ``INTERCHANGE_DATA``
        (e.g. ``"System (Highway + Highway)"``).

    Returns
    -------
    list[Alternative]
        Ready-to-pass list for ``DecisionSupportSystem.evaluate()``.
    """
    return [
        Alternative(
            name=name,
            raw_values=dict(values),
            description=ALTERNATIVE_DESCRIPTIONS.get(name, ""),
        )
        for name, values in INTERCHANGE_DATA[context].items()
    ]
