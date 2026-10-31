"""
Prediction-model API: the document corpus, retraining, and model-predicted criterion values.

  - GET    /api/model/status            — model status: documents, accuracy, coefficients
  - GET    /api/model/auth              — 204 if the admin token is valid (admin)
  - POST   /api/model/retrain           — re-read the whole corpus directory and refit (admin)
  - POST   /api/model/documents         — upload a document (multipart "file"), retrain (admin)
  - DELETE /api/model/documents/{name}  — delete a document, retrain (admin)
  - POST   /api/model/predict           — expert vs. model values (with intervals) for a context

The endpoints marked admin need ``Authorization: Bearer <TDSS_ADMIN_TOKEN>`` (``backend.auth``).

The corpus, the fitted model and all validation of document names / sizes live in
``app.infrastructure.corpus``; this module only maps its errors to HTTP status codes. Handlers
are plain ``def`` so file I/O and the (millisecond) refit run in FastAPI's thread pool; the store
serialises retraining with its own lock.
"""

from __future__ import annotations

from typing import Annotated, Any, Callable

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile

from app.application.prediction import ResidualModel
from app.data.interchange_data import INTERCHANGE_DATA
from app.data.prediction_defaults import MAX_UPLOAD_BYTES
from app.infrastructure.corpus import CorpusError, get_store, sanitize_document_name
from backend.auth import editing_enabled, require_admin
from backend.schemas import (
    ModelStatus,
    PredictedAlternativeSchema,
    PredictRequest,
    PredictResponse,
    ProjectParams,
)

router = APIRouter()
admin_only = [Depends(require_admin)]


def _corpus_call(action: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run a store action, turning ``CorpusError`` into the HTTP status it carries."""
    try:
        return action(*args, **kwargs)
    except CorpusError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


def _with_editing(status: dict[str, Any]) -> dict[str, Any]:
    """The store's status plus whether this server accepts corpus edits (the UI hides them)."""
    return {**status, "editing_enabled": editing_enabled()}


def require_model_params(params: ProjectParams) -> None:
    """The model's traffic feature is ln(AADT / 45 000), so AADT must be positive."""
    if params.aadt <= 0:
        raise HTTPException(
            status_code=422, detail="AADT must be positive to use the prediction model."
        )


def current_model() -> ResidualModel:
    """The fitted model of the process-wide corpus store (trained lazily on first use)."""
    return get_store().model


@router.get("/status", response_model=ModelStatus)
def model_status():
    return _with_editing(get_store().status())


@router.get("/auth", status_code=204, dependencies=admin_only)
def check_admin_token():
    """Lets the UI check a token when it is entered, before the first upload or delete."""
    return Response(status_code=204)


@router.post("/retrain", response_model=ModelStatus, dependencies=admin_only)
def retrain_model():
    return _with_editing(_corpus_call(get_store().retrain))


@router.post("/documents", response_model=ModelStatus, dependencies=admin_only)
def upload_document(
    file: Annotated[UploadFile, File(description="A .csv .json .jsonl .txt .md or .pdf file")],
    overwrite: bool = Query(default=False),
):
    name = _corpus_call(sanitize_document_name, file.filename)
    # One byte past the limit is enough to tell "too large" without holding a huge upload.
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        limit_mb = MAX_UPLOAD_BYTES // (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"the file exceeds the {limit_mb} MB limit")
    return _with_editing(_corpus_call(get_store().save_document, name, data, overwrite=overwrite))


# ``:path`` so that an encoded separator (``..%2Fx.csv``) reaches the name check and is answered
# with 400 rather than silently failing to match the route.
@router.delete("/documents/{name:path}", response_model=ModelStatus, dependencies=admin_only)
def delete_document(name: str):
    return _with_editing(_corpus_call(get_store().delete_document, name))


@router.post("/predict", response_model=PredictResponse)
def predict_values(req: PredictRequest):
    """Every alternative of the context (no feasibility filter): the expert pipeline value and
    the model's point prediction and interval per criterion, under the request's conditions."""
    if req.context not in INTERCHANGE_DATA:
        raise HTTPException(status_code=404, detail=f"Unknown context: {req.context}")
    require_model_params(req.params)
    model = current_model()
    return PredictResponse(
        context=req.context,
        n_records=model.n_records,
        interval_level=model.interval_level,
        alternatives=[
            PredictedAlternativeSchema(name=name, values=model.predict(name, req.params))
            for name in INTERCHANGE_DATA[req.context]
        ],
    )
