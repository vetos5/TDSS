"""
Design dimensions for the procedural interchange footprints (``app/infrastructure/generators.py``).

The footprints are schematic, not a design: they place each interchange type on the map at a
believable real-world size so the planner can judge the land it takes and the buildings it hits.
Every number below is a typical value for its element, chosen to sit inside the usual design range
rather than at a code minimum. Radii follow from the design speed of the movement they carry, the
way AASHTO's *A Policy on Geometric Design of Highways and Streets* (the Green Book, 7th ed., 2018)
tabulates minimum radius against speed and superelevation:

    R_min = V² / (127 · (e_max + f_max))      (V in km/h, R in metres)

With e_max = 8 % this gives about 45 m at 40 km/h, 80 m at 50 km/h, 135 m at 60 km/h and 195 m
at 70 km/h. Lane width is the 3.75 m of the Ukrainian highway standard DBN V.2.3-4 for category
I–II roads (AASHTO's 3.6 m is close enough not to change the drawing). Traffic keeps to the right.

Each generator still accepts its old keyword arguments (radius, lane counts, lengths...) so the
legacy Streamlit view keeps working; anything it does not pass comes from here.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Cross-section
# ---------------------------------------------------------------------------
LANE_WIDTH_M = 3.75              # DBN V.2.3-4, categories I-II
FREEWAY_LANES = 3                # per direction, both roads of a system interchange
ARTERIAL_LANES = 2               # per direction, the crossroad of a service interchange
RAMP_LANES = 1                   # single-lane ramps; directional ramps may use 2
FREEWAY_MEDIAN_M = 4.0           # narrow median with a barrier, as near an interchange
ARTERIAL_MEDIAN_M = 2.0          # raised kerb median on the crossroad

# ---------------------------------------------------------------------------
# Ramp alignment
# ---------------------------------------------------------------------------
# A ramp leaves or joins its carriageway along a parallel auxiliary lane (the parallel-type
# speed-change lane of the Green Book, §10.9.6) before it curves away. The drawing keeps a
# shortened parallel run: long enough to read as a merge on the map, short enough not to dominate.
SPEED_CHANGE_RUN_M = 60.0

# Loop ramps of a cloverleaf and a trumpet: 40 km/h loop, the common 45-75 m range.
LOOP_RADIUS_M = 60.0

# Outer connectors (the right turns of every four-leg system interchange), ~50-55 km/h.
OUTER_CONNECTOR_RADIUS_M = 100.0

# Directional and semi-direct ramps (turbine, stack, trumpet and directional-T left turns).
# The main curve is designed for ~65-70 km/h; the reverse curve that swings the ramp out from
# its carriageway before it turns is flatter.
DIRECTIONAL_RADIUS_M = 180.0
DIRECTIONAL_SWING_RADIUS_M = 200.0

# Edge-to-edge gap kept between two ramps that run side by side at the same level (a verge or a
# barrier), so they never draw on top of each other.
RAMP_GAP_M = 8.0

# How far the drawn mainline and crossroad run past the outermost ramp end.
ROAD_MARGIN_M = 60.0

# ---------------------------------------------------------------------------
# Turbine and stack
# ---------------------------------------------------------------------------
# Both route every left turn on a directional ramp; what tells them apart in plan is how close
# those ramps pass the centre. A turbine's ramps spiral round it on a ring; a stack's cross over
# the centre itself, stacked on levels 3 and 4. The value is the distance from the centre at which
# each left-turn ramp passes it.
TURBINE_RING_RADIUS_M = 70.0
STACK_CENTRE_PASS_M = 14.0

# ---------------------------------------------------------------------------
# Service interchanges (diamond, SPUI, DDI)
# ---------------------------------------------------------------------------
# Distance from the freeway centreline to the ramp terminal on the crossroad. A conventional
# diamond puts its terminals 60-120 m out; a SPUI pulls them in next to the bridge so all left
# turns meet at one signal; a DDI places them between the two crossovers.
DIAMOND_TERMINAL_OFFSET_M = 80.0
SPUI_TERMINAL_OFFSET_M = 32.0
DDI_TERMINAL_OFFSET_M = 42.0

# Reverse curve that takes a diamond-type ramp from its parallel lane out to the terminal line,
# and the straight approach (queue storage) before the terminal.
TERMINAL_RAMP_RADIUS_M = 150.0
TERMINAL_RAMP_ANGLE_DEG = 18.0
TERMINAL_APPROACH_M = 45.0

# Right turns at a ramp terminal are channelised turning roadways (~25 km/h).
TERMINAL_RIGHT_TURN_RADIUS_M = 25.0

# A SPUI's left turns sweep through the one central intersection on a large radius (FHWA's
# SPUI guidance cites 50-90 m), which is what lets opposing left turns run together.
SPUI_LEFT_TURN_RADIUS_M = 60.0

# DDI: the arterial carriageways swap sides at two crossovers. FHWA's DDI guide recommends a
# crossing angle of 40-50 degrees; the crossovers sit 150-250 m apart.
DDI_CROSSOVER_ANGLE_DEG = 40.0
DDI_CROSSOVER_SPACING_M = 220.0
DDI_LEFT_TURN_RADIUS_M = 25.0

# ---------------------------------------------------------------------------
# Three-leg interchanges (trumpet, directional T)
# ---------------------------------------------------------------------------
# Length of the terminating road drawn away from the through road.
STEM_LENGTH_M = 320.0
# Where a directional T's stem splits into its two left-turn flyovers, measured back from the
# through road's centreline. The flyovers start curving there and cross the through road on the
# diagonal.
DIRECTIONAL_T_SPLIT_M = 40.0

# ---------------------------------------------------------------------------
# Roundabout (legacy view only)
# ---------------------------------------------------------------------------
ROUNDABOUT_RADIUS_M = 30.0       # circulatory centreline; a two-lane roundabout of ~70 m ICD
ROUNDABOUT_ARM_LENGTH_M = 100.0
