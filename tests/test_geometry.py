"""Smoke tests for the parametric geometry engine."""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.domain.geometry import ControlPoint, RoadSegment, RoadNetwork
from app.application.traffic_engine import TrafficState, bpr_travel_time, stress_to_rgba
from app.infrastructure.generators import CloverleafGenerator, DDIGenerator, RoundaboutGenerator




def test_straight_segment():
    seg = RoadSegment(
        id="straight",
        control_points=[ControlPoint(x=0, y=0), ControlPoint(x=100, y=0)],
        num_lanes=2,
        lane_width_meters=3.5,
    )
    pts = seg.generate_centreline(steps=50)
    assert len(pts) == 50
    assert abs(pts[0][0] - 0.0) < 1e-9
    assert abs(pts[-1][0] - 100.0) < 1e-9
    print("[PASS] straight segment: 50 points from (0,0) to (100,0)")


def test_curved_segment():
    seg = RoadSegment(
        id="curve",
        control_points=[
            ControlPoint(x=0, y=0),
            ControlPoint(x=30, y=20),
            ControlPoint(x=70, y=-10),
            ControlPoint(x=100, y=0),
        ],
        num_lanes=3,
    )
    pts = seg.generate_centreline(steps=200)
    assert len(pts) == 200
    y_vals = [p[1] for p in pts]
    assert max(y_vals) > 5.0, "Spline should curve above y=0"
    assert min(y_vals) < -2.0, "Spline should dip below y=0"
    print(f"[PASS] curved segment: y-range [{min(y_vals):.1f}, {max(y_vals):.1f}]")


def test_road_width():
    seg = RoadSegment(
        id="w",
        control_points=[ControlPoint(x=0, y=0), ControlPoint(x=10, y=0)],
        num_lanes=4,
        lane_width_meters=3.5,
    )
    assert seg.road_width() == 14.0
    print(f"[PASS] road width: {seg.road_width()} m")


def test_shapely_line():
    seg = RoadSegment(
        id="shp",
        control_points=[
            ControlPoint(x=0, y=0),
            ControlPoint(x=50, y=25),
            ControlPoint(x=100, y=0),
        ],
    )
    line = seg.as_shapely_line(steps=100)
    assert line.length > 100, "Arc length should exceed chord"
    print(f"[PASS] Shapely line length: {line.length:.1f} m")


def test_intersection_detection():
    net = RoadNetwork()
    net.add_segment(RoadSegment(
        id="h",
        control_points=[ControlPoint(x=-50, y=0), ControlPoint(x=50, y=0)],
    ))
    net.add_segment(RoadSegment(
        id="v",
        control_points=[ControlPoint(x=0, y=-50), ControlPoint(x=0, y=50)],
    ))
    conflicts = net.find_intersections()
    assert len(conflicts) == 1
    assert abs(conflicts[0][0]) < 1e-6
    assert abs(conflicts[0][1]) < 1e-6
    print(f"[PASS] intersection at ({conflicts[0][0]:.4f}, {conflicts[0][1]:.4f})")


def test_bpr():
    t = bpr_travel_time(free_flow_time=5.0, volume=1800, capacity=1800)
    assert t > 5.0
    print(f"[PASS] BPR: free-flow=5.0 min, congested={t:.2f} min (V/C=1.0)")


def test_stress_colours():
    assert stress_to_rgba(0.0) == (0, 255, 0, 200), "Free flow should be green"
    assert stress_to_rgba(1.5) == (128, 0, 128, 200), "Gridlock should be purple"
    print("[PASS] stress colour mapping")


def test_cloverleaf_generator():
    gen = CloverleafGenerator(radius=50, lane_width=3.5)
    net = gen.generate()
    assert len(net.segments) >= 6, f"Expected >=6 segments, got {len(net.segments)}"
    print(f"[PASS] cloverleaf: {len(net.segments)} segments generated")


def test_ddi_generator():
    gen = DDIGenerator(crossover_angle_deg=30, length=200)
    net = gen.generate()
    assert len(net.segments) >= 6
    print(f"[PASS] DDI: {len(net.segments)} segments generated")


def test_roundabout_generator():
    gen = RoundaboutGenerator(radius=30, num_entries=4)
    net = gen.generate()
    assert len(net.segments) >= 8
    print(f"[PASS] roundabout: {len(net.segments)} segments generated")


def test_traffic_state_from_network():
    gen = CloverleafGenerator()
    net = gen.generate()
    volumes = {seg.id: 1200.0 for seg in net.segments}
    ts = TrafficState.from_network(net, volumes)
    table = ts.summary_table()
    assert len(table) == len(net.segments)
    print(f"[PASS] traffic state: {len(table)} rows in LOS table")
    for row in table:
        print(f"       {row['Segment']:15s}  V/C={row['V/C']:.2f}  LOS={row['LOS']}")


if __name__ == "__main__":
    test_straight_segment()
    test_curved_segment()
    test_road_width()
    test_shapely_line()
    test_intersection_detection()
    test_bpr()
    test_stress_colours()
    test_cloverleaf_generator()
    test_ddi_generator()
    test_roundabout_generator()
    test_traffic_state_from_network()
    print("\nAll 11 tests passed.")
