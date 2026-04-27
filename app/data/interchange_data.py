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

CRITERION_LABELS_UK: Dict[str, str] = {
    "construction_cost_mln": "Вартість будівництва",
    "land_area_hectares":    "Площа ділянки",
    "throughput_vph":        "Пропускна здатність (авт/год)",
    "safety_index":          "Індекс безпеки",
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
# Context category keys — Ukrainian translations
# ---------------------------------------------------------------------------

INTERCHANGE_CONTEXT_LABELS_UK: Dict[str, str] = {
    "System (Highway + Highway)": "Системний (автодорога + автодорога)",
    "Service (Highway + Urban)":  "Сервісний (автодорога + місто)",
    "T-Type (3 Directions)":      "Т-подібний (3 напрямки)",
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

ALTERNATIVE_DESCRIPTIONS_UK: Dict[str, str] = {
    "Cloverleaf": (
        "Різнорівневий транспортний розв'язок з 4 петльовими з'їздами. Висока пропускна "
        "здатність і безперервний рух без світлофорів, проте петльова геометрія потребує "
        "великої площі, а секції переплетення між з'їздами знижують безпеку при великих обсягах."
    ),
    "Turbine": (
        "Напрямний розв'язок із напівпрямими з'їздами, розташованими за схемою турбіни. "
        "Усуває конфлікти переплетення, забезпечує вищу пропускну здатність і безпеку, "
        "але потребує значних земельних ресурсів і капітальних витрат на будівництво."
    ),
    "Stack (4-Level)": (
        "Чотирирівневий повністю напрямний різнорівневий розв'язок. Найбільш місткий і "
        "безпечний тип системного розв'язку; всі рухи прямі, без переплетення та затримок "
        "на світлофорах, ціною максимальної складності будівництва."
    ),
    "Diamond": (
        "Стандартний ромбоподібний розв'язок з чотирма терміналами з'їздів, керованими "
        "світлофорами або кільцями на перетинах з артеріальною дорогою. Економічний і "
        "компактний, але наземні перетини зі світлофорами вносять затримки й обмежують "
        "пікову пропускну здатність."
    ),
    "SPUI": (
        "Міський розв'язок з єдиною точкою (SPUI): всі рухи з'їздів сходяться в одному "
        "регульованому перетині. Поєднує пропускну здатність, близьку до «конюшини», з "
        "компактним міським слідом — оптимальний для стиснених коридорів, де вартість "
        "відведення землі є критичною."
    ),
    "DDI": (
        "Розв'язок типу Diverging Diamond (DDI): транспорт перетинає на протилежний бік "
        "дороги в двох регульованих точках, усуваючи конфлікти лівого повороту. Висока "
        "пропускна здатність і надійний показник безпеки в сучасних проєктах Північної "
        "Америки та Європи."
    ),
    "Trumpet": (
        "Триногий розв'язок з петльовим з'їздом для одного напряму повороту і прямими "
        "з'їздами для двох інших. Типовий для кінцевих ділянок автодоріг; економічний, "
        "з помірним слідом і хорошими характеристиками безпеки."
    ),
    "Directional T": (
        "Триногий напрямний розв'язок із напівпрямими естакадними з'їздами. Забезпечує "
        "максимальну пропускну здатність і безпеку для Т-подібних перетинів ціною вищих "
        "витрат на будівництво та більших вимог до земельних ресурсів."
    ),
}

# ---------------------------------------------------------------------------
# Static visual asset paths — display only, NEVER parsed
# ---------------------------------------------------------------------------

BLUEPRINT_PATHS: Dict[str, str] = {
    "Cloverleaf":              "assets/blueprints/cloverleaf.png",
    "Turbine":                 "assets/blueprints/turbine.png",
    "Stack (4-Level)":         "assets/blueprints/stack.png",
    "Diamond":                 "assets/blueprints/diamond.png",
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
# Detailed interchange profiles — engineering context for the analytical view
# ---------------------------------------------------------------------------
# Each entry maps an alternative name to a dict with:
#   lat, lon        — coordinates of a real-world example of this interchange type
#   example_name    — human-readable location label for the map popup
#   pros            — list of engineering advantages (FHWA/HCM sourced)
#   cons            — list of engineering limitations
#   engineering_desc — extended markdown description (FHWA/HCM/PIARC context)

DETAILED_INTERCHANGE_INFO: Dict[str, dict] = {
    "Cloverleaf": {
        "lat": 52.17571085485798,
        "lon": 5.42835179002764,
        "example_name": "A1/A28 Knooppunt Hoevelaken, Netherlands",
        "pros": [
            "Full free-flow movement — no traffic signals required",
            "Moderate construction cost relative to directional interchanges",
            "Well-understood design with extensive AASHTO/FHWA guidance",
            "Simultaneous left-turn accommodation via loop ramps",
        ],
        "cons": [
            "Large right-of-way footprint (typically 16–25 ha)",
            "Weaving sections between successive loop ramps degrade capacity at high volumes",
            "Low-speed loop geometry (40–55 km/h design speed) creates merge conflicts",
            "Lower safety index due to speed differentials and weaving (PIARC, 2019)",
        ],
        "engineering_desc": (
            "The cloverleaf interchange is a grade-separated junction where each turning "
            "movement is served by a loop ramp in one of the four quadrants. Per the "
            "**AASHTO Green Book (7th Ed.)**, loop ramp design speeds range from 25–50 km/h "
            "depending on the ramp radius.\n\n"
            "**HCM 7th Edition (Chapter 14)** notes that weaving segments between consecutive "
            "on- and off-ramps are the primary capacity bottleneck. The effective Level of "
            "Service degrades rapidly above 3,500–4,000 veh/hr aggregate volume.\n\n"
            "Modern practice favours *collector-distributor (C-D) roads* to mitigate weaving, "
            "effectively converting a basic cloverleaf into a *partial cloverleaf with C-D* "
            "(FHWA, 2023)."
        ),
    },
    "Turbine": {
        "lat": 35.34832579634311,
        "lon": -80.73352264845165,
        "example_name": "I-485/I-85 Turbine Interchange, Charlotte, NC",
        "pros": [
            "Eliminates all weaving conflicts — direct/semi-direct ramps only",
            "High throughput capacity (5,500–7,000 veh/hr per HCM Ch. 14)",
            "Excellent safety record — no speed-differential merge conflicts",
            "Aesthetically efficient footprint relative to capacity delivered",
        ],
        "cons": [
            "Significant construction cost due to multilevel flyover ramps",
            "Larger right-of-way than stacked designs (25–30 ha typical)",
            "Complex drainage design due to curved, elevated ramp geometry",
            "Longer construction timeline compared to at-grade alternatives",
        ],
        "engineering_desc": (
            "The turbine interchange arranges semi-direct ramps in a spiralling pattern, "
            "eliminating the weaving segments inherent in cloverleaf designs. "
            "**FHWA Interchange Justification Report Guidelines (2023)** classify turbine "
            "interchanges as a *system interchange* suitable for freeway-to-freeway junctions "
            "with projected AADT above 80,000.\n\n"
            "Per **HCM 7th Edition**, the absence of weaving allows sustained LOS C/D operation "
            "at volumes that would push a cloverleaf into LOS E/F. The curving flyover ramps "
            "are typically designed for 60–80 km/h, significantly higher than cloverleaf loops.\n\n"
            "Widely adopted in the Netherlands and Germany, the turbine is considered "
            "a best-practice design for high-volume, space-conscious system interchanges "
            "(PIARC Road Safety Manual, 2019)."
        ),
    },
    "Stack (4-Level)": {
        "lat": 29.780682113553848,
        "lon": -95.45416042412587,
        "example_name": "Judge Harry Pregerson Interchange (I-105/I-110), Los Angeles, CA",
        "pros": [
            "Maximum throughput — all movements are direct with no weaving or signals",
            "Highest safety index among system interchanges (AASHTO HSM, 2022)",
            "Minimal land footprint for capacity delivered (10–15 ha typical)",
            "Design speeds of 50–80 km/h on all ramps — no slow loops",
        ],
        "cons": [
            "Highest construction cost of all interchange types (typically $60–120M+)",
            "Maximum structural complexity — 3 or 4 bridge levels required",
            "Visual impact and noise propagation due to elevated structures",
            "Long construction duration (5–8 years for major urban stacks)",
        ],
        "engineering_desc": (
            "The four-level stack interchange provides fully directional, grade-separated "
            "connections for all turning movements using stacked flyover ramps. "
            "**FHWA (2023)** considers this the highest-capacity system interchange form, "
            "justified only when projected volumes exceed the capacity of turbine or "
            "cloverleaf alternatives.\n\n"
            "**HCM 7th Edition (Chapter 14)** reports effective capacity of 7,000–8,500 "
            "veh/hr with sustained LOS C. The absence of weaving, loop-ramp speed "
            "differentials, and at-grade conflicts yields the highest safety index "
            "per **AASHTO Highway Safety Manual (2022)**.\n\n"
            "The vertical stacking of four structural levels compresses the ground-level "
            "footprint to roughly 10–15 ha — considerably less than a cloverleaf serving "
            "the same volume — at the cost of significant structural engineering investment."
        ),
    },
    "Diamond": {
        "lat": 38.6274825958427,
        "lon": -90.21773134487837,
        "example_name": "I-64 / Jefferson Ave Diamond, St. Louis, MO",
        "pros": [
            "Lowest construction cost of all interchange types",
            "Minimal right-of-way requirement (3–6 ha typical)",
            "Simple, well-understood design — rapid construction timeline",
            "Easily retrofittable with roundabouts or adaptive signal control",
        ],
        "cons": [
            "At-grade signal crossings limit peak throughput to ~2,500 veh/hr",
            "Signal delay degrades LOS during peak hours (HCM Ch. 23)",
            "Left-turn conflict points reduce safety compared to grade-separated designs",
            "Not suitable for freeway-to-freeway (system) interchange applications",
        ],
        "engineering_desc": (
            "The conventional diamond interchange connects a limited-access highway to an "
            "arterial via four ramp terminals — two on each side of the overpass. "
            "**AASHTO Green Book (7th Ed.)** identifies it as the default service interchange "
            "for low-to-moderate volume crossings.\n\n"
            "Per **HCM 7th Edition (Chapter 23)**, the signalised ramp terminals are the "
            "capacity bottleneck; adaptive signal control (SCOOT/SCATS) can improve throughput "
            "by 10–15% over fixed-time plans.\n\n"
            "**FHWA (2023)** notes that the diamond is the most cost-effective interchange "
            "where AADT is below 30,000 and left-turn volumes are moderate."
        ),
    },
    "SPUI": {
        "lat": 33.567584165755285,
        "lon": -112.117341986649,
        "example_name": "I-17 / Dunlap Ave SPUI, Phoenix, AZ",
        "pros": [
            "Single signal phase handles all movements — high throughput for footprint",
            "Compact urban footprint (3–5 ha typical)",
            "Reduces conflict points vs. conventional diamond (fewer signal phases)",
            "Strong LOS performance at moderate-to-high volumes (HCM Ch. 23)",
        ],
        "cons": [
            "Higher construction cost than diamond due to wider bridge structure",
            "Single-point signal failure cascades to entire interchange",
            "Pedestrian accommodation requires careful design (FHWA Ped. Guide, 2023)",
            "Complex signal timing — requires experienced traffic engineering",
        ],
        "engineering_desc": (
            "The Single Point Urban Interchange (SPUI) consolidates all ramp movements "
            "into one signalised intersection positioned directly under or over the freeway "
            "bridge. **FHWA Technical Advisory T6640.8A** recommends SPUIs where conventional "
            "diamonds exceed capacity but land constraints preclude a DDI or cloverleaf.\n\n"
            "**HCM 7th Edition (Chapter 23)** reports that a well-designed SPUI achieves "
            "throughput of 4,000–5,000 veh/hr — nearly double a conventional diamond — "
            "through its efficient two-phase signal cycle.\n\n"
            "The design requires a wider bridge deck (typically 40–60 m) compared to a "
            "diamond (20–30 m), increasing structural cost by 30–50% (NCHRP Report 345)."
        ),
    },
    "DDI": {
        "lat": 37.2503533593438,
        "lon": -93.31069441742719,
        "example_name": "I-44 / Route 13 DDI, Springfield, MO (first US DDI, 2009)",
        "pros": [
            "Eliminates left-turn conflict points — strong safety improvement (40–60% crash reduction)",
            "High throughput with only two signal phases per crossover",
            "Moderate construction cost — often a retrofit of existing diamond",
            "Proven safety record: 100+ US installations since 2009 (FHWA EDC-4)",
        ],
        "cons": [
            "Counter-intuitive driver experience at crossover points",
            "Requires clear wayfinding signage and positive guidance markings",
            "Slightly larger footprint than conventional diamond (5–7 ha)",
            "Limited pedestrian/bicycle accommodation without dedicated facilities",
        ],
        "engineering_desc": (
            "The Diverging Diamond Interchange (DDI), also known as the Double Crossover "
            "Diamond (DCD), routes traffic to the left side of the road between two "
            "signalised crossover points. This geometry eliminates all left-turn conflict "
            "points, dramatically improving safety.\n\n"
            "**FHWA Every Day Counts (EDC-4)** promoted the DDI as a proven innovation; "
            "crash studies at early installations (e.g., I-44/Route 13, Springfield, MO) "
            "reported 40–60% reduction in total crashes.\n\n"
            "**HCM 7th Edition** notes that the two-phase crossover signal achieves "
            "throughput comparable to a SPUI (5,000–6,000 veh/hr) at 60–70% of SPUI "
            "construction cost, making it an increasingly popular retrofit option."
        ),
    },
    "Trumpet": {
        "lat": 51.757061532105844,
        "lon": -0.4163784923468657,
        "example_name": "M1 Junction 8, Hemel Hempstead, UK",
        "pros": [
            "Cost-effective three-leg interchange — one loop + two direct ramps",
            "Moderate footprint (8–12 ha typical)",
            "Good safety for T-junction applications (AASHTO HSM, 2022)",
            "Simple design with proven performance for highway termini",
        ],
        "cons": [
            "One loop ramp introduces speed differential and potential weaving",
            "Not expandable to four-leg operation without major reconstruction",
            "Loop ramp capacity is the system bottleneck at high volumes",
            "Limited to three-leg (T-junction) configurations only",
        ],
        "engineering_desc": (
            "The trumpet interchange serves three-leg (T-junction) connections where a "
            "highway terminates or a major ramp branches. One movement uses a loop ramp "
            "while the other two use semi-direct or direct ramps.\n\n"
            "**AASHTO Green Book (7th Ed.)** specifies trumpet interchanges for freeway "
            "termini where traffic demand on the loop movement is moderate (<1,500 veh/hr).\n\n"
            "**HCM 7th Edition** capacity analysis shows the loop ramp governs overall "
            "interchange capacity. **PIARC (2019)** rates trumpets favourably for safety "
            "among T-junction solutions due to the limited number of conflict points."
        ),
    },
    "Directional T": {
        "lat": 55.832584716078884,
        "lon": -4.101001282052542,
        "example_name": "US-59 / I-610 West Loop Interchange, Houston, TX",
        "pros": [
            "Maximum throughput for three-leg junctions — all movements semi-direct",
            "Highest safety index for T-junction category (AASHTO HSM, 2022)",
            "No loop ramp speed differentials — higher design speeds on all ramps",
            "Scalable — can accommodate very high turning volumes (>5,000 veh/hr)",
        ],
        "cons": [
            "High construction cost due to multilevel flyover ramps",
            "Large right-of-way requirement (12–18 ha typical)",
            "Complex structural engineering — multiple bridge levels",
            "Longer construction timeline than trumpet alternatives",
        ],
        "engineering_desc": (
            "The Directional T interchange replaces the trumpet's loop ramp with a "
            "semi-direct flyover, providing high-speed, free-flow connections for all "
            "three turning movements.\n\n"
            "**FHWA (2023)** recommends the directional T when peak-hour turning volumes "
            "exceed the capacity of a trumpet's loop ramp (typically >2,000 veh/hr) or "
            "when the mainline design speed exceeds 100 km/h.\n\n"
            "**HCM 7th Edition** reports that directional T interchanges sustain LOS C at "
            "volumes that would degrade a trumpet to LOS E. **AASHTO HSM (2022)** assigns "
            "the highest safety performance function (SPF) scores among T-junction designs."
        ),
    },
}

# ---------------------------------------------------------------------------
# Detailed interchange profiles — Ukrainian translations
# ---------------------------------------------------------------------------

DETAILED_INTERCHANGE_INFO_UK: Dict[str, dict] = {
    "Cloverleaf": {
        "pros": [
            "Повністю безперервний рух — світлофорів не потрібно",
            "Помірна вартість будівництва порівняно з напрямними розв'язками",
            "Добре вивчена конструкція з детальними рекомендаціями AASHTO/FHWA",
            "Одночасне обслуговування лівих поворотів через петлеві з'їзди",
        ],
        "cons": [
            "Великий земельний слід (зазвичай 16–25 га)",
            "Секції переплетення між послідовними петлями знижують пропускну здатність при великих обсягах",
            "Низькошвидкісна геометрія петель (розрахункова швидкість 40–55 км/год) створює конфлікти злиття",
            "Нижчий індекс безпеки через перепади швидкостей та переплетення (PIARC, 2019)",
        ],
        "engineering_desc": (
            "Розв'язок типу «конюшина» — різнорівневий вузол, де кожен напрям повороту "
            "обслуговується петльовим з'їздом в одному з чотирьох квадрантів. Згідно з "
            "**AASHTO Green Book (7-е вид.)**, розрахункова швидкість петльових з'їздів "
            "становить 25–50 км/год залежно від радіуса.\n\n"
            "**HCM 7-е видання (Глава 14)** зазначає, що секції переплетення між послідовними "
            "з'їздами є основним вузьким місцем за пропускною здатністю. Ефективний рівень "
            "обслуговування різко погіршується при сумарному обсязі понад 3 500–4 000 авт/год.\n\n"
            "Сучасна практика надає перевагу *дорогам-колекторам (C-D)* для зменшення "
            "переплетення, перетворюючи звичайну «конюшину» на *часткову з C-D дорогами* "
            "(FHWA, 2023)."
        ),
    },
    "Turbine": {
        "pros": [
            "Усуває всі конфлікти переплетення — лише прямі/напівпрямі з'їзди",
            "Висока пропускна здатність (5 500–7 000 авт/год за HCM Гл. 14)",
            "Відмінний показник безпеки — відсутні конфлікти злиття при перепадах швидкостей",
            "Ефективний земельний слід відносно забезпечуваної пропускної здатності",
        ],
        "cons": [
            "Значні витрати на будівництво через багаторівневі естакадні з'їзди",
            "Більша площа відчуження ніж у штабельних конструкцій (зазвичай 25–30 га)",
            "Складне проєктування дренажу через криволінійну підняту геометрію з'їздів",
            "Триваліший термін будівництва порівняно з наземними альтернативами",
        ],
        "engineering_desc": (
            "Розв'язок «турбіна» розташовує напівпрямі з'їзди по спіральній схемі, "
            "усуваючи секції переплетення, властиві «конюшині». "
            "**FHWA Interchange Justification Report Guidelines (2023)** відносять турбінні "
            "розв'язки до **системних**, придатних для з'єднань автодорога–автодорога при "
            "прогнозованому AADT понад 80 000.\n\n"
            "Згідно з **HCM 7-е видання**, відсутність переплетення забезпечує стійкий рівень "
            "обслуговування C/D при обсягах, що переводять «конюшину» до рівня E/F. "
            "Криволінійні естакадні з'їзди зазвичай розраховуються на 60–80 км/год — значно "
            "вище, ніж петлі «конюшини».\n\n"
            "Широко застосовується в Нідерландах та Німеччині; турбіна вважається найкращою "
            "практикою для великовантажних системних розв'язків (PIARC Road Safety Manual, 2019)."
        ),
    },
    "Stack (4-Level)": {
        "pros": [
            "Максимальна пропускна здатність — всі рухи прямі, без переплетення та світлофорів",
            "Найвищий індекс безпеки серед системних розв'язків (AASHTO HSM, 2022)",
            "Мінімальний земельний слід для забезпечуваної пропускної здатності (зазвичай 10–15 га)",
            "Розрахункова швидкість 50–80 км/год на всіх з'їздах — без повільних петель",
        ],
        "cons": [
            "Найвища вартість будівництва серед усіх типів розв'язків (зазвичай $60–120 млн+)",
            "Максимальна конструктивна складність — потрібні 3 або 4 рівні мостів",
            "Візуальний вплив і поширення шуму через підняті конструкції",
            "Тривалий термін будівництва (5–8 років для великих міських штабелів)",
        ],
        "engineering_desc": (
            "Чотирирівневий штабельний розв'язок забезпечує повністю напрямні різнорівневі "
            "з'єднання для всіх напрямів повороту за допомогою штабельованих естакадних з'їздів. "
            "**FHWA (2023)** вважає його найбільш місткою формою системного розв'язку, "
            "виправданою лише тоді, коли прогнозовані обсяги перевищують пропускну здатність "
            "турбінних або «конюшинних» альтернатив.\n\n"
            "**HCM 7-е видання (Глава 14)** повідомляє про ефективну пропускну здатність "
            "7 000–8 500 авт/год при стійкому рівні обслуговування C. Відсутність переплетення, "
            "перепадів швидкостей на петлях та наземних конфліктів забезпечує найвищий індекс "
            "безпеки згідно з **AASHTO Highway Safety Manual (2022)**.\n\n"
            "Вертикальне штабелювання чотирьох конструктивних рівнів стискає наземний слід до "
            "приблизно 10–15 га — значно менше, ніж у «конюшини» з такою ж пропускною "
            "здатністю, — ціною значних інвестицій у конструктивне проєктування."
        ),
    },
    "Diamond": {
        "pros": [
            "Найнижча вартість будівництва серед усіх типів розв'язків",
            "Мінімальна вимога до земельних ресурсів (зазвичай 3–6 га)",
            "Проста, добре відома конструкція — короткий термін будівництва",
            "Легко переобладнується з кільцями або адаптивним керуванням сигналами",
        ],
        "cons": [
            "Наземні перетини зі світлофорами обмежують пікову пропускну здатність до ~2 500 авт/год",
            "Затримки на світлофорах знижують рівень обслуговування в пікові години (HCM Гл. 23)",
            "Конфліктні точки лівого повороту знижують безпеку порівняно з різнорівневими конструкціями",
            "Не підходить для міжмагістральних (системних) застосувань",
        ],
        "engineering_desc": (
            "Стандартний ромбоподібний розв'язок з'єднує дорогу з обмеженим доступом з "
            "артеріальною через чотири термінали з'їздів — по два з кожного боку шляхопроводу. "
            "**AASHTO Green Book (7-е вид.)** визначає його як типовий сервісний розв'язок для "
            "перетинів з низьким і помірним обсягом руху.\n\n"
            "Згідно з **HCM 7-е видання (Глава 23)**, регульовані термінали з'їздів є вузьким "
            "місцем за пропускною здатністю; адаптивне керування сигналами (SCOOT/SCATS) може "
            "підвищити пропускну здатність на 10–15% порівняно з фіксованими планами.\n\n"
            "**FHWA (2023)** зазначає, що ромбоподібний розв'язок є найбільш економічним при "
            "AADT нижче 30 000 та помірних обсягах лівого повороту."
        ),
    },
    "SPUI": {
        "pros": [
            "Одна фаза світлофора обслуговує всі рухи — висока пропускна здатність для свого сліду",
            "Компактний міський слід (зазвичай 3–5 га)",
            "Зменшує конфліктні точки порівняно зі стандартним ромбом (менше фаз)",
            "Хороший рівень обслуговування при помірних та великих обсягах (HCM Гл. 23)",
        ],
        "cons": [
            "Вища вартість будівництва, ніж у ромбі, через ширшу конструкцію моста",
            "Відмова єдиної точки сигналізації поширюється на весь розв'язок",
            "Забезпечення пішоходів потребує ретельного проєктування (FHWA Ped. Guide, 2023)",
            "Складне регулювання сигналів — потрібен досвідчений інженер з дорожнього руху",
        ],
        "engineering_desc": (
            "Міський розв'язок з єдиною точкою (SPUI) концентрує всі рухи з'їздів в одному "
            "регульованому перетині, розташованому безпосередньо під мостом або над ним. "
            "**FHWA Technical Advisory T6640.8A** рекомендує SPUI там, де стандартний ромб "
            "перевищує пропускну здатність, але земельні обмеження не дозволяють використати "
            "DDI або «конюшину».\n\n"
            "**HCM 7-е видання (Глава 23)** повідомляє, що добре спроєктований SPUI досягає "
            "пропускної здатності 4 000–5 000 авт/год — майже вдвічі більше, ніж стандартний "
            "ромб, — завдяки ефективному двофазному циклу.\n\n"
            "Конструкція потребує ширшого полотна моста (зазвичай 40–60 м) порівняно з ромбом "
            "(20–30 м), що збільшує конструктивні витрати на 30–50% (NCHRP Report 345)."
        ),
    },
    "DDI": {
        "pros": [
            "Усуває конфліктні точки лівого повороту — суттєве покращення безпеки (зниження ДТП на 40–60%)",
            "Висока пропускна здатність лише при двох фазах світлофора на кожному перетині",
            "Помірна вартість будівництва — часто реконструкція наявного ромба",
            "Підтверджена безпека: 100+ об'єктів у США з 2009 року (FHWA EDC-4)",
        ],
        "cons": [
            "Неочевидний досвід водіння в точках перетину",
            "Потребує чіткого навігаційного знакування та орієнтуючої розмітки",
            "Дещо більший слід, ніж у стандартного ромба (5–7 га)",
            "Обмежене забезпечення пішоходів/велосипедистів без спеціальних споруд",
        ],
        "engineering_desc": (
            "Розв'язок типу DDI (Diverging Diamond Interchange), також відомий як Double "
            "Crossover Diamond (DCD), переводить транспорт на ліву смугу між двома "
            "регульованими точками перетину. Ця геометрія усуває всі конфліктні точки лівого "
            "повороту, суттєво підвищуючи безпеку.\n\n"
            "**FHWA Every Day Counts (EDC-4)** просував DDI як перевірену інновацію; дослідження "
            "ДТП на ранніх об'єктах (напр., I-44/Route 13, Спрингфілд, МО) зафіксували зниження "
            "загальної кількості аварій на 40–60%.\n\n"
            "**HCM 7-е видання** зазначає, що двофазний перетинний сигнал забезпечує пропускну "
            "здатність, порівнянну з SPUI (5 000–6 000 авт/год), при 60–70% вартості будівництва "
            "SPUI, що робить його дедалі популярнішим варіантом реконструкції."
        ),
    },
    "Trumpet": {
        "pros": [
            "Економічний триногий розв'язок — одна петля та два прямі з'їзди",
            "Помірний слід (зазвичай 8–12 га)",
            "Хороша безпека для Т-подібних застосувань (AASHTO HSM, 2022)",
            "Проста конструкція з підтвердженими характеристиками для кінцевих ділянок",
        ],
        "cons": [
            "Один петльовий з'їзд вносить перепад швидкостей і потенційне переплетення",
            "Неможливо розширити до чотириногої схеми без масштабної реконструкції",
            "Пропускна здатність петльового з'їзду є вузьким місцем при великих обсягах",
            "Обмежено лише триногими (Т-подібними) конфігураціями",
        ],
        "engineering_desc": (
            "Розв'язок «труба» обслуговує триногі (Т-подібні) з'єднання, де дорога "
            "закінчується або відгалужується великий з'їзд. Один напрям використовує петльовий "
            "з'їзд, тоді як два інші — напівпрямі або прямі.\n\n"
            "**AASHTO Green Book (7-е вид.)** передбачає «труби» для кінцевих ділянок "
            "автодоріг, де попит на петльовий рух є помірним (<1 500 авт/год).\n\n"
            "Аналіз пропускної здатності за **HCM 7-е видання** показує, що петльовий з'їзд "
            "визначає загальну пропускну здатність розв'язку. **PIARC (2019)** позитивно "
            "оцінює «труби» за безпекою серед Т-подібних рішень через обмежену кількість "
            "конфліктних точок."
        ),
    },
    "Directional T": {
        "pros": [
            "Максимальна пропускна здатність для триногих вузлів — всі рухи напівпрямі",
            "Найвищий індекс безпеки в категорії Т-подібних розв'язків (AASHTO HSM, 2022)",
            "Без перепадів швидкостей на петлях — вища розрахункова швидкість на всіх з'їздах",
            "Масштабується для дуже великих обсягів поворотів (>5 000 авт/год)",
        ],
        "cons": [
            "Висока вартість будівництва через багаторівневі естакадні з'їзди",
            "Великий земельний слід (зазвичай 12–18 га)",
            "Складне конструктивне проєктування — кілька рівнів мостів",
            "Триваліший термін будівництва порівняно з «трубою»",
        ],
        "engineering_desc": (
            "Напрямний Т-розв'язок замінює петльовий з'їзд «труби» напівпрямою естакадою, "
            "забезпечуючи високошвидкісний безперервний рух для всіх трьох напрямів повороту.\n\n"
            "**FHWA (2023)** рекомендує напрямний Т, коли обсяги в пікову годину перевищують "
            "пропускну здатність петльового з'їзду «труби» (зазвичай >2 000 авт/год) або коли "
            "розрахункова швидкість головної дороги перевищує 100 км/год.\n\n"
            "**HCM 7-е видання** повідомляє, що напрямні Т-розв'язки підтримують рівень "
            "обслуговування C при обсягах, що переводять «трубу» до рівня E. "
            "**AASHTO HSM (2022)** присвоює найвищі оцінки функції безпеки (SPF) серед "
            "Т-подібних конструкцій."
        ),
    },
}

# ---------------------------------------------------------------------------
# Locale-aware resolver functions
# ---------------------------------------------------------------------------

def resolve_criterion_labels(locale: str) -> Dict[str, str]:
    if locale == "uk":
        return CRITERION_LABELS_UK
    return CRITERION_LABELS


def resolve_alternative_description(name: str, locale: str) -> str:
    if locale == "uk":
        return ALTERNATIVE_DESCRIPTIONS_UK.get(name, ALTERNATIVE_DESCRIPTIONS.get(name, ""))
    return ALTERNATIVE_DESCRIPTIONS.get(name, "")


def resolve_interchange_detail(name: str, locale: str) -> dict:
    base = DETAILED_INTERCHANGE_INFO.get(name)
    if not base:
        return {}
    if locale != "uk":
        return base
    uk = DETAILED_INTERCHANGE_INFO_UK.get(name, {})
    return {
        **base,
        "pros":             uk.get("pros",             base.get("pros", [])),
        "cons":             uk.get("cons",             base.get("cons", [])),
        "engineering_desc": uk.get("engineering_desc", base.get("engineering_desc", "")),
    }


def resolve_context_label(context: str, locale: str) -> str:
    if locale == "uk":
        return INTERCHANGE_CONTEXT_LABELS_UK.get(context, context)
    return context


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
