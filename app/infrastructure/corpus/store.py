"""
Corpus store: the documents directory, the model trained on it, and the model status.

The whole corpus is re-read and the model refitted from scratch on every change — at tens to
hundreds of records ingest + fit take milliseconds, so incremental bookkeeping would only add
ways to drift out of sync with the files. Only the parsing is cached: a document whose file is
unchanged (same size, times and inode) is not parsed again, which matters for PDFs and the LLM.

The fitted model and everything derived from it form one immutable snapshot. Writers (retrain,
upload, delete, and the lazy first fit) are serialised by a lock and publish a new snapshot with
a single assignment; readers take the current snapshot without the lock, so a slow retrain never
blocks the public endpoints. A failed fit keeps the previous snapshot (on the very first fit, an
expert-only model), and a failed upload is rolled back.

The corpus directory is ``$TDSS_CORPUS_DIR`` or ``<repo>/corpus/documents``. Uploaded names must
be plain base names with an allowed extension (no path separators, no ``..``, no hidden files, no
control or format characters, at most 200 UTF-8 bytes) and at most ``MAX_UPLOAD_BYTES``, and the
corpus must stay within ``MAX_DOCUMENTS`` / ``MAX_CORPUS_BYTES``; violations raise ``CorpusError``
subclasses that carry the HTTP status code the API should answer with. Files that reach the
directory another way are read only within the same caps.
"""

from __future__ import annotations

import contextlib
import os
import threading
import time
import unicodedata
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.application.prediction import (
    Correction,
    ProjectRecord,
    ResidualModel,
    build_training_data,
    cross_validate,
    expert_baseline,
)
from app.data.prediction_defaults import (
    ALLOWED_EXTENSIONS,
    MAX_CORPUS_BYTES,
    MAX_DOCUMENTS,
    MAX_RECORDS_PER_DOCUMENT,
    MAX_UPLOAD_BYTES,
    OUTLIER_WEIGHT,
    TARGETS,
)
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
_MAX_NAME_BYTES = 200
_IMPLAUSIBLE_RATIO = 10.0
_FORBIDDEN_NAME_CHARS = set('/\\:*?"<>|') | {chr(c) for c in range(32)} | {"\x7f"}
# Control, format (bidi overrides such as U+202E that disguise an extension) and surrogates.
_FORBIDDEN_NAME_CATEGORIES = frozenset({"Cc", "Cf", "Cs"})
_MB = 1024 * 1024


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


class CorpusFull(CorpusError):
    """The upload would take the corpus past ``MAX_DOCUMENTS`` or ``MAX_CORPUS_BYTES``."""

    status_code = 413


class TooManyRecords(CorpusError):
    """The uploaded document holds more than ``MAX_RECORDS_PER_DOCUMENT`` records."""

    status_code = 413


class TrainingFailed(CorpusError):
    """The model could not be fitted on the corpus; the previous model stays in place."""

    status_code = 422


def sanitize_document_name(name: Any, *, check_extension: bool = True) -> str:
    """Return *name* if it is a safe plain file name, else raise ``InvalidDocumentName`` (or
    ``UnsupportedDocumentType`` for a disallowed extension)."""
    if not isinstance(name, str) or not name.strip():
        raise InvalidDocumentName("document name is empty")
    name = name.strip()
    if (
        ".." in name
        or name.startswith(".")
        or len(name) > _MAX_NAME_BYTES  # cheap pre-check; a character is at least one byte
        or any(
            ch in _FORBIDDEN_NAME_CHARS or unicodedata.category(ch) in _FORBIDDEN_NAME_CATEGORIES
            for ch in name
        )
        or len(name.encode("utf-8")) > _MAX_NAME_BYTES
    ):
        raise InvalidDocumentName(
            f"invalid document name {name[:80]!r}: use a plain file name without path separators"
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


def _downweighted(
    records: List[ProjectRecord], data: Dict[str, Any], model: ResidualModel
) -> Dict[int, List[str]]:
    """Per record index, warnings for observations the Student-t fit gave a weight below
    ``OUTLIER_WEIGHT`` — far from the pattern of the other projects, so they barely count."""
    warnings: Dict[int, List[str]] = {}
    for criterion in TARGETS:
        weights = model.posteriors[criterion].weights
        if weights is None:
            continue
        rows = data[criterion]
        for i, weight, observed in zip(rows.record_index, weights, rows.observed, strict=True):
            if weight < OUTLIER_WEIGHT:
                warnings.setdefault(int(i), []).append(
                    f"{records[i].name}: {criterion} {observed:g} is far from the other projects "
                    f"and was downweighted to {weight:.2f} in training"
                )
    return warnings


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Snapshot:
    """Everything one training run produced; replaced atomically by the next run and never
    mutated once published (readers use it without the lock)."""

    model: ResidualModel
    documents: Tuple[DocumentResult, ...]
    records: Tuple[ProjectRecord, ...]
    criteria: Dict[str, Dict[str, Any]]
    trained_at: str
    train_ms: float
    revision: int


# (size, mtime, ctime, inode, LLM enabled) of a file: a document with the same key is not parsed
# again. ctime changes on every write and cannot be set back, unlike mtime.
_CacheKey = Tuple[int, int, int, int, bool]


def _copy(document: DocumentResult) -> DocumentResult:
    """A copy whose record and warning lists can be extended without touching the original."""
    return replace(document, records=list(document.records), warnings=list(document.warnings))


def _unread(path: Path, size: int, reason: str) -> DocumentResult:
    kind = document_kind(path.name) or "text"
    return DocumentResult(
        name=path.name, kind=kind, extractor="none", warnings=[reason], size_bytes=size
    )


class CorpusStore:
    """Documents directory + the ``ResidualModel`` trained on it (see module docstring)."""

    def __init__(self, directory: Path | str | None = None) -> None:
        if directory is None:
            directory = os.environ.get(CORPUS_DIR_ENV) or DEFAULT_CORPUS_DIR
        self.directory = Path(directory)
        self._lock = threading.RLock()  # serialises writers; readers never take it
        self._snapshot: Optional[_Snapshot] = None
        self._revision = 0
        self._parsed: Dict[str, Tuple[_CacheKey, DocumentResult]] = {}

    # -- training --------------------------------------------------------------

    def document_paths(self) -> List[Path]:
        """Corpus files with an allowed extension, sorted by name (hidden files skipped)."""
        if not self.directory.is_dir():
            return []
        return sorted(
            p for p in self.directory.iterdir()
            if p.is_file() and not p.name.startswith(".") and document_kind(p.name)
        )

    def _read_corpus(self) -> List[DocumentResult]:
        """Every document, in name order. Documents past the corpus caps are listed but not read,
        unchanged files come from the parse cache, and a reader crash costs only its document."""
        llm = extract_records_with_llm if llm_available() else None
        parsed: Dict[str, Tuple[_CacheKey, DocumentResult]] = {}
        documents: List[DocumentResult] = []
        n_read = total_bytes = 0
        for path in self.document_paths():
            try:
                stat = path.stat()
            except OSError as exc:  # strerror, not str(exc): that names the absolute path
                reason = exc.strerror or type(exc).__name__
                documents.append(_unread(path, 0, f"could not read file: {reason}"))
                continue
            size = stat.st_size
            if size > MAX_UPLOAD_BYTES:
                skipped = f"not read: larger than the {MAX_UPLOAD_BYTES // _MB} MB document limit"
            elif n_read >= MAX_DOCUMENTS:
                skipped = f"not read: the corpus limit of {MAX_DOCUMENTS} documents is reached"
            elif total_bytes + size > MAX_CORPUS_BYTES:
                skipped = f"not read: the corpus limit of {MAX_CORPUS_BYTES // _MB} MB is reached"
            else:
                skipped = ""
            if skipped:
                documents.append(_unread(path, size, skipped))
                continue
            n_read += 1
            total_bytes += size

            key: _CacheKey = (
                size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino, llm is not None
            )
            cached = self._parsed.get(path.name)
            if cached is not None and cached[0] == key:
                document = _copy(cached[1])
            else:
                try:
                    document = read_document(path, llm_extract=llm)
                except Exception as exc:  # a parser bug must cost one document, not the corpus
                    document = _unread(
                        path, size, f"could not read the document ({type(exc).__name__})"
                    )
            if document.cacheable:
                parsed[path.name] = (key, _copy(document))
            documents.append(document)
        self._parsed = parsed
        return documents

    def _fit(self, documents: List[DocumentResult], start: float) -> _Snapshot:
        """Fit the model on *documents* (whose warnings it extends). Raises ``TrainingFailed``
        instead of whatever the maths raised; nothing is published either way."""
        try:
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
            downweighted = _downweighted(records, data, model)
            i = 0
            for document in documents:
                for _ in document.records:
                    document.warnings.extend(downweighted.get(i, []))
                    i += 1

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
        except Exception as exc:
            raise TrainingFailed(
                f"the model could not be fitted on the corpus ({type(exc).__name__}); "
                "the previous model is kept"
            ) from exc
        for document in documents:
            document.cap_warnings()
        # Strictly increasing per fit, and wall-clock based so it keeps growing across server
        # restarts: clients use it to tell one fit from the next (trained_at is per second).
        self._revision = max(self._revision + 1, time.time_ns() // 1000)
        return _Snapshot(
            model=model,
            documents=tuple(documents),
            records=tuple(records),
            criteria=criteria,
            trained_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            train_ms=train_ms,
            revision=self._revision,
        )

    def _publish(self, snapshot: _Snapshot) -> Dict[str, Any]:
        self._snapshot = snapshot  # one assignment: a reader sees the old fit or the new one
        return self._status(snapshot)

    def retrain(self) -> Dict[str, Any]:
        """Re-read every document, refit the model, and return the new status.

        Raises ``TrainingFailed`` (422) when the fit fails: the previous model stays in place,
        or, if there is none yet, an expert-only model whose documents say why they are unused.
        """
        with self._lock:
            start = time.perf_counter()
            documents = self._read_corpus()
            try:
                return self._publish(self._fit(documents, start))
            except TrainingFailed as exc:
                if self._snapshot is None:
                    reason = (
                        f"not used: the model could not be fitted on the corpus "
                        f"({type(exc.__cause__).__name__}); the expert values apply"
                    )
                    unused = [replace(d, records=[], warnings=[reason, *d.warnings])
                              for d in documents]
                    self._publish(self._fit(unused, start))
                raise

    def _current(self) -> _Snapshot:
        snapshot = self._snapshot  # published whole and never mutated: safe without the lock
        if snapshot is None:
            with self._lock:
                if self._snapshot is None:
                    with contextlib.suppress(TrainingFailed):  # the fallback is in place
                        self.retrain()
                snapshot = self._snapshot
        assert snapshot is not None
        return snapshot

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

    def _check_room(self, name: str, size: int) -> None:
        """Raise ``CorpusFull`` unless *size* more bytes under *name* fit the corpus caps."""
        others = [p for p in self.document_paths() if p.name != name]
        if len(others) >= MAX_DOCUMENTS:
            raise CorpusFull(
                f"the corpus already holds {len(others)} documents, the limit; delete some first"
            )
        total = size
        for path in others:
            with contextlib.suppress(OSError):
                total += path.stat().st_size
        if total > MAX_CORPUS_BYTES:
            raise CorpusFull(
                f"the corpus would grow to {total / _MB:.1f} MB; the limit is "
                f"{MAX_CORPUS_BYTES // _MB} MB — delete some documents first"
            )

    def _write(self, path: Path, data: bytes) -> None:
        """Write atomically (a retrain never reads half a file), leaving no ``.partial`` behind."""
        partial = self.directory / f".{path.name}.partial"
        try:
            partial.write_bytes(data)
            os.replace(partial, path)
        except OSError:
            with contextlib.suppress(OSError):
                partial.unlink()
            raise

    def save_document(self, name: str, data: bytes, overwrite: bool = False) -> Dict[str, Any]:
        """Validate and store an uploaded document, retrain, and return the new status.

        Raises ``InvalidDocumentName`` / ``UnsupportedDocumentType`` / ``EmptyDocument`` (400),
        ``DocumentTooLarge`` / ``CorpusFull`` / ``TooManyRecords`` (413), ``DocumentExists``
        (409, unless *overwrite*) or ``TrainingFailed`` (422). After an error the corpus and the
        model are as before: the new file is removed, or the overwritten one put back.
        """
        name = sanitize_document_name(name)
        if not data:
            raise EmptyDocument("the uploaded file is empty")
        if len(data) > MAX_UPLOAD_BYTES:
            limit_mb = MAX_UPLOAD_BYTES // _MB
            raise DocumentTooLarge(f"the file is {len(data):,} bytes; the limit is {limit_mb} MB")
        with self._lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self.directory / name
            if path.resolve().parent != self.directory.resolve():
                raise InvalidDocumentName(f"invalid document name {name!r}")
            if path.exists() and not overwrite:
                raise DocumentExists(f"document {name!r} already exists")
            self._check_room(name, len(data))
            previous = path.read_bytes() if path.exists() else None
            self._write(path, data)
            try:
                start = time.perf_counter()
                documents = self._read_corpus()
                if any(d.name == name and d.truncated for d in documents):
                    raise TooManyRecords(
                        f"the document holds more than {MAX_RECORDS_PER_DOCUMENT:,} records; "
                        "split it into several files"
                    )
                snapshot = self._fit(documents, start)
            except Exception:
                if previous is None:
                    path.unlink(missing_ok=True)
                else:
                    self._write(path, previous)
                raise
            return self._publish(snapshot)

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
