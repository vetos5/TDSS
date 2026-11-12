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
FREEWAY_MEDIAN_M = 4.0           # narrow median with a barrier, as near an interchange
ARTERIAL_MEDIAN_M = 2.0          # raised kerb median on the crossroad

# ---------------------------------------------------------------------------
# Lanes ("lane mathematics")
# ---------------------------------------------------------------------------
# Lanes are conserved through every interchange: a ramp is the outer lane of the carriageway it
# leaves, and becomes the outer lane of the one it joins. No lane ends in a taper and no two lanes
# merge into one, so at every diverge   lanes before = lanes carrying on + lanes of the ramp
# and at every merge                    lanes after  = lanes arriving   + lanes of the ramp.
# (AASHTO's lane-balance rule would also allow one lane more on the leaving side; conserving them
# exactly is the stricter reading, and it is the one that keeps the traffic in the 3-D model in
# its lanes.) The counts below follow from it, with two lanes left to run straight through:
FREEWAY_LANES = 3                # per direction where one lane leaves before the next one joins:
#                                  cloverleaf, diamond and the through road of the three-leg types
WIDE_FREEWAY_LANES = 4           # where two lanes leave before any joins: a turbine's and a stack's
#                                  right and left turns, and the two-lane ramps of a SPUI and a DDI
ARTERIAL_LANES = 2               # per direction, the crossroad of a diamond (plain junctions)
TURNING_ARTERIAL_LANES = 3       # SPUI and DDI: a lane each for the left turn, straight on and
#                                  the right turn, since their turns run free of the through lane
STEM_LANES = 2                   # the terminating road of a three-leg type: one lane per turn
RAMP_LANES = 1                   # single-lane ramps
TERMINAL_RAMP_LANES = 2          # SPUI and DDI ramps: a lane each for the left and the right turn

# ---------------------------------------------------------------------------
# Ramp alignment
# ---------------------------------------------------------------------------
# A ramp leaves or joins its carriageway along the outer lane, which it runs on for this far
# before it curves away (after it has straightened up): long enough to read as an exit lane on the
# map, short enough not to dominate. Traffic changes lanes across the line beside it.
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
# Both route every left turn on a directional ramp; what tells them apart in plan is where those
# ramps pass the centre. A turbine's ramps spiral round its far side on a ring, so each one
# crosses the other three. A stack's cross over the centre itself, stacked on levels 3 and 4. The
# value is the distance from the centre at which each left-turn ramp passes it; a negative one is
# on the near side, which keeps a stack's opposite left turns from crossing each other so that
# they can share a level.
TURBINE_RING_RADIUS_M = 70.0
STACK_CENTRE_PASS_M = -14.0

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
# crossing angle of 40-50 degrees. The spacing is the least distance between the crossover
# points; the generator widens it until each off-ramp's left-turn merge lane fits between its
# terminal and the bridge, which gives about 260 m.
DDI_CROSSOVER_ANGLE_DEG = 40.0
DDI_CROSSOVER_SPACING_M = 220.0
DDI_LEFT_TURN_RADIUS_M = 25.0
# The curves either side of a crossover are designed for 40 km/h (FHWA: 25-35 mph), with a
# straight tangent through the crossing itself. Before them the carriageways flare apart round an
# island on a flatter reverse curve, which is what separates them enough to cross at that angle.
DDI_CROSSOVER_RADIUS_M = 60.0
DDI_FLARE_RADIUS_M = 100.0
DDI_FLARE_ANGLE_DEG = 15.0
# Straight run of a left turn from an off-ramp, between the end of its curve and the bridge. From
# there on it is an extra lane on the outside of the carriageway, which crosses the bridge and
# leaves again as the left turn onto the opposite on-ramp.
DDI_MERGE_RUN_M = 45.0

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
# Vertical profile of the 3-D model (``app/application/model3d.py``)
# ---------------------------------------------------------------------------
# The generators are plan geometry only. The 3-D view adds a schematic vertical profile: which
# road passes over which, and the gentlest ramp gradients that give every crossing its clearance.
# It illustrates the interchange's levels; it is not a vertical design.
#
# Height between two road surfaces that cross: 5.0 m of vertical clearance (DBN V.2.3-4 for
# category I-II roads; AASHTO's 4.9 m is the same in practice) plus about 1.5 m of bridge deck.
LEVEL_STEP_M = 6.5

# Gradient of the approach to an elevated road (4 % is the usual maximum for a category I road).
# Where the drawn road is too short to come down at it, the approach is drawn steeper so that the
# road still meets the ground at its end.
APPROACH_GRADE = 0.04

# An elevated road stays level this far beyond the edge of the last road it bridges.
PLATEAU_MARGIN_M = 10.0

# A ramp holds its height from this far before the edge of a road it crosses to this far after.
CROSSING_MARGIN_M = 4.0

# Stacking order where two centrelines cross: the higher number passes over, equal numbers meet
# at grade (a ramp terminal on its crossroad, a SPUI's central intersection, a DDI's crossovers).
# Keys are segment-id prefixes, the longest match wins, and anything unlisted is 0 (ground level).
# Two flyovers of equal rank that cross (a turbine's left turns) are not at grade: the ramp that
# is further along its own path passes over, so a ramp climbs early and comes down late.
VERTICAL_ORDER: dict[str, dict[str, int]] = {
    # Freeway over freeway on one bridge; loops and connectors only join the two levels.
    "Cloverleaf": {"crossroad": 1},
    "Turbine": {
        "crossroad": 1,
        "left-from-SE": 2, "left-from-NW": 2,
        "left-from-NE": 3, "left-from-SW": 3,
    },
    # The classic four levels: opposite left turns share a level.
    "Stack (4-Level)": {
        "crossroad": 1,
        "left-from-SE": 2, "left-from-NW": 2,
        "left-from-NE": 3, "left-from-SW": 3,
    },
    # Service interchanges: the arterial and its ramp terminals sit on the bridge level.
    "Diamond": {"crossroad": 1, "ramp": 1},
    "SPUI": {"crossroad": 1, "ramp": 1},
    "DDI": {"crossroad": 1, "ramp": 1},
    # The stem bridges the through road; the loop passes under the stem.
    "Trumpet": {"stem": 1},
    # Three levels: the stem's carriageways split vertically before the flyovers leave them.
    "Directional T": {
        "mainline": 1,
        "stem-WB": 2, "flyover-stem-out": 2,
    },
}

# Traffic on an auxiliary lane (one that a ramp brings and the next ramp takes away: the weaving
# lane between a cloverleaf's loops, the extra lane over a DDI's bridge) swaps with the lane beside
# it. The swap starts and ends at most this far outside the auxiliary lane itself, on the ramps'
# runs alongside.
WEAVE_LEAD_M = 30.0

# Traffic in the 3-D model: time between two cars in a lane, and how fast speed changes along a
# lane where its limit does (per metre travelled; 0.15 takes a car from 40 to 100 km/h in ~110 m).
TRAFFIC_HEADWAY_S = 2.4
TRAFFIC_SPEED_CHANGE_PER_M = 0.15

# Two carriageways of one road that are closer than this stand on a single deck, paved across
# the median. It covers the arterial's 2 m kerbed median (ARTERIAL_MEDIAN_M), which has to be open
# where ramp traffic turns across it, and not a freeway's 4 m median with its barrier.
MEDIAN_FILL_MAX_M = 2.5

# Piers stand under a deck that is at least this high (lower approaches are drawn as fill behind
# retaining walls), at about this spacing, and never on a road passing underneath.
PIER_MIN_HEIGHT_M = 3.0
PIER_SPACING_M = 30.0
PIER_ROAD_CLEARANCE_M = 2.0

# ---------------------------------------------------------------------------
# Roundabout (legacy view only)
# ---------------------------------------------------------------------------
ROUNDABOUT_RADIUS_M = 30.0       # circulatory centreline; a two-lane roundabout of ~70 m ICD
ROUNDABOUT_ARM_LENGTH_M = 100.0
