"""
TDSS Backend — FastAPI server for the Transport Interchange DSS.

Exposes REST endpoints consumed by the Vue 3 frontend:
  - POST /api/evaluate        — run the MCDA evaluation (value_source: expert | model)
  - POST /api/robustness      — SMAA-2 rank acceptability + weight sensitivity
  - GET  /api/methods         — list the MCDA methods
  - GET  /api/contexts        — list available interchange contexts
  - GET  /api/interchange/:name — detailed info for one interchange
  - GET  /api/blueprints/:name  — serve blueprint images
  - POST /api/site/analyse    — infer context/terrain/environment/land from GIS data
  - POST /api/site/footprint  — place a real-scale interchange footprint + right-of-way estimate
  - GET  /api/model/status    — document-trained prediction model: corpus, accuracy, coefficients
  - POST /api/model/retrain   — re-read the corpus documents and refit the model (admin)
  - POST /api/model/documents — upload a corpus document (multipart "file"), then retrain (admin)
  - DELETE /api/model/documents/:name — delete a corpus document, then retrain (admin)
  - POST /api/model/predict   — expert vs. model criterion values with prediction intervals

Admin endpoints need the ``TDSS_ADMIN_TOKEN`` bearer token (backend/auth.py). There is no CORS
middleware: the SPA reaches the API on its own origin (nginx in production, Vite's proxy in dev),
so browsers refuse cross-site calls to it.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.model_routes import router as model_router
from backend.routes import router
from backend.site_routes import router as site_router

_ROOT = Path(__file__).resolve().parents[1]

app = FastAPI(
    title="TDSS API",
    description="Transport Interchange Decision Support System — MCDA/WSM Engine",
    version="5.0.0-dev",
)

# FastAPI's own 422 echoes every failing item with its input: a large body of bad list items gave
# a response many times its size, and a NaN input made the 422 itself fail as a 500.
_MAX_VALIDATION_ERRORS = 20


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [
        {"type": e.get("type"), "loc": list(e.get("loc", ())), "msg": e.get("msg")}
        for e in exc.errors()[:_MAX_VALIDATION_ERRORS]
    ]
    return JSONResponse(status_code=422, content={"detail": errors})


app.include_router(router, prefix="/api")
app.include_router(site_router, prefix="/api/site")
app.include_router(model_router, prefix="/api/model")

blueprints_dir = _ROOT / "assets" / "blueprints"
if blueprints_dir.exists():
    app.mount("/blueprints", StaticFiles(directory=str(blueprints_dir)), name="blueprints")
