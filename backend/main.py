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
  - POST /api/model/retrain   — re-read the corpus documents and refit the model
  - POST /api/model/documents — upload a corpus document (multipart "file"), then retrain
  - DELETE /api/model/documents/:name — delete a corpus document, then retrain
  - POST /api/model/predict   — expert vs. model criterion values with prediction intervals
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")
app.include_router(site_router, prefix="/api/site")
app.include_router(model_router, prefix="/api/model")

blueprints_dir = _ROOT / "assets" / "blueprints"
if blueprints_dir.exists():
    app.mount("/blueprints", StaticFiles(directory=str(blueprints_dir)), name="blueprints")
