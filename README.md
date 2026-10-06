# SatQuery AI

> **Query → Evidence → Understanding** — "From Pixels to Evidence to Understanding"

SatQuery AI turns a natural-language Earth-observation (EO) question into a validated, capability-aware workflow over multi-sensor satellite imagery (optical, multispectral and SAR). A user asks a question in plain language and receives an answer backed by measured, traceable evidence — or a clear statement of why the data cannot support an answer.

This repository is the **prototype application foundation** for that vision (Problem Statement 26167, ISRO / Department of Space; Team Chitravits). It is a React + Vite frontend and a FastAPI backend on Supabase, with a fully real upload → query → history flow, sensor-aware input validation, image-pair change-detection gating, persistent conversations/projects, profile analytics and server-generated PDF reports. The AI/model layer is **intentionally pending** (see [AI layer status](#ai-layer-status)); the orchestration contract and model-service protocol are in place so models can be added without reworking the app.

```
Browser → Frontend (Vite, :5173) → FastAPI Backend (:8000) → Supabase Cloud (PostgreSQL + Storage)
```

The frontend talks **only** to the FastAPI backend and never sees Supabase keys. Every developer runs frontend + backend locally, and every backend connects to the **same Supabase project**, so conversations, imagery, projects and jobs stay in sync across the team.

---

## Table of contents

- [What SatQuery does](#what-satquery-does)
- [Architecture](#architecture)
- [Tech stack](#tech-stack)
- [Project structure](#project-structure)
- [Key features](#key-features)
- [The real upload → query → history flow](#the-real-upload--query--history-flow)
- [Input validation engine](#input-validation-engine)
- [Backend data model & API](#backend-data-model--api)
- [AI layer status](#ai-layer-status)
- [First-time setup](#first-time-setup-fresh-clone)
- [Running the application](#running-the-application)
- [Testing](#testing)
- [Troubleshooting](#troubleshooting)
- [Documentation](#documentation)

---

## What SatQuery does

EO data spans optical, multispectral and SAR modalities at resolutions from sub-metre (Cartosat) to tens of metres (Sentinel). Extracting information normally requires expertise in sensors, bands, polarizations, coordinate systems, pair registration and model selection — and most tools are single-task. SatQuery's design orchestrates a registry of remote-sensing models and deterministic tools behind one conversational interface:

- **Deterministic tools** provide measurements (spectral indices, SAR backscatter, temporal statistics).
- **Specialist models** provide perception and interpretation (EarthMind-4B as the VLM / AI Analyst; MCD-Mamba for bi-temporal change).
- **Geospatial processing** gives every output spatial meaning (CRS, geometry, area, GeoJSON).
- **The Evidence Engine** connects, validates and verifies results before the answer is presented, so every number and location traces back to a source.

The full design, capability roadmap and prototype status for each block live in [`docs/design/`](docs/design/) — see [Documentation](#documentation).

---

## Architecture

The design is a **modular monolith with a capability-aware orchestration layer and an Evidence Engine**, with GPU models served as separate HTTP services. Target end-to-end flow:

```
User query + imagery (any supported language)
        │
API + Security Gateway
        │
Input Validation
        │
Preprocessing + Registration Quality Gate
        │
Analysis Orchestrator (intent → data assessment → tool/model selection → execution)
   │                    │                       │
Deterministic Tools   AI/ML Models           External Data Connectors
        │
Geo-Spatial Processing (shared)
        │
Evidence Aggregation → Validation + Uncertainty → Evidence Engine
        │
AI Analyst (EarthMind) → Claim Verification
        │
Answer + Map + Evidence + Trace (in the user's language)
```

What this prototype actually implements today: the interface, API gateway (no auth yet), input validation, raster preprocessing/previews, pair compatibility checks, the LangGraph orchestrator skeleton, the model-service contract, and the Evidence/Session stores. The model execution, deterministic tools, Evidence Engine verification, registration-residual gate and multilingual layer are designed and scaffolded but not yet running — see [`docs/design/02_system_architecture.md`](docs/design/02_system_architecture.md) for per-block status.

---

## Tech stack

| Layer | Technologies |
|---|---|
| **Frontend** | React 19, Vite 8, Tailwind CSS 4, Radix / shadcn-style primitives, framer-motion, lucide-react, oxlint. Mixed `.jsx` / `.tsx`, `tsconfig` `strict: false` |
| **Backend** | Python 3.12, FastAPI, Uvicorn, Pydantic v2 + pydantic-settings, python-multipart, supabase-py (PostgREST + storage3). No ORM, no raw SQL |
| **Geospatial** | Rasterio (bundled GDAL/PROJ) for raster inspection, reprojection and previews |
| **Orchestration** | LangGraph (`validate_inputs → route → execute_step → compose_response`) |
| **Model contract** | `backend/app/ml/` — `ModelService` contract + registry; GPU model services over `GET /v1/health` + `POST /v1/predict` |
| **Data** | Supabase PostgreSQL + Supabase Storage (private bucket `Satquery`) |
| **Tests** | pytest with an in-memory fake Supabase + fake Storage (`backend/tests/fakes.py`) |
| **Not yet present** | Authentication, running AI/ML, queues/workers, Redis, Nginx, CI |

---

## Project structure

```text
sat_/
├── src/                          # React + Vite frontend
│   ├── App.jsx                   # single source of navigation + session state + refresh restore
│   ├── lib/apiClient.ts          # the ONLY frontend → backend access point (typed fetch)
│   ├── components/               # LandingHero, Workspace, UserHistorySidebar, ProfileDashboard,
│   │                             #   SettingsPage, ImageViewer (+ legacy mock screens)
│   ├── components/ui/            # shadcn primitives, logo, animated background
│   └── data/mockData.js          # SUGGESTED_QUERIES / SATELLITE_SCENARIOS (UI copy + legacy screens)
│
├── backend/                      # FastAPI service
│   ├── app/
│   │   ├── main.py               # app init, CORS, exception handlers, routers under /api/v1
│   │   ├── api/routes/           # health, imagery, analysis, jobs, results, evidence,
│   │   │                         #   validation, conversations, projects, profile, settings, reports
│   │   ├── services/             # all business logic (imagery_, analysis_, raster_, report_, title_, …)
│   │   ├── schemas/              # Pydantic models + the ApiResponse envelope (common.py)
│   │   ├── validation/           # input-validation engine (file/raster/sensor/band/modality/workflow)
│   │   ├── orchestrator/         # LangGraph graph (no model/DB code here)
│   │   ├── ml/                   # ModelService contract + ModelRegistry (no torch/HF imports)
│   │   ├── db/supabase.py        # single cached Supabase client (service-role key)
│   │   └── core/                 # config (env), exceptions, logging, security
│   ├── tests/                    # pytest suite + fakes.py
│   ├── supabase/
│   │   ├── schema.sql            # baseline DDL for a fresh project
│   │   └── migrations/           # 0002 … 0008, applied manually in the Supabase SQL editor
│   ├── Dockerfile / docker-compose.yml
│   └── .env.example
│
└── docs/
    ├── design/                   # the 14 formal design & specification documents
    ├── ai-integration/           # HANDOFF.md + reference code for the model layer
    └── deploy/                   # deployment guide
```

Screen routing is callback-based in [`App.jsx`](src/App.jsx) (no router library): `landing` → `workspace` → `settings` / `profile`, plus legacy demo screens (`change` / `fusion` / `pipeline` / `analytics` / `report`) still rendered from mock data and out of scope for the backend-persistence work.

---

## Key features

### 1. Multi-sensor imagery ingestion & server-side raster inspection
- Accepts **GeoTIFF / TIFF / PNG / JPEG / WEBP** (up to 50 MB by default).
- TIFFs are parsed with Rasterio in a worker thread **before** the Storage upload: real `latitude`/`longitude` (scene centre) and `bbox` reprojected to WGS84, `cloud_cover` only from a genuine metadata tag, and full raster properties (bands, dtype, CRS, transform, bounds, nodata) stored in `metadata.raster`.
- A web-optimized **PNG preview** (long edge ≤ 1600 px, read decimated, 2–98 % stretch for non-8-bit, nodata transparent) is generated and stored at `imagery/{uuid}/thumbnail.png`; the row records `preview_path` / `preview_status`. Older TIFF rows get their preview generated once on first open, then cached.
- Every upload passes a **file-validation gate** first (empty, size, extension, magic bytes incl. BigTIFF, declared MIME, readability, pixel ceiling, band count, dtype, every-pixel-readable) → specific 422 codes with nothing stored.

### 2. Bi-temporal image pairs & the change-detection compatibility gate
- A **Single Image / Image Pair** toggle on the landing screen. Pair uploads send both files in one `POST /imagery/pair`; both are validated before anything is stored, then inserted as two rows sharing a `pair_id` (`pair_position` 1/2) — never a half pair.
- A query against a pair runs through the **change-detection compatibility gate** first (relaxed `chat` profile): an incompatible pair (bad file, same image twice, unsupported sensor, different modality, mismatched bands/band-count/dimensions/aspect-ratio/CRS/format/dtype) is rejected **422 with the failing code** and a `t1`/`t2` breakdown the UI renders as an "Invalid Input" card. **No job is created** for an incompatible pair.

### 3. Conversations, projects & persistent history
- The sidebar lists **conversations** (not files), grouped Today / Yesterday / Previous 7/30 Days / Older from each conversation's real `updated_at`.
- A conversation is created lazily by the first upload, titled "New Chat" until its first meaningful query, then titled **once** by a deterministic keyword matcher (no AI) — filenames never become titles; a manual rename is never overwritten.
- **Projects** group conversations and reference files. Full CRUD; deleting a project keeps its conversations.
- Refresh persistence stores only a pointer in `localStorage`; on mount the app re-fetches real records from the backend — never sample data.

### 4. Profile analytics & settings
- A single workspace profile (no auth in the prototype), with a dashboard aggregated in Postgres by one `profile_dashboard()` RPC: query/scene counts, current & longest streak, a year of daily activity, feature and remote-sensing usage. Task/data-type labels come from a deterministic keyword classifier, not a model.
- Settings (theme, sidebar density, notification/privacy flags, default data type / analysis task) persist per profile; theme and density are applied via `data-theme` / `data-sidebar-density` on `<html>`.

### 5. Server-generated PDF reports
- **Download Report** builds a PDF server-side from stored data only (conversation, jobs, results, evidence, imagery). A job with no stored result prints "Result not available"; nothing is invented.

### 6. Honest states, never fake data
- The primary flow shows backend data, an empty state, or a real error — never a fallback to fabricated analysis. Static UI copy (headings, suggestion chips) is the only hardcoded text.

---

## The real upload → query → history flow

1. [`LandingHero.jsx`](src/components/LandingHero.jsx) uploads the selected file via `POST /api/v1/imagery/upload` (real bytes → Supabase Storage → an `imagery` row) during its "Parsing GeoTIFF Metadata…" state.
2. [`App.jsx`](src/App.jsx)'s `handleStartAnalysis` awaits `submitAnalysis()` before opening the workspace, so the chat opens already showing the real **"Analysis request submitted." / status: queued** acknowledgment — or an honest error.
3. [`Workspace.jsx`](src/components/Workspace.jsx) does the same mid-chat against the conversation's most recent upload (`backendImageryId`), so follow-ups target the same image.
4. [`UserHistorySidebar.tsx`](src/components/UserHistorySidebar.tsx) fetches `GET /conversations` + `GET /analysis/history` on mount and on every refresh; empty → "No conversations yet.", failure → "Unable to load conversation history." + Retry (which creates nothing).

[`src/lib/apiClient.ts`](src/lib/apiClient.ts) is the single typed access point and must not set `Content-Type` for `FormData` (the browser sets the multipart boundary).

---

## Input validation engine

`backend/app/validation/` answers exactly one question: **is this input structurally/semantically valid for the requested workflow?** It never runs NDVI/change detection/registration, never calls a model, and is storage-agnostic (Supabase meets it only at `imagery_service.build_validation_image`).

- **Sensor scope:** Sentinel-1, Sentinel-2, Cartosat, RISAT — identified from `imagery.sensor`/`source` → TIFF tags → band metadata → filename. Out-of-scope → `UNSUPPORTED_SENSOR`; none → `UNKNOWN_SENSOR` where a workflow requires one.
- **Band identity** comes from the raster's own band names (Sentinel-2 `B04` etc.), not filenames; Cartosat by raster index; no band/polarisation validation for Sentinel-1/RISAT yet.
- **Two endpoints:** `POST /validation/validate` collects *every* applicable issue for a declared workflow; `POST /validation/change-detection` is a purpose-built T1/T2 check that stops at the **first** failing check in a fixed order. The latter (relaxed `chat` profile) also gates `POST /analysis`.
- Workflows are declarative (`workflow_validator.WORKFLOW_REGISTRY`) — add one there rather than scattering `if/else`.

A REJECT is a **successful HTTP 200** with the verdict in `data` (status, errors[], warnings[], per-check details). See [`docs/design/07_api_specification.md`](docs/design/07_api_specification.md) §4.2 for the full shapes and the validation-code list.

---

## Backend data model & API

All routes live under `/api/v1` and use one envelope: `{"success", "data", "error": {code, message, details} | null}`. Routes stay thin; logic lives in `services/`, the only layer that talks to `db/supabase.py`. Services raise typed `core/exceptions` subclasses that `main.py` maps to the envelope.

### Tables (source of truth: `backend/supabase/schema.sql`)

| Table | Purpose |
|---|---|
| `profiles` | Single workspace profile (no auth yet) |
| `user_settings` | One row per profile — theme, density, defaults, flags |
| `conversations` | Chat sessions listed by the sidebar |
| `imagery` | Scene metadata + Storage location; `pair_id`/`pair_position` for pairs; `preview_path`/`preview_status` for TIFF previews |
| `analysis_jobs` | An analysis *request* (FK → imagery; nullable `comparison_imagery_id` and `conversation_id`) |
| `analysis_results` | Stored results (retrieval only — empty until the AI layer writes them) |
| `evidence` | Evidence records tied to a result (retrieval only) |
| `audit_logs` | Activity log (schema only; nothing writes to it yet) |

Schema changes go in a **new numbered migration** under `backend/supabase/migrations/` and are applied **manually** in the Supabase SQL editor (there is no migration runner). Current migrations: `0002` upload fields, `0003` conversations, `0004` profile analytics + **RLS on all tables**, `0005` user settings, `0006` image pairs, `0007` imagery previews, `0008` projects. Running new code against an unmigrated DB fails with `503 SCHEMA_NOT_MIGRATED`.

### Endpoint summary

| Area | Endpoints |
|---|---|
| Health | `GET /health`, `/health/supabase`, `/health/storage` |
| Imagery | `POST /imagery/upload`, `POST /imagery/pair`, `POST /imagery`, `GET /imagery`, `GET /imagery/{id}`, `DELETE /imagery/{id}` |
| Validation | `POST /validation/validate`, `POST /validation/change-detection` |
| Analysis | `POST /analysis`, `GET /analysis/history`, `GET /jobs/{id}`, `GET /results/{id}`, `GET /results/{id}/evidence` |
| Conversations | `POST` / `GET` / `GET {id}` / `PATCH {id}` / `POST {id}/title` / `DELETE {id}`, plus `legacy/{imagery_id}` rename/delete |
| Projects | `GET` / `POST` / `GET {id}` / `PATCH {id}` / `DELETE {id}`, plus `{id}/files` upload/delete |
| Profile | `GET /profile`, `PATCH /profile`, `GET /profile/dashboard` (+ slices), `POST`/`DELETE /profile/avatar` |
| Settings | `GET /settings`, `PATCH /settings` |
| Reports | `POST /reports` → `application/pdf` |

Interactive docs: `http://localhost:8000/docs` (Swagger) and `/redoc`. Full request/response shapes, error codes and the model-service protocol: [`docs/design/07_api_specification.md`](docs/design/07_api_specification.md) and [`backend/README.md`](backend/README.md).

---

## AI layer status

**No AI/model layer runs yet — this is intentional for the current milestone.** A submitted query creates an `analysis_jobs` row that stays `status: "queued"` with `model_name = NULL`; `analysis_results` and `evidence` are empty by design.

The scaffolding is in place so models drop in without reworking the app:
- **Orchestration** in `backend/app/orchestrator/` (LangGraph; no model or DB code there).
- **Model contract + registry** in `backend/app/ml/` (no torch/HF imports in `contracts.py`/`registry.py`); unregistered tasks fail with `MODEL_NOT_AVAILABLE` — never a placeholder that returns text.
- **Model-service protocol** (`GET /v1/health`, `POST /v1/predict`) for EarthMind, MCD-Mamba and optional specialists, served as separate GPU services.

Start here before touching the model layer: [`docs/ai-integration/HANDOFF.md`](docs/ai-integration/HANDOFF.md) (current state, the two core models, the backend↔model-server protocol and the ordered task list; draft reference code in `docs/ai-integration/reference/`).

---

## First-time setup (fresh clone)

Requirements: **Node.js 20+**, **Python 3.12+**, Git.

```bash
git clone https://github.com/Shruti11506/sat_.git
cd sat_
npm install
npm run setup
```

`npm run setup` creates `backend/.venv`, installs `backend/requirements.txt`, and creates `backend/.env` from `backend/.env.example` (an existing `.env` is never overwritten).

Then fill in **`backend/.env`**:

| Variable | Description |
|---|---|
| `SUPABASE_URL` | Project URL: `https://<ref>.supabase.co` |
| `SUPABASE_SECRET_KEY` | Secret / `service_role` key (never a publishable/anon key — RLS would make every table read empty, and the backend refuses it with `503 SUPABASE_NOT_CONFIGURED`) |
| `SUPABASE_STORAGE_BUCKET` | Storage bucket (defaults to `Satquery`) |
| `MAX_UPLOAD_SIZE_MB` | Upload ceiling (default 50) |
| `CORS_ORIGINS` | Allowed origins (default `http://localhost:3000,http://localhost:5173`; any local port is allowed when `APP_ENV=development`) |

Never put Supabase keys in `VITE_*` variables. The frontend's optional root `.env` only sets `VITE_API_BASE_URL` (defaults to `http://localhost:8000/api/v1`).

**Database:** run `backend/supabase/schema.sql` once in the Supabase SQL editor for a fresh project, then apply each file under `backend/supabase/migrations/` in order.

---

## Running the application

```bash
npm run dev
```

This starts the Vite dev server at `http://localhost:5173` **and** the FastAPI backend at `http://localhost:8000` (the `satqueryBackend` Vite plugin starts uvicorn; it reuses one already on :8000 and stops with Vite). Opt out with `SATQUERY_SKIP_BACKEND=1`.

> The dev-server start has **no `--reload`**, so **restart `npm run dev` after backend edits**. On Windows, never run a detached backend with `--reload` — uvicorn's reloader keeps serving stale code. Confirm current code via `GET /openapi.json`.

To run the backend on its own:

```bash
cd backend
.venv\Scripts\activate            # Windows (source .venv/bin/activate elsewhere)
uvicorn app.main:app --reload --port 8000
```

Other scripts: `npm run build` (production build → `dist/`; no type-check step), `npm run preview`, `npm run lint` (oxlint). `docker compose up --build` exists but is **unverified** on this machine.

---

## Testing

```bash
cd backend
pytest -v                                      # full suite (in-memory fake Supabase, no network)
pytest tests/test_imagery_upload.py::test_upload_imagery_success -v   # one test
```

Tests use `backend/tests/fakes.py` (fake DB + fake Storage, incl. an `rpc()` mirror of `profile_dashboard`), so they run without a live Supabase or network. Note: the fake DB **does not** catch missing-migration errors — those only appear against a real unmigrated database.

There is no frontend test suite and no CI.

---

## Troubleshooting

**"Unable to load conversation history." — diagnose in this order** (all of these have happened; the sidebar now prints the reason):

1. **Which origin is the page on?** `npm run dev` silently moves to `5174`, `5175`, … when `5173` is taken, and stale Vite servers can linger. An origin the backend doesn't allow fails CORS and every API call errors with `TypeError: Failed to fetch`. In development, any `localhost`/`127.0.0.1`/`[::1]` port is allowed.
2. **Is the backend up and on current code?** A stopped backend gives `ERR_CONNECTION_REFUSED` on :8000. A uvicorn started without `--reload` keeps serving old code, so new routes 404 — compare `GET /openapi.json` against `backend/app/api/routes/`.
3. **Is the schema migrated?** New code on an unmigrated DB fails with `SUPABASE_ERROR` / `503 SCHEMA_NOT_MIGRATED` (`PGRST205` = missing table, `42703` = missing column in the server log).
4. **Transient:** Supabase drops the pooled connection after idle (`httpx.RemoteProtocolError`); sidebar reads go through `db/supabase.py::execute_read`, which retries once.

A fresh clone on another machine with no `backend/.venv` or `backend/.env` is the most common cause — `npm run dev` prints a boxed `[satquery]` warning when either is missing.

---

## Documentation

### Developer references
- [Backend Foundation & Endpoints](backend/README.md)
- [Architecture & Coding Standards](CLAUDE.md)
- [AI Layer Integration Handoff](docs/ai-integration/HANDOFF.md)
- [Deployment Guide](docs/deploy/DEPLOY.md)

### Design & specification documents

The full SatQuery AI design set (Problem Statement 26167, Team Chitravits) lives under [`docs/design/`](docs/design/):

| # | Document | Summary |
|---|---|---|
| 01 | [Solution Overview & Executive Summary](docs/design/01_solution_overview.md) | Core principle, problem analysis, proposed solution, capabilities and success criteria |
| 02 | [System Architecture](docs/design/02_system_architecture.md) | Architecture style, end-to-end pipeline, component blocks, data-flow and deployment |
| 03 | [Functional Requirements](docs/design/03_functional_requirements.md) | FR specification with MoSCoW priorities, acceptance criteria and traceability |
| 04 | [Non-Functional Requirements](docs/design/04_non_functional_requirements.md) | Performance, scalability, reliability, security and evidence-integrity targets |
| 05 | [Technical Design](docs/design/05_technical_design.md) | Models, tools, evidence, orchestration and the MCD-Mamba → EarthMind pipeline |
| 06 | [Data Strategy](docs/design/06_data_strategy.md) | Datasets, sensor handling, preprocessing, adaptation and external connectors |
| 07 | [API Specification](docs/design/07_api_specification.md) | Endpoints as implemented, response envelope, error codes and planned additions |
| 08 | [UI/UX Design](docs/design/08_ui_ux_design.md) | Design philosophy, workspace layout, evidence cards and safe-failure UX |
| 09 | [Evaluation Strategy](docs/design/09_evaluation_strategy.md) | Model, tool, orchestration and evidence evaluation; results templates |
| 10 | [Feasibility & Risk Analysis](docs/design/10_feasibility_risk_analysis.md) | Technical/economic/operational feasibility, risk register and fallback policy |
| 11 | [Innovation Statement](docs/design/11_innovation_statement.md) | Novelty dimensions and comparison against single VLMs and scripted GIS |
| 12 | [Project Timeline](docs/design/12_project_timeline.md) | MVP-first plan, extension track, milestones and critical path |
| 13 | [Sustainability Roadmap](docs/design/13_sustainability_roadmap.md) | Maintainability, future roadmap, scalability and impact |
| 14 | [References](docs/design/14_references.md) | Core models, datasets, external sources and research basis |
