"""
Economic and spatial domain models for interchange analysis.

Provides InterchangeMetrics with land footprint (hectares) and construction
cost ($) using Shapely for geometry and configurable unit costs.
Bridges are 7× more expensive than at-grade asphalt.
"""

from __future__ import annotations

from dataclasses import dataclass

from shapely.ops import unary_union

from app.domain.geometry import METRES_PER_COORD, RoadNetwork


# Unit costs (USD): asphalt at-grade, bridge/structure (7× asphalt)
UNIT_COST_ASPHALT_PER_SQ_M = 500.0
UNIT_COST_BRIDGE_PER_SQ_M = 3500.0  # 7 × 500


@dataclass
class InterchangeMetrics:
    """
    On-the-fly economic and spatial metrics for an interchange network.

    Land footprint: convex hull of the union of all segment footprints (m² → hectares).
    Cost: (at-grade area × $500) + (bridge area × $3500).
    """

    network: RoadNetwork

    def _segment_polygons(self, steps: int = 200):
        """Yield Shapely polygons (buffered centrelines) for each segment."""
        for seg in self.network.segments:
            line = seg.as_shapely_line(steps)
            if line.is_empty or line.length < 1e-9:
                continue
            half_w_coord = seg.road_width() / 2.0 / METRES_PER_COORD
            try:
                poly = line.buffer(half_w_coord, cap_style=2, join_style=2)
                if poly.is_empty:
                    continue
                if not poly.is_valid:
                    poly = poly.buffer(0)
                yield poly
            except Exception:
                continue

    def calculate_footprint(self, steps: int = 200) -> float:
        """
        Total land footprint in hectares.
        Uses unary_union of all segment polygons, then convex_hull.area.
        """
        polygons = list(self._segment_polygons(steps))
        if not polygons:
            return 0.0
        union = unary_union(polygons)
        if union.is_empty:
            return 0.0
        hull = union.convex_hull
        area_sq_coord = hull.area
        # Convert coord² to m² then to hectares (1 ha = 10 000 m²)
        area_sq_m = area_sq_coord * (METRES_PER_COORD ** 2)
        return area_sq_m / 10_000.0

    def calculate_cost(self) -> float:
        """
        Estimated construction cost in USD.
        Cost = (at-grade area × $500) + (bridge area × $3500).
        """
        at_grade_area = 0.0
        bridge_area = 0.0
        for seg in self.network.segments:
            area = seg.road_area_sq_meters()
            if seg.is_bridge:
                bridge_area += area
            else:
                at_grade_area += area
        return (
            at_grade_area * UNIT_COST_ASPHALT_PER_SQ_M
            + bridge_area * UNIT_COST_BRIDGE_PER_SQ_M
        )

    @property
    def footprint_hectares(self) -> float:
        """Land use in hectares (cached only at call time)."""
        return self.calculate_footprint()

    @property
    def cost_usd(self) -> float:
        """Total estimated cost in USD."""
        return self.calculate_cost()
