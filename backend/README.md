# SatQuery AI — Backend Foundation

## 1. Purpose

This is the backend foundation for SatQuery AI: a REST API that sits between the existing SatQuery frontend and Supabase (PostgreSQL + Storage). It registers satellite imagery metadata, records analysis *requests*, and retrieves stored results/evidence.

**AI models and agentic orchestration are intentionally not implemented in this milestone.** The `analysis_type` values, `analysis_jobs` table, and `/analysis` endpoint exist only as a stable, future-ready API contract — no VLM, SAR model, change-detection model, captioning model, or agent framework runs behind them. A job created today stays in `queued` status until a future milestone adds real processing.

Current flow:

```
Existing SatQuery UI → FastAPI → Supabase → stored metadata / analysis requests / results
```

## 2. Existing frontend integration

The frontend (repo root, outside `backend/`) is a Vite + React app — see the root [`CLAUDE.md`](../CLAUDE.md) for its architecture. It is now **fully backend-driven** for the upload → query → history flow: no hardcoded chat history, no fabricated AI analysis text, no "Sample Demo" fake scenario.

[`src/lib/apiClient.ts`](../src/lib/apiClient.ts) is a typed `fetch` wrapper for every endpoint below.

- [`LandingHero.jsx`](../src/components/LandingHero.jsx)'s `processFile()` uploads the selected file via `/imagery/upload` during its existing "Parsing GeoTIFF Metadata..." loading state. The old "Sample Demo (Bengaluru 0.28m)" button was removed — it only ever produced a fabricated scenario with no real backend record.
- [`App.jsx`](../src/App.jsx)'s `handleStartAnalysis` awaits the real `submitAnalysis()` call before rendering the Workspace, so the chat shows a neutral **"Analysis request submitted." / status: queued** acknowledgment — never a fabricated NDWI/NDVI/SAR paragraph. If no image was attached (or its upload failed), it shows an honest notice instead of silently falling back to demo content.
- [`Workspace.jsx`](../src/components/Workspace.jsx) does the same for a mid-chat attachment + query. Its old `generateAgentResponse()` keyword-matcher (fake NDWI/NDVI/SAR responses) and the "report"/"compare" fake-redirect branches were removed entirely.
- [`UserHistorySidebar.tsx`](../src/components/UserHistorySidebar.tsx) lists **conversations** (`GET /api/v1/conversations`) plus legacy pre-conversation requests from `GET /api/v1/analysis/history`. A conversation is titled "New Chat" until its first meaningful query, then titled once from that query (never from an uploaded filename); users can rename or delete it from the hover menu. Empty data renders "No conversations yet.", a failed fetch renders "Unable to load conversation history." with a Retry button, and neither ever falls back to sample data.
- Page-refresh persistence: `localStorage` holds only a pointer (`satquery-last-conversation-id`, or `satquery-last-imagery-id` for legacy chats), never the data itself — on mount, `App.jsx` re-fetches it fresh from the backend and reconstructs the chat from real records. A stale/deleted pointer is cleared, never used to show fake data.

The five pre-existing demo screens (`ChangeDetection`, `FusionViewer`, `AgentPipeline`, `AnalyticsDashboard`, `ReportScreen`, all reachable via the "Compare"/"Full Report" buttons and sidebar shortcuts) are **out of scope** for this milestone and still render entirely from `SATELLITE_SCENARIOS` mock data — see "Current limitations" below.

To point the frontend at a running backend, copy the root `.env.example` to `.env` and set `VITE_API_BASE_URL` (defaults to `http://localhost:8000/api/v1`).

## 3. Architecture

```
Existing SatQuery UI
        │  REST API (fetch)
        ▼
┌──────────────────────┐
│      FastAPI          │
│  api/routes  (thin)    │
│  schemas     (Pydantic)│
│  services    (logic)   │
│  db/supabase (client)  │
│  core        (config,  │
│               errors,  │
│               logging) │
└──────────┬────────────┘
           ▼
┌──────────────────────┐
│       Supabase         │
│  PostgreSQL + Storage   │
└──────────────────────┘
```

Routes never talk to Supabase directly — they call a service function, which calls `app/db/supabase.py`. Business logic and error translation live in `services/`, not in routes.

## 4. Folder structure

```
backend/
├── app/
│   ├── main.py              # FastAPI app, CORS, exception handlers, router wiring
│   ├── api/routes/          # health, imagery, analysis, jobs, results, evidence, validation, conversations, projects, profile, settings
│   ├── validation/          # validation engine (change detection, modality, bands, dimensions, CRS, workflows)
│   ├── schemas/             # Pydantic request/response models + the ApiResponse envelope
│   ├── services/            # business logic, talks to Supabase via db/supabase.py
│   ├── db/supabase.py       # single place the Supabase client is constructed
│   └── core/                # config (env vars), logging, security (UUID validation), exceptions
├── tests/                   # pytest suite (327 tests), in-memory fakes + regression tests
├── supabase/
│   ├── schema.sql           # DDL for baseline tables (new projects)
│   └── migrations/          # incremental migrations (0002 to 0008_projects.sql)
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── .env                     # local only, gitignored — fill in real Supabase values here
```

## 5. Python setup (without Docker)

Requires Python 3.12+.

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

pip install -r requirements.txt
cp .env.example .env          # then fill in your Supabase values
uvicorn app.main:app --reload --port 8000
```

## 6-7. Supabase setup, URL/key configuration

1. Create a Supabase project (or use an existing one).
2. In the Supabase dashboard, go to **Project Settings → API** and copy:
   - **Project URL** → `SUPABASE_URL`
   - **anon / publishable key** → `SUPABASE_PUBLISHABLE_KEY` (not currently used server-side, kept for parity with the frontend)
   - **service_role / secret key** → `SUPABASE_SECRET_KEY` — **server-side only, never send this to the frontend**
3. Paste these into `backend/.env` (copy from `.env.example` first). `.env` is gitignored and must never be committed.

## 8. Database schema

**New project**: run [`supabase/schema.sql`](supabase/schema.sql) once, in the Supabase SQL editor (Project → SQL Editor → New query → paste → Run).

**Existing project** (already ran an earlier version of `schema.sql` with a `file_path` column instead of `storage_path`/`bucket`/`mime_type`/`file_size`/`original_filename`): run [`supabase/migrations/0002_imagery_upload_fields.sql`](supabase/migrations/0002_imagery_upload_fields.sql) instead. It renames `file_path` → `storage_path` and adds the new columns — safe on an empty table, additive otherwise, never deletes data.

| Table | Purpose |
|---|---|
| `imagery` | Registered satellite scene metadata + Storage location (`bucket`, `storage_path`, `mime_type`, `file_size`, `original_filename`) |
| `analysis_jobs` | An analysis *request* — status stays `queued` until a future AI layer processes it |
| `analysis_results` | Stored results (retrieval only — this API never writes AI answers) |
| `evidence` | Stored evidence records tied to a result (retrieval only) |
| `audit_logs` | Backend/API activity log table (schema only; nothing currently writes to it) |

## 9. Storage setup

Uses the **existing** `Satquery` bucket (private) — the backend never creates a bucket. Confirmed via `client.storage.list_buckets()` against the live project: `Satquery` is the only bucket, `public: false`. Set `SUPABASE_STORAGE_BUCKET` in `.env` if your bucket is named differently.

Conceptual folder layout inside the bucket (see `app/services/storage_service.py`), enforced by `build_storage_path()`:

```
Satquery/
  imagery/{uuid}/{original filename}
  results/
  evidence/
  exports/
```

The `{uuid}` per upload prevents filename collisions and guarantees one user's upload never overwrites another's.

Since the bucket is **private**, `GET /api/v1/imagery/{id}` resolves a fresh **signed URL** (1 hour TTL) rather than a public URL — see `storage_service.resolve_url()`, which checks `get_bucket().public` and switches to a public URL automatically if the bucket's privacy is ever changed. The bucket itself is never made public by this backend.

**TIFF/GeoTIFF uploads** are also read with rasterio (`services/raster_service.py`; the PyPI wheel bundles GDAL/PROJ, so no system packages): a downscaled PNG preview (long edge ≤ 1600 px, read decimated; true colour only when the bands really are R/G/B — colour-interpreted RGB(A), or bands named B4/B3/B2 or red/green/blue — otherwise the file's colour palette, grayscale, or a labelled bands-1-2-3 composite; 2–98 % stretch for non-8-bit data, nodata transparent) is stored at `imagery/{uuid}/thumbnail.png` next to the untouched original, and recorded on the row as `preview_path` / `preview_status` (`ready`/`failed`; migration `0007_imagery_previews.sql`), with the file's properties (size, bands, dtype, CRS, transform, bounds, nodata) and the preview composition in `metadata.raster`. A TIFF row without a recorded preview (older uploads) gets it generated once on first open, then cached; and the file's real footprint is reprojected to WGS84 into `latitude`/`longitude` (scene centre) and `bbox` = `{west, south, east, north, crs: "EPSG:4326", source_crs}`. `cloud_cover` is set only from a real metadata tag (`CLOUD_COVERAGE_ASSESSMENT`, `CLOUDY_PIXEL_PERCENTAGE`, …). Anything the file doesn't carry stays null, and a file rasterio can't parse still uploads normally, just without these extras. Measured: 0.65 s for a 26.6 MB, 105-megapixel int16 raster, so it runs inside the request (in a worker thread) with no queue.

### Row Level Security

The backend connects with the `service_role` (`SUPABASE_SECRET_KEY`), which always bypasses RLS, so RLS doesn't affect FastAPI ↔ Supabase. Migration `0004_profile_analytics.sql` **enables RLS on every table** with no policies for `anon`/`authenticated`, and revokes `profile_dashboard()` from those roles — the frontend never talks to Supabase directly, so they get zero access (verified: the publishable key reads 0 rows and gets `42501` on the function).

## 10-11. API endpoints & examples

Most responses use one envelope:

```json
{ "success": true, "data": { ... }, "error": null }
{ "success": false, "data": null, "error": { "code": "IMAGE_NOT_FOUND", "message": "..." } }
```

The `/health/*` connectivity checks are the exception — they put status in `data` on both success *and* failure, so a caller can render "disconnected" without special-casing:

```json
{ "success": true, "data": { "supabase": "connected", "database": "connected", "storage": "connected", "bucket": "Satquery" }, "error": null }
{ "success": false, "data": { "supabase": "degraded", "database": "connected", "storage": "disconnected", "bucket": "Satquery" }, "error": { "code": "SUPABASE_STORAGE_ERROR", "message": "Unable to access the Supabase Storage bucket 'Satquery'." } }
```

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/health` | Liveness check |
| GET | `/api/v1/health/supabase` | Verifies the Supabase client, database, **and** the `Satquery` Storage bucket in one call |
| GET | `/api/v1/health/storage` | Storage-only version of the same check |
| POST | `/api/v1/conversations` | Create a conversation titled "New Chat" (`title_source: default`) |
| GET | `/api/v1/conversations?limit=100` | List **started** conversations (at least one upload or query), most recently active (`updated_at`) first — the sidebar's data source. Empty ones are hidden, not deleted; `python scripts/purge_empty_conversations.py [--apply]` removes those older than an hour (dry run by default) |
| GET | `/api/v1/conversations/{id}` | Conversation + its `imagery` (with fresh `url`) and `jobs`, oldest first |
| PATCH | `/api/v1/conversations/{id}` | Rename (`{"title"}`); sets `title_source: user`, never auto-overwritten |
| POST | `/api/v1/conversations/{id}/title` | Title from the FIRST meaningful stored query (deterministic keywords, `services/title_service.py`, no AI). No-op once `auto`/`user` |
| DELETE | `/api/v1/conversations/{id}` | Deletes its jobs, then each imagery (row + Storage object), then the conversation |
| POST | `/api/v1/imagery/upload` | **Real upload**: multipart file → Supabase Storage (`Satquery` bucket) → `imagery` row. Optional form field `conversation_id`. Used by the frontend. |
| POST | `/api/v1/imagery` | Register imagery metadata only (no file) — for a file already placed in Storage some other way |
| GET | `/api/v1/imagery?page=1&page_size=20` | List imagery (paginated, from the database — never scans Storage) |
| GET | `/api/v1/imagery/{imagery_id}` | Get one imagery record, with a freshly-resolved signed/public `url` (and `thumbnail_url` for a TIFF/GeoTIFF that got a generated PNG preview, else null) |
| DELETE | `/api/v1/imagery/{imagery_id}` | Deletes the DB record first, then the Storage object (see note below). |
| POST | `/api/v1/imagery/pair` | **Image pair upload**: multipart `image_1` (reference) + `image_2` (comparison), optional `conversation_id`. Both validated before anything is stored (errors prefixed "Image 1:"/"Image 2:"; a missing file → 422 `IMAGE_PAIR_INCOMPLETE`); two independent Storage objects + two `imagery` rows sharing `pair_id` (`pair_position` 1/2) in ONE insert; on a failure the objects it uploaded are removed. Returns `{pair_id, image_1, image_2}`, each in the `/imagery/upload` shape. Needs migration `0006_image_pairs.sql` (else 503 `SCHEMA_NOT_MIGRATED`). |
| POST | `/api/v1/analysis` | Create an analysis job (**no AI inference**) — validates `imagery_id` exists and `query` is non-empty; optional `conversation_id`; optional `comparison_imagery_id` (Image 2 of a pair; must exist and differ from `imagery_id`, else 404 `IMAGE_NOT_FOUND` / 422 `INVALID_IMAGE_PAIR`). **When `comparison_imagery_id` is set, the pair is run through the same change-detection compatibility gate as `/validation/change-detection` (`analysis_service._reject_incompatible_pair`) before any row is written** — an incompatible pair (mismatched modality/bands/dimensions/aspect-ratio/CRS/format) is 422 with the failing code and a `error.details.{workflow, errors[], t1, t2}` breakdown, and no job is queued. |
| GET | `/api/v1/analysis/history?limit=50` | `analysis_jobs` joined with `imagery`, most recent first — the sidebar's sole data source |
| GET | `/api/v1/jobs/{job_id}` | Get job status |
| GET | `/api/v1/results/{result_id}` | Get a stored result (404 if none exists yet) |
| GET | `/api/v1/results/{result_id}/evidence` | Get stored evidence for a result |
| GET | `/api/v1/profile/dashboard` | Everything the profile page shows in ONE request: user, stats (queries, scenes analyzed, current/longest streak), a year of daily activity (zeros included, starting on a Sunday), insights, feature usage, remote-sensing usage, recent activity |
| GET | `/api/v1/profile` | `{user, stats}` |
| PATCH | `/api/v1/profile` | Update any of `display_name`, `username`, `headline`, `bio` (only the fields sent) |
| POST / DELETE | `/api/v1/profile/avatar` | Upload (multipart `file`, JPG/PNG/WEBP ≤ 5 MB → `avatars/{profile id}/…` in the bucket) / remove the profile photo |
| GET | `/api/v1/profile/activity?period=year`, `/insights`, `/features`, `/recent-activity` | Slices of the dashboard |
| POST | `/api/v1/validation/validate` | **Input Validation gate** (`app/validation/`) — checks whether already-uploaded image(s) are structurally/semantically valid for a requested workflow (`ndvi`, `sar_change_vv`, `optical_sar_analysis`, …) BEFORE anything runs on them. Never a 4xx/5xx for a REJECT verdict — the envelope stays `success: true`; the verdict is `data.status` (`VALID`/`REJECT`) with `data.errors`/`data.warnings` (every applicable problem, each with a machine-readable `code`). No AI/ML runs here. |
| POST | `/api/v1/validation/change-detection` | **Strict T1/T2 compatibility gate** (`app/validation/change_detection_validator.py`) for bi-temporal change detection specifically — takes `{t1_imagery_id, t2_imagery_id, aspect_ratio_tolerance?, require_exact_dimensions?, require_matching_format?, require_geospatial?}`. Runs a fixed, STOPPING order (unreadable → distinct images → supported format → **modality** → format family → aspect ratio → exact dimensions → bands (strict VV↔VV/VH↔VH for SAR) → CRS/geotransform) and reports only the first failure, with `{code, message, t1, t2}` naming the two conflicting values (e.g. `"RGB"`/`"Multispectral"`). Response is `{status, valid, workflow, t1, t2, errors, warnings}` (`t1`/`t2` are `null` when that image couldn't be read). Never reprojects/resizes/resamples to "fix" a mismatch. **This same validator also gates `POST /analysis`** (see below) — this standalone endpoint exists for a frontend that wants to pre-check a pair before submitting, or for a different `analysis_type` to use different `requirements` later. |

Error codes added by the upload flow: `UNSUPPORTED_FILE_TYPE`, `EMPTY_FILE`, `FILE_TOO_LARGE`, `MISSING_FILENAME`, `INVALID_METADATA` (422), `STORAGE_UPLOAD_FAILED` (500, upload itself failed — no DB record is created), `INVALID_QUERY` (422, empty/whitespace-only query on `/analysis`). Conversations add `CONVERSATION_NOT_FOUND` (404) and `INVALID_TITLE` (422). The conversation endpoints need migration `supabase/migrations/0003_conversations.sql`.

**Settings endpoints** (`GET /api/v1/settings`, `PATCH /api/v1/settings` with only the changed flat fields, e.g. `{"theme": "system", "notify_product_updates": true}`) need migration `supabase/migrations/0005_user_settings.sql` (else 503 `SCHEMA_NOT_MIGRATED`). Values are validated against the same lists as the table's CHECK constraints, and unknown fields (including any `user_id`/`profile_id`) are rejected with 422 `VALIDATION_ERROR`. The row is created with defaults on first read. Profile fields are edited through `/profile`, not here.

**Change Detection Input Validation** (`app/validation/change_detection_validator.py` + `dimension_validator.py`, no migration needed) is a second, stricter validator living in the same package, purpose-built for the T1/T2 shape of bi-temporal change detection: it compares the two images directly (aspect-ratio tolerance, exact pixel dimensions, cross-image CRS equality via `geospatial_validator.crs_match_issue`) rather than checking each image against an abstract workflow spec. It reuses `raster_validator`/`modality_validator`/`band_validator` for the actual detection logic. Configurable via the four request fields above (`ChangeDetectionRequirements` in `schemas.py`); the shipped defaults match what this prototype's single change-detection path actually needs (identical dimensions, matching raster format, geospatial required). Modality is checked before the format-family check (not the reverse) so a plain-RGB-JPEG-vs-multispectral-GeoTIFF pair is rejected as `MODALITY_MISMATCH`, the more informative reason; the geospatial/CRS step only applies when the pair is TIFF-family to begin with, so two otherwise-compatible plain JPEGs are never rejected for lacking a CRS neither side ever claimed to have. Two same-family-but-different-content bi-temporal observations (a real T1 vs T2) are always VALID — only structural incompatibility is rejected, never a pixel-content difference. **This validator is wired into `POST /analysis`** (see the endpoint table above) — that's the actual bug it fixes: previously an incompatible pair was queued and shown as "Analysis Request / Queued" in the UI regardless of compatibility.

**Input Validation** (`app/validation/`, no migration needed — it doesn't add any table) answers exactly one question per image: is it structurally/semantically suitable for a *requested* workflow, given a declarative `WorkflowRequirements` table (`workflow_validator.WORKFLOW_REGISTRY`)? It never runs, approximates, or fabricates an AI/scientific result — see the package docstring in `app/validation/__init__.py` for the full scope boundary and pipeline. `imagery_service.build_validation_image()` is the only place it touches Supabase: a TIFF whose structure was already recorded at upload time (`imagery.metadata.raster.properties`) is validated from that stored dict with no re-download; everything else (JPEG/PNG, or an older TIFF row) is read once from Storage, read-only. Modality/band identity come only from the raster's own band names/colour-interpretation or an explicit `modality_hint` — never a filename. `POST /validation/validate` takes `{workflow, images: [{imagery_id, role?, modality_hint?}], aoi?}`; `role` is `single`/`t1`/`t2`/`optical`/`sar`. Resource limits (`VALIDATION_MAX_IMAGE_WIDTH/HEIGHT/BANDS/INPUT_IMAGES` in `.env`) are checked alongside file-size (`MAX_UPLOAD_SIZE_MB`, reused).

**Profile endpoints** need migration `supabase/migrations/0004_profile_analytics.sql` (until then they return 503 `SCHEMA_NOT_MIGRATED`, and the page shows that message with Retry). Identity: no login in this prototype — exactly one workspace profile (a unique index enforces it), resolved server-side by `profile_service.get_current_profile`; no endpoint accepts a user id. Aggregation runs in Postgres (`profile_dashboard()`, one RPC); Python only derives streaks and keyword categories (`services/usage_classifier.py` — deterministic, not a model: task from the query text, data type from filename/sensor/source, with JPEG/PNG/WEBP defaulting to Optical / RGB). Days are bucketed in the profile's `timezone`, else `APP_TIMEZONE` (default `Asia/Kolkata`); the current streak survives until today ends. Errors: `INVALID_DISPLAY_NAME`, `INVALID_USERNAME`, `INVALID_HEADLINE`, `INVALID_BIO` (422), avatar reuses `UNSUPPORTED_FILE_TYPE` / `EMPTY_FILE` / `FILE_TOO_LARGE`.

Example — upload an image, then create an analysis request:

```bash
curl -X POST http://localhost:8000/api/v1/imagery/upload \
  -F "file=@scene.jpg;type=image/jpeg" \
  -F "name=Bengaluru scene" -F "source=Sentinel-2" -F "sensor=MSI"
# → { "success": true, "data": { "id": "<uuid>", "name": "Bengaluru scene", "original_filename": "scene.jpg",
#      "bucket": "Satquery", "storage_path": "imagery/<uuid>/scene.jpg", "mime_type": "image/jpeg",
#      "file_size": 123456, "status": "registered" }, "error": null }

curl -X POST http://localhost:8000/api/v1/analysis \
  -H "Content-Type: application/json" \
  -d '{"imagery_id":"<uuid>","analysis_type":"vqa","query":"What is visible in this image?"}'
# → { "success": true, "data": { "job_id": "<uuid>", "imagery_id": "<uuid>", "analysis_type": "vqa",
#      "query": "What is visible in this image?", "status": "queued" }, "error": null }
```

Interactive docs: `http://localhost:8000/docs` (Swagger UI) and `http://localhost:8000/redoc`.

## 12-14. Docker

### What these tools are (first-time setup)

- **Docker**: a tool that packages an application with everything it needs to run (Python, dependencies, code) so it behaves identically on any machine.
- **Docker image**: the packaged, read-only blueprint built from the `Dockerfile` — think of it as a frozen snapshot of the app + its environment.
- **Docker container**: a running instance of an image — the actual live process.
- **Dockerfile**: the recipe (`backend/Dockerfile`) that builds the image: start from `python:3.12-slim`, install `requirements.txt`, copy the app, run `uvicorn` on port 8000.
- **docker-compose.yml**: describes how to run one or more containers together (here, just the `api` service) with one command, instead of typing a long `docker run ...` line every time.

### Commands

```bash
docker --version              # confirm Docker is installed
docker compose version        # confirm Compose is available

docker compose build          # build the image from the Dockerfile
docker compose up             # build (if needed) and start the container, logs in foreground
docker compose up -d          # same, but detached (runs in background)
docker compose down           # stop and remove the container
docker compose ps             # list running containers for this project
docker compose logs -f        # follow the container's logs
docker compose build --no-cache   # rebuild from scratch, ignoring cached layers
```

`docker-compose.yml` reads `backend/.env` and exposes the API on `localhost:8000`, same as running `uvicorn` directly.

### Why Docker is used here

At this stage, Docker's job is reproducibility and dependency isolation — not performance and not GPU access. It lets the exact same backend environment run identically on a developer's laptop, a teammate's laptop, a test environment, a server, and (later) a GPU server or ISRO/SAC infrastructure, without "works on my machine" drift. **Docker itself does not provide GPU acceleration** — that would need separate GPU-passthrough configuration when a real model workload exists.

Per current scope, there are **no** containers for Postgres, Redis, Celery, MinIO, AI models, GPU, Nginx, Prometheus, or Grafana — only the `api` service talking to Supabase Cloud.

## 15. Local development

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

The frontend runs separately (`npm run dev` at the repo root) and talks to the backend over HTTP via `VITE_API_BASE_URL` — the two are not coupled at build time.

## 16. Testing

```bash
cd backend
pytest -v
```

Tests use an in-memory fake Supabase client (`tests/fakes.py`, including a fake Storage bucket/object store) so they run without a live Supabase project or network access. Coverage: health (including database-down and bucket-missing cases), imagery CRUD + pagination, invalid UUIDs, real upload flow (`test_imagery_upload.py`: success, unsupported type, empty file, storage failure not creating a DB record, delete removing the Storage object, delete aborting when Storage delete fails), analysis creation (invalid `analysis_type`, missing imagery, empty/whitespace query), job retrieval, and result/evidence retrieval.

## 17. Frontend integration

See section 2 above for what's wired. `src/lib/apiClient.ts` exports `uploadImagery()`, `submitAnalysis()`, `getImagery()`, `listImagery()`, `deleteImagery()`, `getAnalysisJob()`, `getAnalysisHistory()`, `getResult()`, `getEvidence()`.

### Delete ordering (found via live testing against the real project)

`DELETE /api/v1/imagery/{id}` deletes the **database row first**, then the Storage object — the reverse of a naive "storage then DB" order, and deliberately so. `imagery.id` has an incoming foreign key from `analysis_jobs.imagery_id`; deleting an image that still has a job referencing it fails with a Postgres FK violation (`23503`) unrelated to Storage. Discovered this live: deleting a test image that had an analysis job attached failed the DB delete, and had the Storage object already been removed first, the DB record would have been left pointing at a file that no longer existed. With DB-first ordering, a blocked delete leaves both sides untouched and consistent. The only remaining edge case — DB delete succeeds but the subsequent Storage delete fails — orphans the Storage object; there's no cross-system transaction to roll back with, so this is logged loudly server-side (`imagery_service.delete_imagery`) and returned as an error rather than silently swallowed.

### History N+1 (found via live testing against the real project)

`list_history()` originally called `imagery_service.get_imagery()` once per job to resolve `imagery_name` (an N+1 pattern). Under concurrent load in the browser (the sidebar and the page-refresh restore path both fetch history on mount at once), this fired enough rapid requests through the shared Supabase client to intermittently trip a Cloudflare-level `400 Bad Request` in front of Supabase's REST API — a real failure only visible under actual concurrent usage, not in unit tests against the fake client. Fixed by batching: one `imagery.select("id,name").in_("id", [...])` call for all distinct `imagery_id`s in the page, instead of one call per row.

## 18. Current limitations

- No AI/model/agentic layer — `analysis_jobs` never progress past `status: "queued"`, and `/results` will 404 until something writes to `analysis_results` (nothing does yet).
- No authentication/authorization layer.
- `audit_logs` table exists in the schema but nothing writes to it yet.
- Upload/analysis errors from the frontend are only logged to the browser console (`console.error`) — there's no toast/banner component in the existing design system to surface them visually without adding new UI, so none was added.
- The pre-existing `ChangeDetection`, `FusionViewer`, `AgentPipeline`, `AnalyticsDashboard`, and `ReportScreen` components (reachable via the "Compare"/"Full Report" buttons and sidebar shortcuts) still render entirely from `SATELLITE_SCENARIOS` mock data — rebuilding them on real data would require either raster/change-detection analysis (explicitly out of scope) or removing them, and neither was requested by this milestone's endpoint list.
- Docker build was written and reviewed but could not be verified on this machine (Docker was not installed in this environment) — verify `docker compose build && docker compose up` locally before relying on it.

## 19. Future AI integration point

When an AI/agentic layer is ready, it should:
1. Poll or subscribe to `analysis_jobs` rows with `status = 'queued'`.
2. Set `status = 'processing'`, run inference, then write a row to `analysis_results` (and `evidence` if applicable).
3. Update the job with `status = 'completed'` (or `'failed'` + `error_message`), `result_id`, and `completed_at`.

The `/api/v1/analysis`, `/jobs/{id}`, `/results/{id}`, and `/results/{id}/evidence` contracts are designed to stay stable through that change — no frontend changes should be required beyond consuming non-null `answer`/`evidence` data once it exists.

**AI models and agentic orchestration are intentionally not implemented in this milestone.**
