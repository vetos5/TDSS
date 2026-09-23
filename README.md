# TDSS — Transport Interchange Decision Support System

Web application for selecting a grade-separated highway interchange type with multi-criteria
decision analysis. Backend: FastAPI + NumPy. Frontend: Vue 3 + Vite + Tailwind.

Full technical documentation: [DOCUMENTATION.md](DOCUMENTATION.md).

## Run locally

Backend (Python 3.11+), from the repository root:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn backend.main:app --reload --port 8000
```

Frontend (Node 20+):

```bash
cd frontend
npm ci
npm run dev          # http://localhost:5173, proxies /api to localhost:8000
# TDSS_API=http://localhost:8060 npm run dev   # if the backend runs on another port
```

Docker: `docker compose up --build`, then open http://localhost.

## Tests and lint

```bash
pytest -q
ruff check .
```

## Layout

| Path | Contents |
| --- | --- |
| `app/application/` | Decision engine and traffic model (pure Python, no I/O) |
| `app/data/` | Expert constants for interchange types and criteria |
| `app/domain/`, `app/infrastructure/` | Road geometry and procedural interchange generators |
| `backend/` | FastAPI routes and schemas |
| `frontend/` | Vue 3 single-page app |
| `legacy/`, `app/ui/` | Deprecated Streamlit UIs (`pip install -e .[legacy]`) |
