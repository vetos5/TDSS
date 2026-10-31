"""
Rule-based extraction of project records from plain text (pure, no I/O).

Project reports are rarely tables, but the facts the model needs are almost always written as
"Field: value" lines — in English or Ukrainian, with the units and number formats of the author.
This module recognises such lines and converts the values to the canonical units:

* construction cost → millions of USD (``$48.5M``, ``USD 48.5 million``, ``48,5 млн дол.``,
  ``$48,500,000``). Another currency is *not* converted — exchange rates and price years would add
  more error than the field is worth — the field is skipped with a warning instead;
* land area → hectares (``ha``/``га``; ``m²``/``м2`` divided by 10 000);
* throughput → veh/h, AADT → veh/day (``k``/``тис.`` multiply by 1000), speed → km/h.

A document holds one record, or several separated by a line of three or more dashes. Lines that do
not start with a known field name are ignored, so free prose around the facts is harmless. Values
are only converted here; ``records.validate_record`` decides whether a record is usable.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional, Tuple

from app.application.prediction.records import (
    normalise_key,
    parse_bool,
    parse_number,
    resolve_field_name,
    resolve_header,
)
from app.data.prediction_defaults import FIELD_SYNONYMS, MAX_FIELD_LINE_CHARS, YEAR_RANGE

# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------


def _word(alternatives: str) -> re.Pattern[str]:
    """Case-insensitive pattern for *alternatives* not glued to other letters (digits are fine,
    so ``48.5M`` matches ``m``)."""
    return re.compile(rf"(?<![^\W\d_])(?:{alternatives})(?![^\W\d_])", re.IGNORECASE)


_FOREIGN_CURRENCIES: Tuple[Tuple[str, re.Pattern[str]], ...] = (
    ("UAH", re.compile(r"₴|(?<![^\W\d_])(?:грн|гривн\w*|гривень|uah)(?![^\W\d_])", re.I)),
    ("EUR", re.compile(r"€|(?<![^\W\d_])(?:eur|euro|euros|євро)(?![^\W\d_])", re.I)),
    ("GBP", re.compile(r"£|(?<![^\W\d_])(?:gbp)(?![^\W\d_])", re.I)),
    ("PLN", re.compile(r"(?<![^\W\d_])(?:pln|zł|злот\w*)(?![^\W\d_])", re.I)),
    ("CHF", _word("chf")),
)
_BILLION = _word(r"bn|billion|billions|млрд|мільярд\w*")
_MILLION = _word(r"m|mm|mn|mln|mio|million|millions|млн|мільйон\w*")
_THOUSAND = _word(r"k|thousand|thousands|тис|тисяч\w*")
_SQUARE_METRES = re.compile(
    r"(?<![^\W\d_])(?:m²|m2|м²|м2|sq\.?\s*m|square\s+met\w*|кв\.?\s*м)(?![^\W\d_])", re.I
)
_YEAR = re.compile(r"(?<!\d)(\d{4})(?!\d)")

# A bare cost at or above this value is read as plain dollars (10 000 M USD would be absurd).
_RAW_DOLLARS_THRESHOLD = 10_000.0

_TEXT_FIELDS = frozenset({"interchange_type", "terrain", "env_sensitivity", "name", "country"})


def _parse_cost(text: str, units: str) -> Tuple[Optional[float], Optional[str]]:
    for code, pattern in _FOREIGN_CURRENCIES:
        if pattern.search(units):
            return None, (
                f"construction_cost_mln {text!r}: currency {code} not supported "
                "(USD only) — field skipped"
            )
    number = parse_number(text)
    if number is None:
        return None, f"construction_cost_mln {text!r} is not a number — field skipped"
    if _BILLION.search(units):
        return number * 1000.0, None
    if _MILLION.search(units):
        return number, None
    if _THOUSAND.search(units):
        return number / 1000.0, None
    if number >= _RAW_DOLLARS_THRESHOLD:
        return number / 1e6, None
    return number, None


def parse_field_value(name: str, text: Any, unit_hint: str = "") -> Tuple[Any, Optional[str]]:
    """Convert the raw text of canonical field *name* to its canonical unit.

    *unit_hint* is extra text consulted for units/currency only, never for the number — e.g. the
    ``(M USD)`` qualifier of ``Construction cost (M USD): 48.5``. Returns ``(value, warning)``;
    ``value`` is None (and ``warning`` set) when nothing usable was found. Non-string inputs are
    returned unchanged.
    """
    if not isinstance(text, str):
        return text, None
    text = text.strip()
    if not text:
        return None, None
    units = f"{unit_hint} {text}"

    if name in _TEXT_FIELDS:
        return text.strip(" .;,").strip("*_`").strip(), None
    if name == "synthetic":
        flag = parse_bool(text)
        return (flag, None) if flag is not None else (None, f"synthetic {text!r} not recognised")
    if name == "year":
        match = _YEAR.search(text)
        if match and YEAR_RANGE[0] <= int(match.group(1)) <= YEAR_RANGE[1]:
            return int(match.group(1)), None
        return None, f"year {text!r} not recognised — ignored"
    if name == "construction_cost_mln":
        return _parse_cost(text, units)

    number = parse_number(text)
    if number is None:
        return None, f"{name} {text!r} is not a number — field skipped"
    if name == "land_area_hectares" and _SQUARE_METRES.search(units):
        return number / 10_000.0, None
    if name in ("aadt", "throughput_vph") and _THOUSAND.search(units):
        return number * 1000.0, None
    return number, None


def normalise_fields(raw: Mapping[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """Map synonym keys to canonical names and convert string values with units.

    Unknown keys are dropped silently. Used for CSV rows and JSON objects before
    ``validate_record``; the first usable value of a field wins.
    """
    fields: Dict[str, Any] = {}
    warnings: List[str] = []
    for key, value in raw.items():
        name, unit_hint = resolve_header(key)
        if name is None or name in fields:
            continue
        parsed, warning = parse_field_value(name, value, unit_hint)
        if warning:
            warnings.append(warning)
        if parsed is not None and not (isinstance(parsed, str) and not parsed):
            fields[name] = parsed
    return fields, warnings


# ---------------------------------------------------------------------------
# "Field: value" lines
# ---------------------------------------------------------------------------


def _synonym_pattern(synonym: str) -> str:
    parts = [re.escape(word).replace("'", "['’ʼ`]") for word in normalise_key(synonym).split()]
    return r"\s+".join(parts)


_SYNONYMS_BY_LENGTH = sorted(
    {(normalise_key(s), field) for field, synonyms in FIELD_SYNONYMS.items() for s in synonyms},
    key=lambda item: -len(item[0]),
)
# key, optional "(unit)" qualifier, separator (: = — – or a dash followed by a space), value.
# The whitespace after the qualifier sits inside its optional group: two adjacent "\s*" around an
# optional group backtrack quadratically on a long run of spaces.
_LINE_RE = re.compile(
    r"^(?P<key>" + "|".join(_synonym_pattern(s) for s, _ in _SYNONYMS_BY_LENGTH) + r")"
    r"\s*(?:(?P<qualifier>\([^)]*\))\s*)?(?:[:=—–]|-(?=\s))\s*(?P<value>.*)$",
    re.IGNORECASE,
)
_BULLET = re.compile(r"^\s*(?:[-*•·+>#]+|\d+[.)])\s+")
_SEPARATOR_LINE = re.compile(r"^\s*-{3,}\s*$")


def _clean_line(line: str) -> str:
    line = line.replace("**", "").replace("__", "").replace("`", "").strip()
    if line.startswith("|"):  # markdown table row: "| Field | value |"
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) >= 2 and cells[0] and cells[1]:
            return f"{cells[0]}: {cells[1]}"
        return ""
    return _BULLET.sub("", line, count=1).strip()


def match_field_line(line: str) -> Optional[Tuple[str, str, str]]:
    """``(canonical field, value text, qualifier)`` if *line* is a "Field: value" line.

    The qualifier is the optional parenthesised text after the key — usually a unit, as in
    ``Construction cost (M USD): 48.5`` — or ``""``. Lines longer than ``MAX_FIELD_LINE_CHARS``
    are prose and never match.
    """
    if len(line) > MAX_FIELD_LINE_CHARS:
        return None
    match = _LINE_RE.match(_clean_line(line))
    if match is None:
        return None
    name = resolve_field_name(match.group("key"))
    if name is None:
        return None
    return name, match.group("value").strip(), match.group("qualifier") or ""


def split_blocks(text: str) -> List[List[str]]:
    """Split *text* into record blocks at lines of three or more dashes."""
    blocks: List[List[str]] = [[]]
    for line in text.splitlines():
        if _SEPARATOR_LINE.match(line):
            blocks.append([])
        else:
            blocks[-1].append(line)
    return [b for b in blocks if any(line.strip() for line in b)]


def too_many_records_warning(limit: int) -> str:
    """The warning of a document cut at *limit* records (rows, objects or record blocks)."""
    return f"more than {limit:,} records — only the first {limit:,} were read"


def extract_records_from_text(
    text: str, max_records: Optional[int] = None
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Extract record dicts (canonical keys, canonical units) from a text document.

    Returns ``(records, warnings)``. Blocks without any recognised field (prose, front matter) are
    skipped silently; a block with fields but no interchange type yields a warning, not a record.
    With *max_records*, reading stops after that many blocks with fields, with a warning.
    """
    blocks = split_blocks(text)
    records: List[Dict[str, Any]] = []
    warnings: List[str] = []
    with_fields = 0
    for index, lines in enumerate(blocks, start=1):
        prefix = f"block {index}: " if len(blocks) > 1 else ""
        fields: Dict[str, Any] = {}
        for line in lines:
            matched = match_field_line(line)
            if matched is None:
                continue
            name, value_text, qualifier = matched
            if name in fields:
                continue  # the first usable value of a field wins
            value, warning = parse_field_value(name, value_text, qualifier)
            if warning:
                warnings.append(prefix + warning)
            if value is not None and value != "":
                fields[name] = value
        if not fields:
            continue
        if max_records is not None and with_fields >= max_records:
            warnings.append(too_many_records_warning(max_records))
            break
        with_fields += 1
        if "interchange_type" not in fields:
            warnings.append(prefix + "no interchange type found — block skipped")
            continue
        records.append(fields)
    return records, warnings
