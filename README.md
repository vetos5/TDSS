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

## Deploy to ZimaOS

`docker-compose.zima.yml` runs TDSS on a ZimaOS machine, or any other Docker host. The images
are built on the machine itself, so their CPU architecture always matches. From a development
machine with SSH access to the box:

```bash
scripts/deploy_zima.sh root@<zima-ip>      # copy the source, build, (re)start
```

Then open `http://<zima-ip>:8580`. Port 80 stays free for the ZimaOS dashboard. Running the same
command again redeploys. On the machine itself, run `docker compose -f docker-compose.zima.yml
build` and then `docker compose -f docker-compose.zima.yml up -d --force-recreate`. Plain `up
--build` can leave the containers running on the previous images.

- **Data** lives in `/DATA/AppData/tdss`: `corpus/` holds the prediction-model documents, and
  `cache/` holds the GIS responses. Both survive rebuilds. On first start an empty `corpus/` is
  seeded with the demo documents once. Documents you delete stay deleted. With
  `TDSS_SEED_DEMO=0`, the corpus starts empty.
- **Settings** go in a `.env` file in the repository root, which the deploy script copies along:
  `TDSS_PORT` (default 8580), `TZ`, `PUID` / `PGID` (owner of the data folders, default 1000),
  `TDSS_DATA` (data folder) and `TDSS_SEED_DEMO`. For the optional LLM extractor, set
  `TDSS_WITH_LLM=1`, `TDSS_LLM_EXTRACTION=1` and `ANTHROPIC_API_KEY`. `.env` is gitignored and
  never copied into an image.
- **Logs and status:** `docker compose -f docker-compose.zima.yml logs -f` or `ps` in
  `/DATA/AppData/tdss/src`. The backend has a health check, and the frontend starts once it passes.

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
  Mount a volume at `/opt/tdss/corpus/documents` to keep them, as `docker-compose.zima.yml` does.
  An empty volume is seeded with the demo documents on first start.

## Continuous deployment to ZimaOS

`deploy/zima/docker-compose.yml` turns the ZimaOS machine into its own deployment target. A small
deployer container checks GitHub every minute. When `main` has a new commit and every CI job for
it has passed (backend, frontend and the Docker build and smoke test), it builds that commit on
the box and replaces the running site. The box only makes outbound requests, so it needs no open
ports and no GitHub token, and pull requests from forks cannot run anything on it.

**Setup.** This needs a one-time step: `main` must contain `deploy/zima/` and
`docker-compose.zima.yml`, so merge this work first. Then, on the box:

```bash
mkdir -p /DATA/AppData/tdss-deployer && cd /DATA/AppData/tdss-deployer
# copy deploy/zima/docker-compose.yml here as docker-compose.yml
docker compose up -d
docker compose logs -f        # "watching vetos5/TDSS@main", then each deploy
```

ZimaOS can also import the same file under *App Store → Custom Install*.

- **Each deploy** downloads the commit and builds the images while the old site keeps running.
  It then recreates the containers and checks that the backend is healthy and that nginx serves
  the API.
  - If the build fails, the site is untouched, and the build is retried twice.
  - If the new version does not start, the previous images are restored and the commit is not
    retried.
  - A commit whose CI failed is never deployed.
- **App settings** (`TDSS_PORT`, `TZ`, `TDSS_SEED_DEMO`, `ANTHROPIC_API_KEY`, ...) go in
  `/DATA/AppData/tdss/app.env`.
- **Deployer settings** go in a `.env` next to the deployer's compose file:
  - `TDSS_BRANCH` (default `main`) and `TDSS_POLL_SECONDS` (default 60);
  - `TDSS_REQUIRE_CI=0` to deploy without waiting for CI;
  - `GITHUB_TOKEN`, a read-only token, only for a private repository.
- **Polling cost.** Polls use conditional requests, and an unchanged answer does not count
  against GitHub's anonymous limit of 60 requests an hour.
- **State** lives in `/DATA/AppData/tdss/deployer`. `deployed` holds the commit that is live, and
  `history.log` lists every deploy. To force a redeploy of the current commit, delete `deployed`
  and run `docker compose restart`.
- **Self-updating.** The deploy logic is `deploy/zima/deployer.sh`. It is fetched when the
  container starts and replaces itself when a deploy brings a new version.
- **Manual deploys** with `scripts/deploy_zima.sh` still work and use the same folders.

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
