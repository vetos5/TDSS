"""
Corpus document readers: one file in, validated ``ProjectRecord`` objects and warnings out.

Supported kinds (by extension, see ``ALLOWED_EXTENSIONS``):

* ``csv``  — header row of field names (canonical names or any EN/UK synonym, optionally with a
  unit in parentheses: ``Land area (m²)``), one record per row; ``,`` ``;`` or tab delimited.
* ``json`` — a list of record objects or ``{"records": [...]}``; ``.jsonl`` holds one object per
  line.
* ``text`` — ``.txt`` / ``.md`` reports with "Field: value" lines (rule-based extraction).
* ``pdf``  — text layer extracted with ``pypdf`` (optional dependency), then as ``text``.

For text and PDF documents an optional LLM extractor is tried only when the rules find nothing.
Every record, whatever its origin, passes through ``validate_record``; a bad row costs a warning,
never the whole document.
"""

from __future__ import annotations

import csv
import importlib.util
import io
import json
from dataclasses import dataclass, field
from pathlib import Path, PurePath
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from app.application.prediction import (
    ProjectRecord,
    extract_records_from_text,
    is_synthetic_source,
    normalise_fields,
    resolve_header,
    validate_record,
)
from app.data.prediction_defaults import ALLOWED_EXTENSIONS

# (document text, document name) → (raw record dicts, warnings)
LlmExtractor = Callable[[str, str], Tuple[List[Dict[str, Any]], List[str]]]

PDF_MISSING_WARNING = "PDF support not installed: pip install -e .[documents]"


@dataclass
class DocumentResult:
    """What one document contributed to the corpus."""

    name: str
    kind: str                      # csv | json | text | pdf
    extractor: str                 # table | rules | llm | none
    records: List[ProjectRecord] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    size_bytes: int = 0

    @property
    def synthetic(self) -> bool:
        return is_synthetic_source(self.name) or any(r.synthetic for r in self.records)

    def report(self) -> Dict[str, Any]:
        """The ``documents[]`` entry of the model status."""
        return {
            "name": self.name,
            "kind": self.kind,
            "synthetic": self.synthetic,
            "records": len(self.records),
            "extractor": self.extractor,
            "warnings": list(self.warnings),
            "size_bytes": self.size_bytes,
        }


def document_kind(name: str) -> Optional[str]:
    """``csv`` / ``json`` / ``text`` / ``pdf`` for an allowed extension, else None."""
    return ALLOWED_EXTENSIONS.get(PurePath(name).suffix.lower())


def pdf_available() -> bool:
    return importlib.util.find_spec("pypdf") is not None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _decode(data: bytes, warnings: List[str]) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        warnings.append("not valid UTF-8 — decoded as Windows-1251")
        return data.decode("cp1251", errors="replace")


def _validate_all(
    raws: Iterable[Tuple[str, Dict[str, Any]]], name: str, warnings: List[str]
) -> List[ProjectRecord]:
    """Normalise + validate each ``(label, raw dict)``; warnings are prefixed with the label."""
    stem = PurePath(name).stem
    records: List[ProjectRecord] = []
    for label, raw in raws:
        prefix = f"{label}: " if label else ""
        fields, field_warnings = normalise_fields(raw)
        record, record_warnings = validate_record(
            fields, source=name, default_name=f"{stem} {label}".strip()
        )
        warnings.extend(prefix + w for w in field_warnings + record_warnings)
        if record is not None:
            records.append(record)
    return records


# ---------------------------------------------------------------------------
# Kinds
# ---------------------------------------------------------------------------


def _read_csv(text: str, name: str, warnings: List[str]) -> List[ProjectRecord]:
    lines = text.splitlines()
    if not lines:
        return []
    header_line = lines[0]
    delimiter = max((",", ";", "\t"), key=header_line.count)
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    header = [h.strip() for h in rows[0]]
    unknown = [h for h in header if h and resolve_header(h)[0] is None]
    if unknown:
        warnings.append("unknown columns ignored: " + ", ".join(unknown))
    if "interchange_type" not in {resolve_header(h)[0] for h in header}:
        warnings.append("no interchange type column")
        return []

    def raws() -> Iterable[Tuple[str, Dict[str, Any]]]:
        for line_no, row in enumerate(rows[1:], start=2):  # spreadsheet row numbers
            if not any(cell.strip() for cell in row):
                continue
            yield f"row {line_no}", dict(zip(header, row, strict=False))

    return _validate_all(raws(), name, warnings)


def _objects(
    items: Iterable[Tuple[str, Any]], warnings: List[str]
) -> List[Tuple[str, Dict[str, Any]]]:
    objects = []
    for label, item in items:
        if isinstance(item, dict):
            objects.append((label, item))
        else:
            warnings.append(f"{label}: not an object — skipped")
    return objects


def _read_json(text: str, name: str, warnings: List[str]) -> List[ProjectRecord]:
    if PurePath(name).suffix.lower() == ".jsonl":
        items: List[Tuple[str, Any]] = []
        for line_no, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                items.append((f"line {line_no}", json.loads(line)))
            except json.JSONDecodeError as exc:
                warnings.append(f"line {line_no}: invalid JSON ({exc.msg}) — skipped")
        return _validate_all(_objects(items, warnings), name, warnings)

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        warnings.append(f"invalid JSON: {exc.msg} (line {exc.lineno})")
        return []
    if isinstance(payload, dict) and isinstance(payload.get("records"), list):
        payload = payload["records"]
    if not isinstance(payload, list):
        warnings.append('expected a list of records or {"records": [...]}')
        return []
    labelled = [(f"record {i}", item) for i, item in enumerate(payload, start=1)]
    return _validate_all(_objects(labelled, warnings), name, warnings)


def _read_text(text: str, name: str, warnings: List[str]) -> List[ProjectRecord]:
    raw_records, text_warnings = extract_records_from_text(text)
    warnings.extend(text_warnings)
    labelled = [
        (f"record {i}" if len(raw_records) > 1 else "", raw)
        for i, raw in enumerate(raw_records, start=1)
    ]
    return _validate_all(labelled, name, warnings)


def _pdf_text(data: bytes, warnings: List[str]) -> Optional[str]:
    if not pdf_available():
        warnings.append(PDF_MISSING_WARNING)
        return None
    from pypdf import PdfReader  # optional dependency
    from pypdf.errors import PyPdfError

    try:
        reader = PdfReader(io.BytesIO(data))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except (PyPdfError, ValueError, KeyError, OSError) as exc:
        warnings.append(f"could not read PDF: {exc}")
        return None
    if not text.strip():
        warnings.append("PDF has no text layer (scanned image?)")
        return None
    return text


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def read_document_bytes(
    name: str, data: bytes, *, llm_extract: Optional[LlmExtractor] = None
) -> DocumentResult:
    """Read one document given its file name (for the kind) and its content."""
    kind = document_kind(name)
    result = DocumentResult(name=name, kind=kind or "text", extractor="none", size_bytes=len(data))
    warnings = result.warnings
    if kind is None:
        warnings.append(f"unsupported file type {PurePath(name).suffix!r}")
        return result

    if kind in ("csv", "json"):
        text = _decode(data, warnings)
        reader = _read_csv if kind == "csv" else _read_json
        try:
            result.records = reader(text, name, warnings)
        except (csv.Error, RecursionError) as exc:  # malformed CSV, absurdly nested JSON
            warnings.append(f"could not parse {kind.upper()}: {exc}")
        extractor = "table"
    else:
        text = _decode(data, warnings) if kind == "text" else _pdf_text(data, warnings)
        extractor = "rules"
        if text is not None:
            result.records = _read_text(text, name, warnings)
            if not result.records and llm_extract is not None:
                llm_raws, llm_warnings = llm_extract(text, name)
                warnings.extend(f"LLM: {w}" for w in llm_warnings)
                labelled = [(f"LLM record {i}", raw) for i, raw in enumerate(llm_raws, start=1)]
                result.records = _validate_all(labelled, name, warnings)
                extractor = "llm"

    if result.records:
        result.extractor = extractor
    else:
        warnings.append("no project records found")
    return result


def read_document(path: Path, *, llm_extract: Optional[LlmExtractor] = None) -> DocumentResult:
    """Read one corpus file from disk."""
    try:
        data = path.read_bytes()
    except OSError as exc:
        kind = document_kind(path.name) or "text"
        return DocumentResult(
            name=path.name, kind=kind, extractor="none", warnings=[f"could not read file: {exc}"]
        )
    return read_document_bytes(path.name, data, llm_extract=llm_extract)
