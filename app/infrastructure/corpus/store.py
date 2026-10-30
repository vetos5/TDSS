"""
Corpus store: the documents directory, the model trained on it, and the model status.

The whole corpus is re-read and the model refitted from scratch on every change — at tens to
hundreds of records ingest + fit take milliseconds, so incremental bookkeeping would only add
ways to drift out of sync with the files. The fitted model is kept in memory; training happens
lazily on first access and under a lock, so concurrent requests never see a half-built model.

The corpus directory is ``$TDSS_CORPUS_DIR`` or ``<repo>/corpus/documents``. Uploaded names must
be plain base names with an allowed extension (no path separators, no ``..``, no hidden files) and
at most ``MAX_UPLOAD_BYTES``; violations raise ``CorpusError`` subclasses that carry the HTTP status
code the API should answer with.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.application.prediction import (
    Correction,
    ProjectRecord,
    ResidualModel,
    build_training_data,
    cross_validate,
    expert_baseline,
)
from app.data.prediction_defaults import ALLOWED_EXTENSIONS, MAX_UPLOAD_BYTES, TARGETS
from app.infrastructure.corpus.llm_extraction import extract_records_with_llm, llm_available
from app.infrastructure.corpus.readers import (
    DocumentResult,
    document_kind,
    pdf_available,
    read_document,
)

CORPUS_DIR_ENV = "TDSS_CORPUS_DIR"
# app/infrastructure/corpus/store.py -> repo root is three levels up.
DEFAULT_CORPUS_DIR = Path(__file__).resolve().parents[3] / "corpus" / "documents"
_MAX_NAME_LENGTH = 200
_IMPLAUSIBLE_RATIO = 10.0
_FORBIDDEN_NAME_CHARS = set('/\\:*?"<>|') | {chr(c) for c in range(32)} | {"\x7f"}


# ---------------------------------------------------------------------------
# Errors (each carries the HTTP status the API maps it to)
# ---------------------------------------------------------------------------


class CorpusError(Exception):
    status_code = 400


class InvalidDocumentName(CorpusError):
    status_code = 400


class UnsupportedDocumentType(CorpusError):
    status_code = 400


class EmptyDocument(CorpusError):
    status_code = 400


class DocumentTooLarge(CorpusError):
    status_code = 413


class DocumentExists(CorpusError):
    status_code = 409


class DocumentNotFound(CorpusError):
    status_code = 404


def sanitize_document_name(name: Any, *, check_extension: bool = True) -> str:
    """Return *name* if it is a safe plain file name, else raise ``InvalidDocumentName`` (or
    ``UnsupportedDocumentType`` for a disallowed extension)."""
    if not isinstance(name, str) or not name.strip():
        raise InvalidDocumentName("document name is empty")
    name = name.strip()
    if (
        ".." in name
        or name.startswith(".")
        or any(ch in _FORBIDDEN_NAME_CHARS for ch in name)
        or len(name) > _MAX_NAME_LENGTH
    ):
        raise InvalidDocumentName(
            f"invalid document name {name!r}: use a plain file name without path separators"
        )
    if check_extension and document_kind(name) is None:
        allowed = " ".join(ALLOWED_EXTENSIONS)
        raise UnsupportedDocumentType(
            f"unsupported file type {Path(name).suffix or '(none)'!r}; allowed: {allowed}"
        )
    return name


def _implausible_values(records: List[ProjectRecord]) -> List[str]:
    """Warnings for observed values more than ``_IMPLAUSIBLE_RATIO``× off the expert baseline —
    almost always a unit mistake (cost in thousands, land in m² without a unit). The record is
    still used; the warning tells the user where to look."""
    warnings = []
    for record in records:
        baseline = expert_baseline(record.interchange_type, record.conditions)
        for criterion, observed in record.targets.items():
            ratio = observed / baseline[criterion]
            if not 1 / _IMPLAUSIBLE_RATIO <= ratio <= _IMPLAUSIBLE_RATIO:
                warnings.append(
                    f"{record.name}: {criterion} {observed:g} is {ratio:.3g}× the expert value "
                    f"{baseline[criterion]:g} — check the units"
                )
    return warnings


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Snapshot:
    """Everything one training run produced; replaced atomically by the next run."""

    model: ResidualModel
    documents: List[DocumentResult]
    records: List[ProjectRecord]
    criteria: Dict[str, Dict[str, Any]]
    trained_at: str
    train_ms: float
    revision: int


class CorpusStore:
    """Documents directory + the ``ResidualModel`` trained on it (see module docstring)."""

    def __init__(self, directory: Path | str | None = None) -> None:
        if directory is None:
            directory = os.environ.get(CORPUS_DIR_ENV) or DEFAULT_CORPUS_DIR
        self.directory = Path(directory)
        self._lock = threading.RLock()
        self._snapshot: Optional[_Snapshot] = None
        self._revision = 0

    # -- training --------------------------------------------------------------

    def document_paths(self) -> List[Path]:
        """Corpus files with an allowed extension, sorted by name (hidden files skipped)."""
        if not self.directory.is_dir():
            return []
        return sorted(
            p for p in self.directory.iterdir()
            if p.is_file() and not p.name.startswith(".") and document_kind(p.name)
        )

    def retrain(self) -> Dict[str, Any]:
        """Re-read every document, refit the model, and return the new status."""
        with self._lock:
            start = time.perf_counter()
            llm = extract_records_with_llm if llm_available() else None
            documents = [read_document(p, llm_extract=llm) for p in self.document_paths()]
            for document in documents:
                document.warnings.extend(_implausible_values(document.records))
            records = [r for d in documents for r in d.records]
            data = build_training_data(records)
            model = ResidualModel.from_training_data(
                data,
                n_records=len(records),
                n_synthetic=sum(1 for r in records if r.synthetic),
            )
            train_ms = (time.perf_counter() - start) * 1000.0

            metrics = cross_validate(data, interval_level=model.interval_level)
            criteria = {
                c: {
                    "n_obs": model.n_obs(c),
                    "noise_sd": model.noise_sd(c),
                    "loo_mape_expert": metrics[c]["loo_mape_expert"],
                    "loo_mape_model": metrics[c]["loo_mape_model"],
                    "coverage90": metrics[c]["coverage90"],
                }
                for c in TARGETS
            }
            # Strictly increasing per fit, and wall-clock based so it keeps growing across server
            # restarts: clients use it to tell one fit from the next (trained_at is per second).
            self._revision = max(self._revision + 1, time.time_ns() // 1000)
            self._snapshot = _Snapshot(
                model=model,
                documents=documents,
                records=records,
                criteria=criteria,
                trained_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                train_ms=train_ms,
                revision=self._revision,
            )
            return self._status(self._snapshot)

    def _current(self) -> _Snapshot:
        with self._lock:
            if self._snapshot is None:
                self.retrain()
            assert self._snapshot is not None
            return self._snapshot

    # -- queries ---------------------------------------------------------------

    @property
    def model(self) -> ResidualModel:
        """The fitted model (trained lazily on first access)."""
        return self._current().model

    @property
    def records(self) -> List[ProjectRecord]:
        return list(self._current().records)

    def predict(self, interchange_type: str, conditions: Any = None) -> Dict[str, Dict[str, float]]:
        """``ResidualModel.predict`` on the current model."""
        return self.model.predict(interchange_type, conditions)

    def corrections(self, interchange_type: str, conditions: Any = None) -> Dict[str, Correction]:
        """``ResidualModel.corrections`` (e^μ and interval ratios) on the current model."""
        return self.model.corrections(interchange_type, conditions)

    def status(self) -> Dict[str, Any]:
        """Plain dict matching the ``ModelStatus`` API contract."""
        return self._status(self._current())

    @staticmethod
    def _status(snapshot: _Snapshot) -> Dict[str, Any]:
        model = snapshot.model
        return {
            "trained_at": snapshot.trained_at,
            "train_ms": snapshot.train_ms,
            "revision": snapshot.revision,
            "n_records": model.n_records,
            "n_synthetic": model.n_synthetic,
            "documents": [d.report() for d in snapshot.documents],
            "criteria": {c: dict(m) for c, m in snapshot.criteria.items()},
            "coefficients": model.coefficients(),
            "interval_level": model.interval_level,
            "llm_available": llm_available(),
            "pdf_available": pdf_available(),
        }

    # -- documents -------------------------------------------------------------

    def save_document(self, name: str, data: bytes, overwrite: bool = False) -> Dict[str, Any]:
        """Validate and store an uploaded document, retrain, and return the new status.

        Raises ``InvalidDocumentName`` / ``UnsupportedDocumentType`` / ``EmptyDocument`` (400),
        ``DocumentTooLarge`` (413) or ``DocumentExists`` (409, unless *overwrite*).
        """
        name = sanitize_document_name(name)
        if not data:
            raise EmptyDocument("the uploaded file is empty")
        if len(data) > MAX_UPLOAD_BYTES:
            limit_mb = MAX_UPLOAD_BYTES // (1024 * 1024)
            raise DocumentTooLarge(f"the file is {len(data):,} bytes; the limit is {limit_mb} MB")
        with self._lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self.directory / name
            if path.resolve().parent != self.directory.resolve():
                raise InvalidDocumentName(f"invalid document name {name!r}")
            if path.exists() and not overwrite:
                raise DocumentExists(f"document {name!r} already exists")
            partial = self.directory / f".{name}.partial"
            partial.write_bytes(data)
            os.replace(partial, path)  # atomic: a retrain never reads half a file
            return self.retrain()

    def delete_document(self, name: str) -> Dict[str, Any]:
        """Delete a document, retrain, and return the new status.

        Raises ``InvalidDocumentName`` (400) for unsafe names, ``DocumentNotFound`` (404).
        """
        name = sanitize_document_name(name, check_extension=False)
        with self._lock:
            path = self.directory / name
            if document_kind(name) is None or not path.is_file():
                raise DocumentNotFound(f"document {name!r} not found")
            path.unlink()
            return self.retrain()


# ---------------------------------------------------------------------------
# Process-wide singleton
# ---------------------------------------------------------------------------

_store: Optional[CorpusStore] = None
_store_lock = threading.Lock()


def get_store() -> CorpusStore:
    """The process-wide store (created on first use from ``$TDSS_CORPUS_DIR`` / the default)."""
    global _store
    with _store_lock:
        if _store is None:
            _store = CorpusStore()
        return _store


def reset_store(directory: Path | str | None = None) -> CorpusStore:
    """Replace the singleton with a fresh, untrained store on *directory* (None → env/default).

    Tests point the API at a temporary corpus with ``reset_store(tmp_path)`` and restore the
    default afterwards with ``reset_store()``.
    """
    global _store
    with _store_lock:
        _store = CorpusStore(directory)
        return _store
