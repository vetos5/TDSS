"""
Document corpus for the criterion-value prediction model (file I/O, optional PDF / LLM).

API for the web layer
---------------------
``get_store() -> CorpusStore``
    Process-wide store on ``$TDSS_CORPUS_DIR`` (default ``<repo>/corpus/documents``). Trains
    lazily on first access. ``reset_store(path=None)`` swaps it (tests: a tmp dir; ``None``
    restores the env/default directory).

``CorpusStore``
    ``status() -> dict``                 the ``ModelStatus`` contract, JSON-ready
    ``retrain() -> dict``                re-ingest every document, refit, return status
    ``save_document(name, data, overwrite=False) -> dict``
                                         store an upload, retrain, return status
    ``delete_document(name) -> dict``    delete, retrain, return status
    ``model -> ResidualModel``           the fitted model; useful members:
        ``predict(type, conditions)``             per criterion {expert, predicted, low, high}
        ``corrections(type, conditions)``         per criterion Correction(factor=e^μ,
                                                  low_ratio, high_ratio)
        ``correct_values(type, raw_values, conditions)``
                                                  expert constants × e^μ (safety clamped) — feed
                                                  to ``apply_project_params``
        ``value_ranges(types, conditions)``       per criterion (min low_ratio, max high_ratio)
        ``n_records``, ``n_synthetic``, ``interval_level``
    ``predict(type, conditions)`` / ``corrections(type, conditions)``  shortcuts to the model.

    *conditions* may be ``backend.schemas.ProjectParams`` as is (or a dict / ``Conditions``).

Errors — ``CorpusError`` subclasses with a ``status_code`` attribute:
    ``InvalidDocumentName`` / ``UnsupportedDocumentType`` / ``EmptyDocument`` → 400,
    ``DocumentTooLarge`` / ``CorpusFull`` / ``TooManyRecords`` → 413, ``DocumentExists`` → 409,
    ``DocumentNotFound`` → 404, ``TrainingFailed`` → 422 (raised by ``retrain`` and the document
    calls; the previous model stays in place).

``read_document(path)`` / ``read_document_bytes(name, data)`` read a single document;
``llm_available()`` / ``pdf_available()`` report the optional extras.
"""

from __future__ import annotations

from app.infrastructure.corpus.llm_extraction import extract_records_with_llm, llm_available
from app.infrastructure.corpus.readers import (
    PDF_MISSING_WARNING,
    DocumentResult,
    document_kind,
    pdf_available,
    read_document,
    read_document_bytes,
)
from app.infrastructure.corpus.store import (
    CORPUS_DIR_ENV,
    DEFAULT_CORPUS_DIR,
    CorpusError,
    CorpusFull,
    CorpusStore,
    DocumentExists,
    DocumentNotFound,
    DocumentTooLarge,
    EmptyDocument,
    InvalidDocumentName,
    TooManyRecords,
    TrainingFailed,
    UnsupportedDocumentType,
    get_store,
    reset_store,
    sanitize_document_name,
)

__all__ = [
    "CORPUS_DIR_ENV",
    "DEFAULT_CORPUS_DIR",
    "PDF_MISSING_WARNING",
    "CorpusError",
    "CorpusFull",
    "CorpusStore",
    "DocumentExists",
    "DocumentNotFound",
    "DocumentResult",
    "DocumentTooLarge",
    "EmptyDocument",
    "InvalidDocumentName",
    "TooManyRecords",
    "TrainingFailed",
    "UnsupportedDocumentType",
    "document_kind",
    "extract_records_with_llm",
    "get_store",
    "llm_available",
    "pdf_available",
    "read_document",
    "read_document_bytes",
    "reset_store",
    "sanitize_document_name",
]
