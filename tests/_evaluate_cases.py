"""Request matrix shared by the snapshot generator and the regression test."""

from itertools import product

CONTEXTS = [
    "System (Highway + Highway)",
    "Service (Highway + Urban)",
    "T-Type (3 Directions)",
]

PARAM_SETS = {
    "default": {},
    "mountain_critical_fast": {
        "terrain": "Mountainous", "env_sensitivity": "Critical", "design_speed": 130,
        "budget": 200.0, "land_limit": 60.0,
    },
    "heavy_demand": {"aadt": 90000, "peak_factor": 12, "terrain": "Rolling"},
    "tight_budget": {"budget": 20.0, "land_limit": 12.0, "env_sensitivity": "Low"},
}

WEIGHT_SETS = {
    "default": {},
    "cost_heavy": {
        "construction_cost_mln": 0.7, "land_area_hectares": 0.1,
        "throughput_vph": 0.1, "safety_index": 0.1,
    },
}


def cases():
    for ctx, (pname, params), (wname, weights) in product(
        CONTEXTS, PARAM_SETS.items(), WEIGHT_SETS.items()
    ):
        yield f"{ctx}|{pname}|{wname}", {"context": ctx, "weights": weights, "params": params}
