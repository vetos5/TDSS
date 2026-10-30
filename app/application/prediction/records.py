"""
Project records — one past interchange project as the prediction model sees it.

Every document reader (CSV, JSON, rule-based text, optional LLM) produces plain dicts; this module
is the single gate that turns such a dict into a validated ``ProjectRecord``. Keeping validation in
one place means a record extracted by an LLM obeys exactly the same rules as a CSV row.

Rules (see ``app.data.prediction_defaults`` for the constants):

* ``interchange_type`` is required and must resolve to one of the eight alternatives of
  ``INTERCHANGE_DATA`` (EN/UK synonyms, case-insensitive). The context is derived from the type.
* At least one target (cost, land, throughput, safety) is required; every target must be > 0 and
  the safety index must lie in [1, 10]. An invalid target is dropped with a warning.
* A missing or invalid site condition is replaced by its reference value, with a warning naming
  the field — the record still informs the per-type correction.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Any, Dict, List, Mapping, Optional, Tuple

from app.data.interchange_data import INTERCHANGE_DATA
from app.data.prediction_defaults import (
    DESIGN_SPEED_RANGE,
    ENV_LEVELS,
    ENV_SYNONYMS,
    FALSE_WORDS,
    FIELD_SYNONYMS,
    INTERCHANGE_TYPE_SYNONYMS,
    NUM_LANES_RANGE,
    REFERENCE_CONDITIONS,
    SAFETY_BOUNDS,
    SYNTHETIC_PREFIX,
    TARGETS,
    TERRAIN_LEVELS,
    TERRAIN_SYNONYMS,
    TRUE_WORDS,
    YEAR_RANGE,
)

# Alternative name → context key, in INTERCHANGE_DATA order (also the model's feature order).
CONTEXT_OF_TYPE: Dict[str, str] = {
    name: context for context, alternatives in INTERCHANGE_DATA.items() for name in alternatives
}
INTERCHANGE_TYPES: Tuple[str, ...] = tuple(CONTEXT_OF_TYPE)

CONDITION_FIELDS: Tuple[str, ...] = (
    "aadt", "num_lanes", "design_speed", "terrain", "env_sensitivity",
)
RECORD_FIELDS: Tuple[str, ...] = (
    ("interchange_type",) + CONDITION_FIELDS + TARGETS + ("name", "year", "country", "synthetic")
)


# ---------------------------------------------------------------------------
# Text normalisation and synonym resolution
# ---------------------------------------------------------------------------

_APOSTROPHES = str.maketrans({"’": "'", "ʼ": "'", "`": "'", "‘": "'", "´": "'"})


def normalise_key(text: str) -> str:
    """Lower-case, unify apostrophes, drop markdown emphasis, collapse whitespace."""
    text = str(text).translate(_APOSTROPHES).replace("**", "").replace("__", "")
    return " ".join(text.strip().strip("*_").lower().split())


_FIELD_LOOKUP: Dict[str, str] = {
    normalise_key(synonym): canonical
    for canonical, synonyms in FIELD_SYNONYMS.items()
    for synonym in synonyms
}
_TYPE_LOOKUP: Dict[str, str] = {
    **{normalise_key(name): name for name in INTERCHANGE_TYPES},
    **{normalise_key(k): v for k, v in INTERCHANGE_TYPE_SYNONYMS.items()},
}
_TERRAIN_LOOKUP: Dict[str, str] = {
    **{level.lower(): level for level in TERRAIN_LEVELS},
    **{normalise_key(k): v for k, v in TERRAIN_SYNONYMS.items()},
}
_ENV_LOOKUP: Dict[str, str] = {
    **{level.lower(): level for level in ENV_LEVELS},
    **{normalise_key(k): v for k, v in ENV_SYNONYMS.items()},
}
# Generic words people append to a type name ("Turbine interchange", "розв'язка типу труба").
_TYPE_FILLER = re.compile(
    r"\b(interchange|junction|type|розв'язка|розв'язок|розв'язки|типу|тип|вузол)\b"
)


def resolve_field_name(key: Any) -> Optional[str]:
    """Canonical field name for a CSV header / JSON key / text key, or None if unknown."""
    return _FIELD_LOOKUP.get(normalise_key(key))


_HEADER_QUALIFIER = re.compile(r"^(?P<key>.*?)\s*\((?P<unit>[^)]*)\)\s*$")


def resolve_header(key: Any) -> Tuple[Optional[str], str]:
    """``(canonical field, unit hint)`` for a CSV header / JSON key; a trailing parenthesised
    unit is accepted, e.g. ``Land area (m²)`` → ``("land_area_hectares", "m²")``."""
    name = resolve_field_name(key)
    if name is not None:
        return name, ""
    match = _HEADER_QUALIFIER.match(str(key))
    if match is None:
        return None, ""
    return resolve_field_name(match.group("key")), match.group("unit")


def _clean_value(value: Any) -> str:
    return normalise_key(value).strip(" .;,:")


def resolve_interchange_type(value: Any) -> Optional[str]:
    """Canonical alternative name for *value* (EN/UK synonyms, case-insensitive) or None."""
    if value is None:
        return None
    key = _clean_value(value)
    if key in _TYPE_LOOKUP:
        return _TYPE_LOOKUP[key]
    stripped = " ".join(_TYPE_FILLER.sub(" ", key).split())
    return _TYPE_LOOKUP.get(stripped)


def resolve_terrain(value: Any) -> Optional[str]:
    return None if value is None else _TERRAIN_LOOKUP.get(_clean_value(value))


def resolve_env_sensitivity(value: Any) -> Optional[str]:
    return None if value is None else _ENV_LOOKUP.get(_clean_value(value))


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------

# Integer part with thousands groups (comma, space, NBSP, thin / narrow space, apostrophe) that are
# followed by exactly three digits, or a plain digit run; then an optional decimal comma / point.
_NUMBER_RE = re.compile(
    r"(?<![\d.,])([-+−]?)"
    r"(\d{1,3}(?:[,    '’]\d{3}(?!\d))+|\d+)"
    r"(?:[.,](\d+))?"
)


def parse_number(value: Any) -> Optional[float]:
    """First number in *value* (``"52,000"`` → 52000, ``"48,5"`` → 48.5), or None.

    Numeric inputs are returned as float; booleans and NaN are rejected.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    match = _NUMBER_RE.search(str(value))
    if match is None:
        return None
    sign, integer, decimals = match.groups()
    integer = re.sub(r"\D", "", integer)
    number = float(f"{integer}.{decimals}" if decimals else integer)
    return -number if sign in ("-", "−") else number


def parse_bool(value: Any) -> Optional[bool]:
    """``True``/``False`` for the usual EN/UK spellings, None when not recognisable."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if value is None:
        return None
    key = _clean_value(value)
    if key in TRUE_WORDS:
        return True
    if key in FALSE_WORDS:
        return False
    return None


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return isinstance(value, str) and not value.strip()


def is_synthetic_source(source: str) -> bool:
    """True when the document name marks it as synthetic demo data (``synthetic_*``)."""
    return PurePath(source).name.lower().startswith(SYNTHETIC_PREFIX)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Conditions:
    """Site conditions of a project or of a prediction query.

    Unknown terrain / env. labels are kept verbatim: the expert rules treat them as neutral and
    the model's features treat them as the reference level, so both stay consistent.
    """

    aadt: float = float(REFERENCE_CONDITIONS["aadt"])
    num_lanes: int = int(REFERENCE_CONDITIONS["num_lanes"])
    design_speed: float = float(REFERENCE_CONDITIONS["design_speed"])
    terrain: str = str(REFERENCE_CONDITIONS["terrain"])
    env_sensitivity: str = str(REFERENCE_CONDITIONS["env_sensitivity"])

    @classmethod
    def of(cls, source: Any = None) -> "Conditions":
        """Build from a ``Conditions``, a mapping, or any object with the attributes
        (e.g. ``backend.schemas.ProjectParams``); missing values take the reference value."""
        if isinstance(source, Conditions):
            return source
        if source is None:
            return cls()

        def get(name: str) -> Any:
            if isinstance(source, Mapping):
                value = source.get(name)
            else:
                value = getattr(source, name, None)
            return REFERENCE_CONDITIONS[name] if _is_missing(value) else value

        terrain, env = str(get("terrain")), str(get("env_sensitivity"))
        return cls(
            aadt=float(get("aadt")),
            num_lanes=int(get("num_lanes")),
            design_speed=float(get("design_speed")),
            terrain=resolve_terrain(terrain) or terrain,
            env_sensitivity=resolve_env_sensitivity(env) or env,
        )


@dataclass(frozen=True)
class ProjectRecord:
    """One observed interchange project: type, site conditions, observed criterion values."""

    interchange_type: str
    aadt: int
    num_lanes: int
    design_speed: float
    terrain: str
    env_sensitivity: str
    targets: Mapping[str, float] = field(default_factory=dict)
    name: str = ""
    year: Optional[int] = None
    country: Optional[str] = None
    source: str = ""
    synthetic: bool = False
    imputed: Tuple[str, ...] = ()

    @property
    def context(self) -> str:
        return CONTEXT_OF_TYPE[self.interchange_type]

    @property
    def conditions(self) -> Conditions:
        return Conditions(
            aadt=float(self.aadt),
            num_lanes=self.num_lanes,
            design_speed=float(self.design_speed),
            terrain=self.terrain,
            env_sensitivity=self.env_sensitivity,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Flat dict with the canonical field names (JSON-serialisable)."""
        return {
            "interchange_type": self.interchange_type,
            "context": self.context,
            "aadt": self.aadt,
            "num_lanes": self.num_lanes,
            "design_speed": self.design_speed,
            "terrain": self.terrain,
            "env_sensitivity": self.env_sensitivity,
            **{t: self.targets.get(t) for t in TARGETS},
            "name": self.name,
            "year": self.year,
            "country": self.country,
            "source": self.source,
            "synthetic": self.synthetic,
            "imputed": list(self.imputed),
        }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _canonical_fields(raw: Mapping[str, Any]) -> Dict[str, Any]:
    """Map synonym keys to canonical names; the first non-missing value of a field wins."""
    fields: Dict[str, Any] = {}
    for key, value in raw.items():
        name, _unit = resolve_header(key)
        if name is not None and name not in fields and not _is_missing(value):
            fields[name] = value
    return fields


def _fmt(value: Any) -> str:
    return f"{value:g}" if isinstance(value, float) else repr(value)


def _condition(
    name: str, value: Any, warnings: List[str], imputed: List[str]
) -> Any:
    reference = REFERENCE_CONDITIONS[name]

    def impute(reason: str) -> Any:
        warnings.append(f"{name} {reason} — reference value {reference} imputed")
        imputed.append(name)
        return reference

    if _is_missing(value):
        return impute("missing")

    if name in ("terrain", "env_sensitivity"):
        resolver = resolve_terrain if name == "terrain" else resolve_env_sensitivity
        resolved = resolver(value)
        return resolved if resolved is not None else impute(f"{value!r} not recognised")

    number = parse_number(value)
    if number is None:
        return impute(f"{value!r} is not a number")
    if name == "aadt":
        return round(number) if number >= 1 else impute(f"{_fmt(number)} must be > 0")
    if name == "num_lanes":
        lo, hi = NUM_LANES_RANGE
        if abs(number - round(number)) > 1e-9:
            return impute(f"{_fmt(number)} is not a whole number")
        if not lo <= number <= hi:
            return impute(f"{_fmt(number)} outside {lo}–{hi}")
        return int(round(number))
    # design_speed
    lo, hi = DESIGN_SPEED_RANGE
    if not lo <= number <= hi:
        return impute(f"{_fmt(number)} outside {lo:g}–{hi:g} km/h")
    return number


def _target(name: str, value: Any, warnings: List[str]) -> Optional[float]:
    number = parse_number(value)
    if number is None:
        warnings.append(f"{name} {value!r} is not a number — ignored")
        return None
    if number <= 0:
        warnings.append(f"{name} {_fmt(number)} must be > 0 — ignored")
        return None
    if name == "safety_index":
        lo, hi = SAFETY_BOUNDS
        if not lo <= number <= hi:
            warnings.append(f"{name} {_fmt(number)} outside {lo:g}–{hi:g} — ignored")
            return None
    return number


def validate_record(
    raw: Mapping[str, Any],
    *,
    source: str = "",
    default_name: str = "",
) -> Tuple[Optional[ProjectRecord], List[str]]:
    """Validate and normalise one record dict.

    Keys may be canonical names or any synonym from ``FIELD_SYNONYMS``; values may be numbers or
    plain numeric strings (unit-aware parsing of strings like ``"$48.5M"`` is done beforehand by
    ``text_extraction.normalise_fields``). Returns ``(record, warnings)``; ``record`` is None when
    the type is missing/unknown or no valid target remains.
    """
    fields = _canonical_fields(raw)
    warnings: List[str] = []

    type_value = fields.get("interchange_type")
    if type_value is None:
        return None, ["no interchange type — record skipped"]
    interchange_type = resolve_interchange_type(type_value)
    if interchange_type is None:
        return None, [f"unknown interchange type {str(type_value)!r} — record skipped"]

    targets: Dict[str, float] = {}
    for name in TARGETS:
        if name in fields:
            value = _target(name, fields[name], warnings)
            if value is not None:
                targets[name] = value
    if not targets:
        warnings.append("no valid target values (cost, land, throughput, safety) — record skipped")
        return None, warnings

    imputed: List[str] = []
    conditions = {
        name: _condition(name, fields.get(name), warnings, imputed) for name in CONDITION_FIELDS
    }

    year = None
    if "year" in fields:
        number = parse_number(fields["year"])
        lo, hi = YEAR_RANGE
        if number is not None and lo <= number <= hi and number == int(number):
            year = int(number)
        else:
            warnings.append(f"year {fields['year']!r} not recognised — ignored")

    country = str(fields["country"]).strip() if "country" in fields else None
    name = str(fields.get("name", "")).strip() or default_name or interchange_type
    synthetic = is_synthetic_source(source) or parse_bool(fields.get("synthetic")) is True

    record = ProjectRecord(
        interchange_type=interchange_type,
        aadt=int(conditions["aadt"]),
        num_lanes=int(conditions["num_lanes"]),
        design_speed=float(conditions["design_speed"]),
        terrain=str(conditions["terrain"]),
        env_sensitivity=str(conditions["env_sensitivity"]),
        targets=targets,
        name=name,
        year=year,
        country=country or None,
        source=source,
        synthetic=synthetic,
        imputed=tuple(imputed),
    )
    return record, warnings
