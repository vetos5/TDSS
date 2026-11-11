# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

TDSS (Transport Interchange Decision Support System) ranks grade-separated highway interchange
types with multi-criteria decision analysis. It is a university diploma project, developed in
phases on `diploma/phase-N-*` branches. `DOCUMENTATION.md` is the full technical reference (maths
in §3, API in §6.2, frontend in §7). Read the relevant section instead of re-deriving behaviour,
and update it when behaviour changes.

## Commands

Backend (Python 3.11+, run from this directory):

```bash
source .venv/bin/activate                      # pip install -r requirements-dev.txt on first use
uvicorn backend.main:app --reload --port 8000
pytest -q                                      # whole suite
pytest tests/test_mcda_methods.py -q           # one file
pytest tests/test_prediction_model.py -k cross # tests matching a name
ruff check .                                   # lint (line length 100; legacy/ and app/ui/ excluded)
```

Frontend (Node 20+):

```bash
cd frontend && npm ci
npm run dev        # http://localhost:5173, proxies /api to localhost:8000 (override with TDSS_API=...)
npm run build      # the only frontend check CI runs; there are no frontend tests or linter
```

Docker: `docker compose up --build`, then http://localhost. ZimaOS: `scripts/deploy_zima.sh root@<host>`
(`docker-compose.zima.yml`, port 8580, data in `/DATA/AppData/tdss`; README *Deploy to ZimaOS*).
Continuous deployment: `deploy/zima/` (a pull-based deployer on the box; it deploys commits on `main`
once all CI jobs pass). CI's `docker` job builds and smoke-tests the stack, and `deployer.sh` must
stay POSIX `sh` (Alpine; `local` is fine) and pass `shellcheck -s sh -S warning -e SC3043`.

CI (`.github/workflows/ci.yml`) runs `ruff check .`, `pytest -q`, `npm run build`, and the `docker` job
(shellcheck, compose validation, image build and a smoke test through nginx).

Optional extras: `pip install -e '.[documents]'` adds `pypdf` and the Anthropic SDK for the corpus
readers. `.[legacy]` is only for the deprecated Streamlit UIs.

## Architecture

The layers are strict. Keep maths out of the routes and the frontend.

- `app/data/` holds expert constants and tunable defaults only, with no I/O and no logic. This
  includes the interchange alternatives and criteria (`interchange_data.py`), adjustment rules,
  MCDA method metadata, SMAA defaults, GIS defaults, and the prediction-model priors
  (`prediction_defaults.py`). Numbers a professor might challenge belong here, with their rationale.
- `app/application/` is pure Python and NumPy, with no web types and no I/O.
  - `adjustments.py` applies the site-parameter rules (terrain, environment, design speed, traffic
    demand) to the expert values. `traffic_engine.py` is the BPR travel-time model.
  - `mcda/` is the multi-method engine: `DecisionMatrix`, normalisation, weighting
    (manual / objective / AHP), the methods in `mcda/methods/` (WSM, TOPSIS, AHP, PROMETHEE II,
    VIKOR, all on a common `base.py` interface), rank agreement, SMAA-2 (`smaa.py`) and weight
    sensitivity.
  - `evaluation.py` is the service that the routes call. It turns a weighting choice into weights
    and runs the methods.
  - `site_analysis.py` and `footprint.py` infer site conditions from GIS data and place real-scale
    footprints.
  - `prediction/` is the Bayesian residual-correction model (a NIG conjugate prior over log-ratio
    residuals against the expert baseline, with LOO cross-validation). The maths is hand-written
    on purpose; see "Project constraints".
- `app/infrastructure/` handles I/O. `gis/` holds the Overpass and elevation clients with retry
  and a disk cache in `.cache/`. `corpus/` holds the document readers, the optional LLM extractor
  and `store.py`, which owns the trained model and retrains on upload or delete.
  `generators.py` and `app/domain/` hold the procedural interchange geometry.
- `backend/` is FastAPI. `routes.py` serves `/api/evaluate`, `/robustness`, `/methods`,
  `/contexts` and `/interchange`. `site_routes.py` serves `/api/site/*` and `model_routes.py`
  serves `/api/model/*`. Pydantic schemas are in `schemas.py`. `value_source: expert | model`
  on evaluate and robustness switches the criterion values between the expert constants and the
  prediction model.
- `frontend/src/` is a Vue 3 + Vite + Tailwind v4 SPA that only renders results. State lives in
  composables (`useDSS.js` for the evaluation, plus `useRobustness`, `useSiteAnalysis`,
  `useModel`, `useLocale`, `useTheme` and `useViewport`). HTTP calls go through `api.js`.
  `App.vue` composes the left `Sidebar.vue` inputs with tabbed views. Phones get `MobileTabBar.vue`
  and a `Sheet.vue` instead. Charts use Plotly through `PlotlyChart.vue`, with colours from
  `chartPalette.js`.
- `legacy/` and `app/ui/` are deprecated Streamlit UIs. Don't extend them.

## Conventions and traps

- **The v4 `/api/evaluate` contract is frozen.** `tests/test_evaluate_regression.py` checks every
  response against `tests/snapshots/evaluate_v4.json`. New fields are allowed. Changing or removing
  an existing field fails the test. `python -m tests._make_snapshot` regenerates the snapshot, but
  it records every current field (all of v5), so it freezes far more than the v4 contract. Run it
  only to accept a deliberate change, and review the diff.
- **Bilingual.** Every user-visible string exists in both `frontend/src/locales/en.json` and
  `uk.json`. Ukrainian is the default locale. Backend enum values shown in the UI are mapped to
  i18n keys in `locales/backendKeys.js`. API routes accept `lang`, and backend-generated text
  such as adjustment notes must be provided in both languages.
- **Tests never touch the network.** GIS and LLM clients are monkeypatched, and `conftest.py`
  disables retry sleeps. Keep new tests offline too.
- **Corpus.** Training documents are in `corpus/documents/` (or `TDSS_CORPUS_DIR`).
  `corpus/README.md` defines the fields, units and EN/UK synonyms the extractor accepts. The
  `synthetic_*` files are invented demo data from `python -m scripts.make_synthetic_corpus`. Costs
  are USD only.
- **The app is public; keep it safe to be.** Corpus edits need `TDSS_ADMIN_TOKEN` as a bearer
  token (`backend/auth.py`; off when unset). Give every new request field a bound in `schemas.py`,
  cap costly endpoints with `backend/limits.slot()`, and never return paths or upstream errors in
  `detail`. DOCUMENTATION.md §6.8 lists the limits; `frontend/nginx.conf` holds the rate limits.
- **LLM extraction is opt-in.** It runs only with `TDSS_LLM_EXTRACTION=1` and `ANTHROPIC_API_KEY`
  set, and `TDSS_LLM_MODEL` overrides the model. It is a fallback for documents the rule-based
  extractor cannot read and must stay outside the model itself.

## Project constraints

- The professor requires the prediction model to be the student's own: explainable at defence
  level and quickly retrainable from new documents. Don't replace it with a third-party ML or AI
  library, and keep any external AI optional.
- The UI is for engineers using professional tools. Keep every main input visible in the left
  panel and the views as tabs along the top. The desktop look is macOS-like (system font, system
  blue, grouped cards). Phones (below `md`) use floating liquid glass instead: a glass title pill,
  a glass pill tab bar with a round *More* button, a monochrome accent and pill controls (`.glass`,
  `.glass-backdrop`, `.liquid-ease` and the phone `@media` blocks in `style.css`). Tab and panel
  changes use short eased transitions, without blank loading states.

## Code map (read this instead of re-exploring)

Where things are and what they hold, so a session can go straight to the file it needs.

### Machines and checkouts

- Dev checkout: `~/projects/TDSS` on `vetos-prodesk1` (remote `origin` = `vetos5/TDSS`, work on
  `main` or a `diploma/phase-N-*` branch merged into `main`). Venv: `.venv` (Python 3.14 locally,
  CI uses 3.11, so avoid 3.12+ only syntax); `frontend/node_modules` installed.
- `~/apps/tdss` on the same box is the **deployer's** home (`TDSS_HOME`): `src/` is the deployed
  tarball (root-owned, replaced on every deploy), `deployer/` its state, `app.env` secrets. Never
  edit there.
- Deploy = push to `main`. CI runs on the self-hosted runner on this box; the deployer polls
  GitHub every 60 s and deploys a `main` commit once CI passed (`deployer/history.log`).

### Backend

- `app/data/interchange_data.py` — `CRITERIA` (4: `construction_cost_mln` min, `land_area_hectares`
  min, `throughput_vph` max, `safety_index` max /10), `INTERCHANGE_DATA[context][alt]`, 3 contexts:
  System (Cloverleaf, Turbine, Stack (4-Level)), Service (Diamond, SPUI, DDI), T-Type (Trumpet,
  Directional T). Also labels (EN/UK), descriptions, colours, `resolve_*` helpers,
  `get_alternatives_for_context()`.
- `app/data/adjustment_rules.py` — terrain cost factor, env land factor, loop-ramp speed penalty
  (`LOOP_RAMP_ALTERNATIVES`), capacity penalty constants.
- `app/application/adjustments.py` — `apply_project_params(alts, params)` → (feasible alts, notes).
  Peak-hour demand = `aadt * peak_factor/100`.
- `app/application/traffic_engine.py` — `bpr_travel_time`, `stress_level`, `los_grade(vc)` (A–F).
- `app/application/evaluation.py` — `select_weights`, `run_methods`, `analyse_robustness`.
- Professional analyses (DOCUMENTATION §3.13–3.18), routes in `backend/analysis_routes.py`:
  `engineering.py` (`Study`, `analyse` — per-element design-life traffic, crashes; constants in
  `app/data/engineering_defaults.py`) → `/api/engineering`; `economics.py` (`appraise` — LCC, NPV,
  BCR, payback) → `/api/economics`; `mcda/breakeven.py` → `/api/breakeven`; `mcda/group.py`
  (geometric-mean weight aggregation, Kendall τ) → `/api/group`. Request schemas: `StudyParams`,
  `EngineeringRequest`, `GroupRequest` in `schemas.py`. Tests: `test_engineering.py`,
  `test_economics.py`, `test_group.py`.
- `app/application/mcda/` — `DecisionMatrix.from_alternatives(alts, CRITERIA)`, `METHODS` dict
  (method fn on matrix + weights), `evaluate()`, `weighting`, `smaa.py`, `sensitivity.py`.
- `backend/routes.py` — `_prepare(req, lang)` is the shared pipeline (context check → optional model
  values → site rules → matrix → weights) returning `_Prepared(locale, alternatives, matrix,
  selection, weights, notes, model)`; reuse it for any new endpoint that ranks alternatives.
  `/robustness` wraps itself in `backend.limits.slot(semaphore)`.
- `backend/schemas.py` — `ProjectParams` (design_speed, aadt, peak_factor, num_lanes, budget,
  land_limit, terrain, env_sensitivity), `EvaluateRequest` (context, weights, params, methods,
  weighting, value_source). Every field needs bounds.
- `backend/main.py` mounts the routers under `/api`.
- Tests: `tests/test_api*.py` use `TestClient(backend.main.app)` and a `body(context, **extra)`
  helper; `tests/test_evaluate_regression.py` + `tests/snapshots/evaluate_v4.json` freeze
  `/api/evaluate`.

### Frontend

- `App.vue` — tab ids `evaluation, site, engineering, economics, robustness, model, compare, group,
  gallery, methodology` (TabNav keys 1–9, 0); each
  pane is mounted with `v-show` and gets `:dss`, `:active`, `:dark`. `title` map per tab id.
  Watches `dss` inputs and re-evaluates (debounced 300 ms).
- Adding a tab touches: `App.vue` (import, `title`, pane), `TabNav.vue` (`tabs`; labels show ≥1760px),
  `MobileTabBar.vue` (`PRIMARY` max 4 or `MORE`), `locales/*.json` (`tabX`, `tabShort.x`).
- `composables/useDSS.js` — module-level shared state: `params`, `weights`, `weighting`, `methods`,
  `valueSource`, `evalData`. `snapshotState / normalizeState / applyState` define what scenarios and
  share links store; a new input must be added there with a rule (`PARAM_RULES`-style).
- `useDSS.study` holds the design-life inputs (`STUDY_DEFAULTS`, `STUDY_RULES`; Sidebar `STUDY_FIELDS`).
- `composables/useAnalysis.js` — `useAnalysis(key)` request state for the professional tabs and
  `siteBody(dss)`; `useGroup.js` holds stakeholders (localStorage). `exporters.js` — CSV/GeoJSON/KML.
- `composables/useRobustness.js` — the pattern for a view's own request state (`data`, `loading`,
  `error`, `requestId` guard, `errorText(e)`).
- `api.js` — axios `/api`, one exported function per endpoint, `lang` as a query param.
- `components/Sidebar.vue` — inputs in collapsible `PanelSection`s (`id`, `title`, `summary`).
- `PlotlyChart.vue` takes `{ chart: { data, layout }, dark }`; colours from `chartPalette.js`
  (`chartInk(dark)`, `METHOD_COLORS`, `rankColors`); alternative colours come from the API
  (`color`, `color_dark`).
- CSS classes (`style.css`): `card card-title card-desc eyebrow field field-label btn btn-primary
  btn-ghost icon-btn seg seg-item table table-scroll notice notice-ok notice-warn notice-bad badge
  badge-accent num spinner tab-pane ios-slider glass glass-backdrop liquid-ease`; `bg-surface-solid` for
  opaque cells over translucent cards. Icons: `Icon.vue` `ICONS` map (Lucide paths).
- `locales/en.json` and `uk.json` are flat-ish objects read as `t.value.key`; keep them in sync.
- `DecisionReport.vue` is the printable report (`.report-*` classes).
