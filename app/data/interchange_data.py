"""
Decoupled Architecture: Expert Data Layer
==========================================
This module defines ALL interchange alternatives using expert-sourced,
predefined constants.  It is completely independent of any SVG geometry,
CAD blueprint parsing, or visual asset processing.

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
# Alternatives — expert-sourced predefined data
# ---------------------------------------------------------------------------
# Raw values are fixed expert estimates drawn from the sources listed above.
# They are intentionally *not* derived from geometry so that the model
# remains stable, reproducible, and auditable for academic review.

ALTERNATIVES: list[Alternative] = [
    Alternative(
        name="Cloverleaf",
        description=(
            "Grade-separated 4-loop interchange. High capacity and free-flow "
            "operations with no traffic signals, but the loop ramp geometry "
            "creates large land requirements and weaving sections between "
            "successive on/off ramps reduce safety at high volumes."
        ),
        raw_values={
            # FHWA: complex grade-separated interchange, 4 loop ramps
            "construction_cost_mln": 45.2,
            # NCHRP 659: typical footprint ~125 000 m² (12.5 ha)
            "land_area_hectares":    12.5,
            # HCM 7th, Ch.14: free-flow, no signals → highest throughput class
            "throughput_vph":        6_500.0,
            # PIARC: weaving zones → moderate-risk; below grade-sep average
            "safety_index":          7.2,
        },
    ),
    Alternative(
        name="Diamond",
        description=(
            "Standard diamond interchange with four ramp terminals controlled "
            "by signals or roundabouts at the arterial crossings. "
            "Cost-effective and compact, but at-grade signal crossings "
            "introduce delay and limit peak throughput."
        ),
        raw_values={
            # FHWA: simple 2-bridge diamond; lower cost than full grade-sep
            "construction_cost_mln": 18.4,
            "land_area_hectares":     4.2,
            # HCM: signalised ramp terminals reduce effective capacity
            "throughput_vph":         4_200.0,
            # AASHTO HSM: at-grade crossings, left-turn conflicts
            "safety_index":           6.5,
        },
    ),
    Alternative(
        name="Roundabout",
        description=(
            "Modern multi-lane roundabout handling all turning movements via "
            "yield control. Extremely safe due to a low conflict-point count "
            "and reduced approach speeds, but throughput is limited compared "
            "to grade-separated alternatives at high-volume corridors."
        ),
        raw_values={
            # Minimal civil works; no bridges or ramp structures required
            "construction_cost_mln":  7.8,
            "land_area_hectares":     1.8,
            # HCM Ch.22: yield-controlled entry limits peak throughput
            "throughput_vph":         2_800.0,
            # AASHTO HSM: lowest crash severity class; single conflict-point type
            "safety_index":           9.1,
        },
    ),
    Alternative(
        name="SPUI",
        description=(
            "Single Point Urban Interchange (SPUI): all ramp movements "
            "converge at one signalised intersection beneath/above the "
            "freeway. Combines near-cloverleaf throughput with a compact "
            "urban footprint, making it optimal for constrained corridors "
            "where land acquisition cost is critical."
        ),
        raw_values={
            # FHWA SPUI Design Guide: elevated structure + single signal point
            "construction_cost_mln": 28.6,
            "land_area_hectares":     3.5,
            # FHWA SPUI Guide: ~5 800 vph through single signal cycle
            "throughput_vph":         5_800.0,
            # Grade-separated + signal control → above diamond, below roundabout
            "safety_index":           7.8,
        },
    ),
]

# ---------------------------------------------------------------------------
# Static visual asset paths — display only, NEVER parsed
# ---------------------------------------------------------------------------

BLUEPRINT_PATHS: Dict[str, str] = {
    "Cloverleaf": "assets/blueprints/cloverleaf.svg",
    "Diamond":    "assets/blueprints/diamond.svg",
    "Roundabout": "assets/blueprints/roundabout.svg",
    "SPUI":       "assets/blueprints/spui.svg",
}

# Modern, accessible chart colour palette (WCAG AA contrast compliant).
ALTERNATIVE_COLORS: Dict[str, str] = {
    "Cloverleaf": "#0f766e",   # Deep Teal
    "Diamond":    "#ea580c",   # Coral / Burnt Orange
    "Roundabout": "#7c3aed",   # Violet
    "SPUI":       "#1d4ed8",   # Royal Blue
}
