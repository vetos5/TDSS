"""
Expert constants for the engineering analyses: design-year traffic per interchange element and
expected crashes (Phase 1), life-cycle cost appraisal (Phase 2).

Constants only, no logic; the models live in ``app.application.engineering`` and
``app.application.economics``. The numbers are planning-level assumptions in the spirit of the
cited manuals, chosen so that the alternatives keep the ordering of the expert criteria in
``interchange_data.py``. They are meant to be replaced by local values on a real project.
See DOCUMENTATION.md §3.13–3.16.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

# ---------------------------------------------------------------------------
# Study defaults (the inputs of the "Traffic and life cycle" panel)
# ---------------------------------------------------------------------------

STUDY_DEFAULTS: Dict[str, float] = {
    "opening_year": 2027,
    "design_years": 20,        # design life / analysis period (years after opening)
    "growth_pct": 2.0,         # compound annual traffic growth
    "directional_split": 55,   # % of the peak-hour volume in the peak direction (D factor)
    "heavy_pct": 10.0,         # % heavy vehicles
    "turning_pct": 25.0,       # % of the peak-direction flow that turns (uses the ramps)
    # Phase 2 — economics
    "discount_pct": 4.0,       # real discount rate
    "value_of_time": 18.0,     # USD per vehicle-hour of delay
    "maintenance_pct": 1.0,    # annual maintenance as % of construction cost
}

# Passenger-car equivalent of a heavy vehicle on level terrain (HCM 7, Ch. 12), and on rolling or
# mountainous terrain the larger equivalents of the specific-grade tables, simplified.
HEAVY_VEHICLE_PCE: Dict[str, float] = {"Flat": 1.5, "Rolling": 2.5, "Mountainous": 4.5}

# ---------------------------------------------------------------------------
# Traffic: interchange elements
# ---------------------------------------------------------------------------
# Each alternative is described by the elements that limit its capacity. ``load`` says which flow
# an element carries, as a multiple of a base flow:
#   "turn"     — T, the peak-direction turning flow (Q · turning share)
#   "mainline" — Q, the peak-direction mainline flow at the merge / diverge
# ``capacity`` is in pc/h; None for "mainline" means lanes × the basic-segment lane capacity at
# the design speed (see ``lane_capacity``). ``ffs_kmh`` and ``length_km`` give the free-flow time
# of the BPR delay function; signals add ``control_s`` seconds of fixed control delay.
#
# Ramp roadway capacities after HCM 7 Exhibit 14-12 (single-lane ramp: 1,900–2,200 pc/h by ramp
# free-flow speed), reduced for loops (tight radius, weaving at the ends). Weaving capacity of a
# cloverleaf C-D section after HCM 7 Ch. 13 (weaving flow, not total flow). Signalised terminals:
# saturation flow 1,900 pc/h/ln × lanes × effective green ratio of the critical movements.

Element = Dict[str, object]

TRAFFIC_ELEMENTS: Dict[str, List[Element]] = {
    "Cloverleaf": [
        {"id": "loop_ramp", "kind": "loop", "load": "turn", "share": 0.5,
         "capacity": 1500, "ffs_kmh": 40, "length_km": 0.35},
        {"id": "outer_ramp", "kind": "ramp", "load": "turn", "share": 0.5,
         "capacity": 1900, "ffs_kmh": 60, "length_km": 0.45},
        {"id": "weave", "kind": "weave", "load": "turn", "share": 1.0,
         "capacity": 1800, "ffs_kmh": 60, "length_km": 0.25},
        {"id": "merge", "kind": "merge", "load": "mainline", "share": 1.0,
         "capacity": None, "ffs_kmh": None, "length_km": 0.5},
    ],
    "Turbine": [
        {"id": "semi_direct_ramp", "kind": "ramp", "load": "turn", "share": 0.5,
         "capacity": 2000, "ffs_kmh": 70, "length_km": 0.8},
        {"id": "outer_ramp", "kind": "ramp", "load": "turn", "share": 0.5,
         "capacity": 2000, "ffs_kmh": 70, "length_km": 0.45},
        {"id": "merge", "kind": "merge", "load": "mainline", "share": 1.0,
         "capacity": None, "ffs_kmh": None, "length_km": 0.5},
    ],
    "Stack (4-Level)": [
        {"id": "direct_ramp", "kind": "ramp", "load": "turn", "share": 0.5,
         "capacity": 2200, "ffs_kmh": 80, "length_km": 0.9},
        {"id": "outer_ramp", "kind": "ramp", "load": "turn", "share": 0.5,
         "capacity": 2100, "ffs_kmh": 70, "length_km": 0.45},
        {"id": "merge", "kind": "merge", "load": "mainline", "share": 1.0,
         "capacity": None, "ffs_kmh": None, "length_km": 0.5},
    ],
    "Diamond": [
        # Two terminals; the critical one serves the off-ramp lefts and rights of one direction
        # plus the opposing lefts: 2 lanes × 1,900 × g/C 0.40.
        {"id": "signal_terminal", "kind": "signal", "load": "turn", "share": 1.0,
         "capacity": 1520, "ffs_kmh": 50, "length_km": 0.3, "control_s": 25},
        {"id": "ramp", "kind": "ramp", "load": "turn", "share": 0.5,
         "capacity": 1900, "ffs_kmh": 60, "length_km": 0.4},
        {"id": "merge", "kind": "merge", "load": "mainline", "share": 1.0,
         "capacity": None, "ffs_kmh": None, "length_km": 0.5},
    ],
    "SPUI": [
        # One signal for both directions' turns: 3 phases, 2 lanes per left, g/C ≈ 0.30 each,
        # free rights bypass it (load 2T · 0.6 ≈ 1.2T reaches the signal).
        {"id": "single_point_signal", "kind": "signal", "load": "turn", "share": 1.2,
         "capacity": 2600, "ffs_kmh": 50, "length_km": 0.35, "control_s": 30},
        {"id": "ramp", "kind": "ramp", "load": "turn", "share": 0.5,
         "capacity": 2000, "ffs_kmh": 60, "length_km": 0.4},
        {"id": "merge", "kind": "merge", "load": "mainline", "share": 1.0,
         "capacity": None, "ffs_kmh": None, "length_km": 0.5},
    ],
    "DDI": [
        # Two-phase crossovers: 2 lanes × 1,900 × g/C 0.48; lefts onto the freeway are unopposed.
        {"id": "crossover_signal", "kind": "signal", "load": "turn", "share": 1.0,
         "capacity": 1820, "ffs_kmh": 50, "length_km": 0.3, "control_s": 15},
        {"id": "ramp", "kind": "ramp", "load": "turn", "share": 0.5,
         "capacity": 2000, "ffs_kmh": 60, "length_km": 0.4},
        {"id": "merge", "kind": "merge", "load": "mainline", "share": 1.0,
         "capacity": None, "ffs_kmh": None, "length_km": 0.5},
    ],
    "Trumpet": [
        {"id": "loop_ramp", "kind": "loop", "load": "turn", "share": 0.5,
         "capacity": 1500, "ffs_kmh": 40, "length_km": 0.35},
        {"id": "semi_direct_ramp", "kind": "ramp", "load": "turn", "share": 0.5,
         "capacity": 1900, "ffs_kmh": 60, "length_km": 0.6},
        {"id": "merge", "kind": "merge", "load": "mainline", "share": 1.0,
         "capacity": None, "ffs_kmh": None, "length_km": 0.5},
    ],
    "Directional T": [
        {"id": "direct_ramp", "kind": "ramp", "load": "turn", "share": 0.5,
         "capacity": 2200, "ffs_kmh": 80, "length_km": 0.8},
        {"id": "direct_ramp_2", "kind": "ramp", "load": "turn", "share": 0.5,
         "capacity": 2100, "ffs_kmh": 70, "length_km": 0.6},
        {"id": "merge", "kind": "merge", "load": "mainline", "share": 1.0,
         "capacity": None, "ffs_kmh": None, "length_km": 0.5},
    ],
}

ELEMENT_LABELS: Dict[str, Tuple[str, str]] = {   # id → (EN, UK)
    "loop_ramp":           ("Loop ramp", "Петльовий з'їзд"),
    "outer_ramp":          ("Outer (right-turn) ramp", "Зовнішній правоповоротний з'їзд"),
    "weave":               ("Weaving section", "Ділянка переплетення"),
    "merge":               ("Mainline merge", "Злиття на основній дорозі"),
    "semi_direct_ramp":    ("Semi-direct ramp", "Напівпрямий з'їзд"),
    "direct_ramp":         ("Direct ramp", "Прямий з'їзд"),
    "direct_ramp_2":       ("Direct ramp (2nd)", "Прямий з'їзд (2-й)"),
    "signal_terminal":     ("Signalised ramp terminal", "Регульований вузол з'їзду"),
    "single_point_signal": ("Single-point signal", "Єдиний світлофорний вузол"),
    "crossover_signal":    ("Crossover signal", "Світлофор на перехресті потоків"),
    "ramp":                ("Ramp", "З'їзд"),
}

# Basic freeway lane capacity (HCM 7 Eq. 12-6): 2,200 + 10·(FFS[mi/h] − 50) pc/h/ln, ≤ 2,400.
LANE_CAPACITY_BASE = 2200.0
LANE_CAPACITY_PER_MPH = 10.0
LANE_CAPACITY_MAX = 2400.0
LANE_CAPACITY_MIN = 1900.0

# BPR delay parameters (traffic_engine.bpr_travel_time) and annualisation.
BPR_ALPHA = 0.15
BPR_BETA = 4.0
# Equivalent full peak hours per year: two peak hours on ~250 working days. Off-peak delay is
# taken as negligible.
PEAK_HOURS_PER_YEAR = 500.0

# V/C thresholds reported as milestones: LOS E starts above 0.93, capacity at 1.0.
VC_LOS_E = 0.93
VC_CAPACITY = 1.0

# ---------------------------------------------------------------------------
# Safety: expected crashes (rate per million entering vehicles × CMFs)
# ---------------------------------------------------------------------------
# N = R · AADT_t · 365 · 1e-6 · CMF_speed · CMF_congestion. R (crashes per million entering
# vehicles) follows the interchange-type ordering reported in the HSM Part C freeway-ramp models,
# FHWA DDI / SPUI before-after studies and PIARC: weaving loops and signalised terminals highest,
# fully directional ramps lowest. ``fi_share`` is the fatal-and-injury share of those crashes.

CRASH_RATE_PER_MEV: Dict[str, float] = {
    "Cloverleaf":      0.55,
    "Turbine":         0.35,
    "Stack (4-Level)": 0.30,
    "Diamond":         0.60,
    "SPUI":            0.48,
    "DDI":             0.40,
    "Trumpet":         0.42,
    "Directional T":   0.30,
}

FI_SHARE: Dict[str, float] = {
    "Cloverleaf":      0.31,
    "Turbine":         0.28,
    "Stack (4-Level)": 0.27,
    "Diamond":         0.33,
    "SPUI":            0.31,
    "DDI":             0.25,
    "Trumpet":         0.29,
    "Directional T":   0.27,
}

# Loop ramps above this design speed: crashes × (1 + CMF_LOOP_PER_20KMH per 20 km/h over).
# Mirrors the safety-index rule in adjustment_rules.py.
CMF_LOOP_SPEED_THRESHOLD = 80
CMF_LOOP_PER_20KMH = 0.10
# Congestion: crashes × (1 + CMF_CONGESTION_SLOPE · (V/C − CMF_CONGESTION_START)) above the start.
CMF_CONGESTION_START = 0.85
CMF_CONGESTION_SLOPE = 0.8

# ---------------------------------------------------------------------------
# Economics (Phase 2)
# ---------------------------------------------------------------------------
# Crash unit costs: HSM (2010) Table 4-3 comprehensive societal costs (2001 USD: fatal-and-injury
# KABC $158,200, PDO $7,400) indexed by CPI to ≈ 2024 (×1.8), rounded.
CRASH_COST_FI_USD = 285_000.0
CRASH_COST_PDO_USD = 13_000.0
# Straight-line residual value of the structure at the end of the analysis period.
SERVICE_LIFE_YEARS = 50
