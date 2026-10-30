"""
Document-trained criterion-value prediction (pure logic, no file or network I/O).

A grey-box "Bayesian residual correction" of the expert values: past interchange projects teach
the model how real cost / land / throughput / safety deviate from the expert pipeline, and it
predicts site-specific values with prediction intervals. With no records it returns the expert
values exactly. Document reading and the trained-model cache live in
``app.infrastructure.corpus``.

Usage
-----
>>> record, warnings = validate_record({"type": "Turbine", "cost": 52.0, "aadt": 60000})
>>> model = ResidualModel.fit([record])
>>> model.predict("Turbine", {"aadt": 60000, "num_lanes": 3})["construction_cost_mln"]
{'expert': 45.0, 'predicted': ..., 'low': ..., 'high': ...}
>>> model.corrections("Turbine", params)["construction_cost_mln"].factor   # e^μ
>>> cross_validate([record])                                              # LOO accuracy
"""

from __future__ import annotations

from app.application.prediction.model import (
    FEATURE_NAMES,
    Correction,
    CriterionData,
    NIGPosterior,
    ResidualModel,
    build_training_data,
    cross_validate,
    cross_validate_criterion,
    expert_baseline,
    features,
    fit_nig,
    prior_hyperparameters,
)
from app.application.prediction.records import (
    CONTEXT_OF_TYPE,
    INTERCHANGE_TYPES,
    Conditions,
    ProjectRecord,
    is_synthetic_source,
    parse_number,
    resolve_env_sensitivity,
    resolve_field_name,
    resolve_header,
    resolve_interchange_type,
    resolve_terrain,
    validate_record,
)
from app.application.prediction.text_extraction import (
    extract_records_from_text,
    normalise_fields,
    parse_field_value,
)

__all__ = [
    "CONTEXT_OF_TYPE",
    "FEATURE_NAMES",
    "INTERCHANGE_TYPES",
    "Conditions",
    "Correction",
    "CriterionData",
    "NIGPosterior",
    "ProjectRecord",
    "ResidualModel",
    "build_training_data",
    "cross_validate",
    "cross_validate_criterion",
    "expert_baseline",
    "extract_records_from_text",
    "features",
    "fit_nig",
    "is_synthetic_source",
    "normalise_fields",
    "parse_field_value",
    "parse_number",
    "prior_hyperparameters",
    "resolve_env_sensitivity",
    "resolve_field_name",
    "resolve_header",
    "resolve_interchange_type",
    "resolve_terrain",
    "validate_record",
]
