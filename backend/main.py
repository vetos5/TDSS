"""
TDSS Backend — FastAPI server for the Transport Interchange DSS.

Exposes REST endpoints consumed by the Vue 3 frontend:
  - POST /api/evaluate        — run WSM evaluation
  - GET  /api/contexts        — list available interchange contexts
  - GET  /api/interchange/:name — detailed info for one interchange
  - GET  /api/blueprints/:name  — serve blueprint images
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.routes import router

app = FastAPI(
    title="TDSS API",
    description="Transport Interchange Decision Support System — MCDA/WSM Engine",
    version="4.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")

blueprints_dir = _ROOT / "assets" / "blueprints"
if blueprints_dir.exists():
    app.mount("/blueprints", StaticFiles(directory=str(blueprints_dir)), name="blueprints")
