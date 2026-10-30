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

## Prediction model

The *Prediction model* tab learns from past interchange project documents how real projects
deviate from the expert criterion values. It then predicts site-specific cost, land, throughput
and safety with 90 % prediction intervals (a Bayesian residual correction; see
[DOCUMENTATION.md §3.12](DOCUMENTATION.md#312-criterion-value-prediction-model-v5-phase-4)).
While the corpus is empty it returns the expert values unchanged. To use the predictions in the
evaluation and robustness analysis, set the sidebar's *Criterion values* control to
*Prediction model*.

- **Add documents** by uploading them in the tab, or by copying them into `corpus/documents/`
  (or the directory in `TDSS_CORPUS_DIR`) and pressing **Retrain** (`POST /api/model/retrain`).
  Supported formats are `.csv`, `.json`, `.jsonl`, `.txt`, `.md` and `.pdf`, up to 5 MB each.
  [corpus/README.md](corpus/README.md) lists the fields and units and has text templates in
  English and Ukrainian.
- **Retraining** re-reads the whole corpus and refits in milliseconds. Uploads and deletions
  retrain automatically.
- **Demo data:** the shipped `synthetic_*` files are invented. Delete them once real documents
  exist. `python -m scripts.make_synthetic_corpus` regenerates the CSV.
- **Optional extras:** `pip install -e '.[documents]'` adds PDF reading (`pypdf`) and the
  Anthropic SDK. The LLM extractor is a fallback for text and PDF documents in which the
  rule-based extractor finds nothing. It runs only when `TDSS_LLM_EXTRACTION=1` and
  `ANTHROPIC_API_KEY` are set, and it sends the document text to the Anthropic API.
  `TDSS_LLM_MODEL` overrides the default model.
- **Docker:** the image includes `corpus/`, but uploaded documents stay inside the container.
  Mount a volume at `/opt/tdss/corpus/documents` to keep them.

## Tests and lint

```bash
pytest -q
ruff check .
```

## Layout

| Path | Contents |
| --- | --- |
| `app/application/` | Decision engine and traffic model (pure Python, no I/O) |
| `app/application/prediction/` | Prediction model: record validation, text extraction, Bayesian residual regression |
| `app/data/` | Expert constants for interchange types and criteria; prediction-model priors (`prediction_defaults.py`) |
| `app/domain/`, `app/infrastructure/` | Road geometry and procedural interchange generators |
| `app/infrastructure/corpus/` | Prediction-model document readers, optional LLM extractor, corpus store |
| `backend/` | FastAPI routes and schemas (`model_routes.py`: `/api/model/*`) |
| `corpus/` | Prediction-model training documents (`corpus/documents/`) and their format guide |
| `scripts/` | `make_synthetic_corpus.py`, the synthetic demo-corpus generator |
| `frontend/` | Vue 3 single-page app |
| `legacy/`, `app/ui/` | Deprecated Streamlit UIs (`pip install -e .[legacy]`) |
