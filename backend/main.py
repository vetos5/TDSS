"""
TDSS Backend — FastAPI server for the Transport Interchange DSS.

Exposes REST endpoints consumed by the Vue 3 frontend:
  - POST /api/evaluate        — run WSM evaluation
  - GET  /api/contexts        — list available interchange contexts
  - GET  /api/interchange/:name — detailed info for one interchange
  - GET  /api/blueprints/:name  — serve blueprint images
  - POST /api/site/analyse    — infer context/terrain/environment/land from GIS data
  - POST /api/site/footprint  — place a real-scale interchange footprint + right-of-way estimate
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

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

blueprints_dir = _ROOT / "assets" / "blueprints"
if blueprints_dir.exists():
    app.mount("/blueprints", StaticFiles(directory=str(blueprints_dir)), name="blueprints")
