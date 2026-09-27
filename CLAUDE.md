# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

For the full, evidence-backed audit (feature inventory, bug table, dummy-data locations, production readiness, roadmap), see [PROJECT_STATUS.md](PROJECT_STATUS.md). Backend setup and endpoint reference: [backend/README.md](backend/README.md). The root [README.md](README.md) is the first-time setup guide for a fresh clone (`npm install` → `npm run setup` → fill `backend/.env` → `npm run dev`).

> **AI layer / ML model integration in progress:** read [docs/ai-integration/HANDOFF.md](docs/ai-integration/HANDOFF.md) FIRST — current state, the two models (EarthMind, MCD-Mamba), the backend↔model-server protocol, and the ordered task list. Draft reference code is in `docs/ai-integration/reference/` (adapt, don't paste blindly).

## Commands

```bash
# Frontend (repo root)
npm run dev       # Vite dev server, http://localhost:5173 — ALSO starts the FastAPI backend on :8000
                  # (vite.config.js `satqueryBackend` plugin; reuses one already on :8000; stops with Vite;
                  # no --reload, so restart `npm run dev` after backend edits; opt out: SATQUERY_SKIP_BACKEND=1)
npm run build     # production build -> dist/ (does NOT type-check .tsx; there is no tsc step)
npm run preview   # preview the production build
npm run lint      # oxlint (.oxlintrc.json); ~63 pre-existing warnings, mostly unused imports
```

There is no frontend test suite and no CI.

```bash
# Backend
cd backend
python -m venv .venv && .venv\Scripts\activate           # first time (Windows; source .venv/bin/activate elsewhere)
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000                  # http://localhost:8000/docs
pytest -v                                                  # 325 tests + test_orchestrator.py (needs langgraph in the venv), in-memory fake Supabase (incl. an rpc() mirror of profile_dashboard), no network
pytest tests/test_imagery_upload.py::test_upload_imagery_success -v   # single test
docker compose up --build                                  # UNVERIFIED: never successfully run on this machine
```

The frontend calls `http://localhost:8000/api/v1` by default, so the backend must be running for uploads/history to work — the UI then shows honest errors, not fake data. The backend has repeatedly been left stopped between sessions, which looks exactly like "upload is broken"; check port 8000 first. Also check that it's running **current** code: a uvicorn started without `--reload` keeps serving the code it started with, and new routes then 404 (this caused the "Unable to load conversation history" regression). Compare `GET /openapi.json` against `backend/app/api/routes/`. **Schema changes need a manual migration:** new code against an unmigrated database fails with `SUPABASE_ERROR` (PostgREST `PGRST205` = missing table, `42703` = missing column in the server log). `pytest` won't catch this because it uses a fake DB.

**"Unable to load conversation history." — diagnose in this order** (all of these have happened). The sidebar now prints the reason under that line (`BACKEND_UNREACHABLE` from `apiClient.request`, or the backend's own error), and `npm run dev` prints a boxed `[satquery]` warning when `backend/.venv` or `backend/.env` is missing. **Fresh clone on another machine:** no venv (backend never starts) and no `backend/.env` (gitignored) — `npm run setup` + fill `SUPABASE_URL`/`SUPABASE_SECRET_KEY`; a publishable/anon key there is refused with 503 `SUPABASE_NOT_CONFIGURED` (`db/supabase.py::supabase_config_problem`) because RLS would otherwise make every table read as empty:
1. **Which origin is the page on?** `npm run dev` silently moves to `5174`, `5175`, … when `5173` is taken, and several stale Vite servers from this folder can be running at once (`Get-NetTCPConnection -State Listen` → ports 5173+). A browser origin the backend doesn't allow gets `OPTIONS … 400 "Disallowed CORS origin"` and every API call fails with `TypeError: Failed to fetch`. Fixed for development: when `APP_ENV=development`, `core/config.py::cors_origin_regex` also allows any `http://localhost|127.0.0.1|[::1]:<port>`. Production uses only the explicit `CORS_ORIGINS` list.
2. **Is the backend up and on current code?** (see above). This was the cause after every machine/session restart (confirmed three times): the data was safe in Supabase, but `npm run dev` (and `.claude/launch.json`, which runs it) started only Vite, so nothing started uvicorn. Symptom: `ERR_CONNECTION_REFUSED` on `:8000`, no python process. Fixed: `npm run dev` now starts the backend too (see Commands); if it can't (no `backend/.venv`), Vite's log says `[satquery] backend NOT started`. Fixed: the backend used to load `.env` relative to the working directory, so a uvicorn started outside `backend/` (e.g. from the repo root) ran with no Supabase credentials and history returned 500 "Supabase is not configured". `core/config.py` now anchors it to `backend/.env` (`tests/test_config.py`).
3. **Is the schema migrated?** (see above).
4. Transient: Supabase drops the pooled HTTP/2 connection after idle (`httpx.RemoteProtocolError: Server disconnected`). Sidebar reads go through `db/supabase.py::execute_read`, which retries a read once — use it for new read paths too; never for writes.

**Running the backend detached (background, no console) on Windows: don't use `--reload`.** uvicorn's Windows reloader restarts the worker with `CTRL_C_EVENT`, which a console-less process never receives, so it logs "Reloading..." and keeps serving the OLD code indefinitely. Restart it explicitly after backend edits and confirm via `/openapi.json` or a behaviour check. `--reload` in an interactive terminal is fine.

## Tech stack (currently used)

- **Frontend:** React 19, Vite 8, Tailwind CSS 4, Radix/shadcn-style UI primitives, framer-motion, lucide-react, oxlint. Mixed `.jsx`/`.tsx`, `tsconfig` has `strict: false`.
- **Backend:** Python 3.12, FastAPI, Uvicorn, Pydantic v2 + pydantic-settings, python-multipart, supabase-py (PostgREST table API + storage3). No ORM, no raw SQL.
- **Data:** Supabase PostgreSQL + Supabase Storage (private bucket `Satquery`).
- **Tests:** pytest with `backend/tests/fakes.py` (fake DB + fake Storage).
- **Not present:** authentication, AI/ML (intentionally pending), queues/workers, Redis, Nginx, CI, deployment config.

## Architecture

SatQuery AI is a React + Vite frontend backed by a separate FastAPI service ([backend/](backend/), `Existing UI → FastAPI → Supabase`). The frontend never talks to Supabase directly. The upload → query → history flow is **fully backend-driven and real** — no hardcoded chat history, no fabricated AI analysis text, nothing invented client-side. There is still **no AI/model layer anywhere** (explicitly out of scope): a submitted query creates an `analysis_jobs` row that stays `status: "queued"` with `model_name = NULL` until a future milestone adds real processing. `analysis_results` and `evidence` are empty by design.

### Project layout

```text
src/App.jsx                 screen routing + real session state + refresh restore
src/lib/apiClient.ts        the ONLY frontend→backend access point
src/components/             LandingHero, Workspace, UserHistorySidebar, ProfileDashboard (+ .css), ImageViewer (primary flow)
                            ChangeDetection, FusionViewer, AgentPipeline, AnalyticsDashboard, ReportScreen (legacy mock screens)
src/components/ui/          shadcn primitives, logo, animated background
src/data/mockData.js        SATELLITE_SCENARIOS (legacy screens only) + SUGGESTED_QUERIES (UI chips)
backend/app/main.py         app init, CORS, exception handlers, routers under /api/v1
backend/app/api/routes/     health, imagery, analysis, jobs, results, evidence (thin)
backend/app/services/       imagery_, analysis_, job_, result_, storage_, raster_service (all logic)
backend/app/schemas/        Pydantic models incl. the ApiResponse envelope (common.py)
backend/app/db/supabase.py  single cached Supabase client (service-role key)
backend/app/core/           config (env), exceptions, logging, security
backend/app/orchestrator/   LangGraph graph: validate_inputs → route → execute_step (loop) → compose_response
backend/app/ml/             ModelService contract (contracts.py) + ModelRegistry (registry.py); specialists go in ml/services/
backend/app/validation/     Input Validation gate (file/raster/geospatial/modality/band/workflow/AOI/limits) -- storage-agnostic, own schemas.py/errors.py
                            + change_detection_validator.py/dimension_validator.py: strict, order-stopping T1/T2 pair check (POST /validation/change-detection)
backend/supabase/           schema.sql (fresh project) + migrations/ (applied manually in the SQL editor)
```

Dead code (unreachable from `src/main.jsx`; don't build on it): `src/components/Navbar.jsx`, `demo.tsx`, `blocks/*`, `ui/demo.tsx`, `ui/git-hub-sky.tsx`, `ui/github-sky-demo.tsx`, `ui/label.tsx`, `ui/nav-header.tsx`. The `viewer` screen is only reachable from the dead `Navbar.jsx`. `backend/app/core/security.py::parse_uuid` is unused.

### Screen routing (no router library)

[App.jsx](src/App.jsx) is the single source of navigation truth. It holds `activeScreen` state (a string id) and a `historyStack` array used for step-by-step "Back" navigation, and conditionally renders one of the screen components based on `activeScreen`:

- `landing` → [LandingHero.jsx](src/components/LandingHero.jsx) — real upload entry point (drag-drop or browse)
- `workspace` → [Workspace.jsx](src/components/Workspace.jsx) — main chat + image viewer, backend-driven
- `settings` → [SettingsPage.jsx](src/components/SettingsPage.jsx) — Profile / App Preferences / Notifications / Account & Privacy, from `GET /settings` held in `App.settingsState`; selects and toggles save immediately (optimistic, reverted on failure), profile uses the existing `/profile` endpoints with a Save button. Opened from the sidebar's "Settings & Appearance" and the profile menu's "Settings"; reopens on refresh.
- `profile` → [ProfileDashboard.jsx](src/components/ProfileDashboard.jsx) — profile/analytics page from `GET /profile/dashboard` (one request) with an Edit Profile dialog; opened from the sidebar footer menu's "Profile" item. `localStorage['satquery-last-screen'] = 'profile'` reopens it on refresh.
- `viewer` → [ImageViewer.jsx](src/components/ImageViewer.jsx) (effectively unreachable, see above)
- `change` / `fusion` / `pipeline` / `analytics` / `report` → [ChangeDetection.jsx](src/components/ChangeDetection.jsx) / [FusionViewer.jsx](src/components/FusionViewer.jsx) / [AgentPipeline.jsx](src/components/AgentPipeline.jsx) / [AnalyticsDashboard.jsx](src/components/AnalyticsDashboard.jsx) / [ReportScreen.jsx](src/components/ReportScreen.jsx) — **pre-existing demo screens, out of scope for the backend-persistence milestone**, still rendering entirely from `SATELLITE_SCENARIOS` mock data. Reachable via the "Compare"/"Full Report" buttons in Workspace's header and several sidebar shortcuts (Images, Plugins, Deep research, See plans and pricing, Help & Mission Guide).

Screens navigate via callback props (`onNavigateScreen`, `onGoBack`) passed down from `App`, not via URL changes — there's no `react-router`. There is no natural-language redirection (typing "report"/"compare" goes through the same real `/api/v1/analysis` flow as any query).

### Real upload → query → history flow

- [src/lib/apiClient.ts](src/lib/apiClient.ts) — typed client for every backend endpoint, including `uploadImagery()`, `submitAnalysis()`, `getAnalysisHistory()`. It must not set `Content-Type` for `FormData` (the browser sets the multipart boundary). Its file-header comment is stale (mentions a removed mock chat).
- [LandingHero.jsx](src/components/LandingHero.jsx)'s `processFile()` uploads the selected file via `POST /api/v1/imagery/upload` (real bytes → Supabase Storage bucket `Satquery` → an `imagery` row) during its existing "Parsing GeoTIFF Metadata..." loading state.
- `App.handleStartAnalysis` awaits `submitAnalysis()` before navigating into Workspace, so the chat opens already showing the real **"Analysis request submitted." / status: queued** acknowledgment (or an honest error) — never fabricated analysis text.
- [Workspace.jsx](src/components/Workspace.jsx)'s `handleSendMessage` does the same for a mid-chat query against `backendImageryId` — the chat's most recent upload, kept across messages so follow-ups target the same image. Sending waits for a pending attachment's upload to settle.
- **Conversations** (`conversations` table, migration `0003`): the sidebar lists conversations, not files. **New Chat** (sidebar button, header logo, "New Analysis") only resets frontend state (`App.handleNewChat`: `activeConversation = null`, clears the workspace, remounts `LandingHero` via `landingKey`) and **never writes to the backend**. The conversation row is created lazily by the first upload (`startConversation` on landing, `ensureConversation` mid-chat); concurrent callers share one in-flight `pendingConversationRef` promise, so one chat never gets two records. The sidebar refreshes after the upload lands (`onImageryUploaded`), and `GET /conversations` hides conversations with no imagery and no jobs (the brief window before the upload stores, a failed first upload, or blanks left by the old eager New Chat — purge with `backend/scripts/purge_empty_conversations.py`, dry run unless `--apply`). Reopening/restoring an **empty** conversation lands on the upload screen and the next upload reuses it (`freshConversationIdRef`). A query can't create a conversation on its own: analysis requires an uploaded image, which already created it. App load never creates a conversation. Uploads and queries carry `conversation_id`. Title rules: starts as "New Chat" (`title_source: default`); uploads never change it; after each successful query `App.handleQuerySubmitted` fires `POST /conversations/{id}/title` in the background, which titles it ONCE from the first meaningful stored query (`auto`) via the deterministic keyword matcher `backend/app/services/title_service.py` (no AI — swap that one function when a model exists); a manual rename sets `user` and is never overwritten. Filenames must never become titles.
- [UserHistorySidebar.tsx](src/components/UserHistorySidebar.tsx) fetches `GET /conversations` + `GET /analysis/history` on mount and on every `refreshToken` bump. Jobs with `conversation_id = NULL` are **legacy** (pre-conversation) chats: shown one per image, titled by their first query, read-only, opened via `App.handleSelectHistoryItem`. Conversations get a hover ⋯ menu (Rename inline / Delete with confirm — deletes its jobs, imagery rows and Storage files). Empty → "No conversations yet.", failure → "Unable to load conversation history." + Retry (re-runs the same two GETs; creates nothing); never sample data. The sidebar renders **only** backend rows — there is no frontend-only "New Chat" placeholder (it was removed because it duplicated the real record New Chat creates); the open conversation is highlighted on both the landing and workspace screens.
- Refresh persistence: `localStorage['satquery-last-conversation-id']` (or, for legacy chats, `satquery-last-imagery-id`) holds only a pointer — on mount `App.jsx` re-fetches from the backend (`buildConversationScenario()` / `buildLegacyScenario()`); a stale pointer is cleared.
- An upload with no typed query submits nothing (no default query is invented); the chat waits for the user's first question.
- **Image pairs** (migration `0006`): LandingHero's **Single Image / Image Pair** toggle (Single is the unchanged default). Pair mode has two slots, Image 1 · Reference and Image 2 · Comparison, each with Remove; validation is client-side (`filePreview.validateSatelliteFile`, "Please upload both images.") and again on the server. Analyze sends both in ONE `POST /imagery/pair` (fields `image_1`, `image_2`, `conversation_id`): the backend validates both before storing anything, stores two independent objects at the usual `imagery/{uuid}/{filename}`, inserts both rows in one insert (`imagery.pair_id` shared, `pair_position` 1/2), and removes what it uploaded if Image 2 or the insert fails — never a half pair. A failed pair upload keeps the user on the landing screen with both files selected. The chat attachment is `filePreview.makePairAttachment()`: top-level `imageryId`/`previewUrl`/`geo` are Image 1 (so single-image code paths still work), `comparisonImageryId` is Image 2, and `images` renders the two-row pair bubble. A query against a pair goes through the **change-detection compatibility gate** first (`analysis_service._reject_incompatible_pair`, `app/validation/change_detection_validator.py`, `ChangeDetectionRequirements()` defaults) — an incompatible pair (different modality, mismatched bands/dimensions/aspect-ratio/CRS/format) is rejected 422 with the failing code and a `error.details.{t1,t2}` summary the frontend renders as an "Invalid Input" chat card (`apiClient.formatChangeDetectionError`, used in both `App.handleStartAnalysis` and `Workspace.jsx`'s send handler); **no `analysis_jobs` row is created**. Only a compatible pair stores `analysis_jobs.imagery_id` = Image 1 and `comparison_imagery_id` = Image 2 (Workspace keeps both across follow-ups; attaching a single image mid-chat replaces the pair). Restore regroups rows by `pair_id` (`App.attachmentForImageryRow`). Single uploads/queries never write the new columns, so they work on an unmigrated DB; pair calls there fail with 503 `SCHEMA_NOT_MIGRATED`. No AI runs: pair jobs stay `queued`.
- **Settings** (migration `0005`, `user_settings`, one row per profile, created lazily with defaults): theme (`dark`/`light`/`system`) and sidebar density are applied by `App.jsx` (`data-theme` / `data-sidebar-density` on `<html>`; compact rules at the end of `index.css`); the header sun/moon toggle saves the theme too. `localStorage` keeps only a copy for the first paint. Notification/privacy toggles and the default data type / analysis task are stored only — nothing sends notifications, and no screen offers a per-analysis data type/task choice yet, so the defaults are not applied to queries. Sign Out and Delete Account are shown but unavailable (no auth).
- **Profile / identity** (migration `0004`): no login — the SIH prototype has ONE workspace profile (`profiles`, singleton index), resolved server-side by `profile_service.get_current_profile`; routes never take a user id, and all conversations/imagery/jobs belong to it. The sidebar footer shows it (`App.profileUser`, from `GET /profile`), or a neutral "Profile" if unavailable — never a placeholder name. Analytics are aggregated in Postgres by `profile_dashboard()` (one RPC); task/data-type labels come from `services/usage_classifier.py` (keywords, not a model). Real multi-user auth later = `user_id` columns + `auth.uid()` policies + swap `get_current_profile`.
- `SUGGESTED_QUERIES` (landing chips) and `QUICK_SUGGESTIONS` (Workspace pills) are legitimate static UI copy — clicking them submits through the real flow.

### Theming

Dual dark/light theme toggled via a `data-theme` attribute on `<html>`, persisted to `localStorage` under `satquery-theme` (state lives in `App.jsx`). Two systems coexist in [src/index.css](src/index.css):
- shadcn/Tailwind CSS variables (`--background`, `--primary`, `--sidebar-*`, etc.) scoped under `:root` / `.dark, [data-theme="dark"]`, used by the `ui/` (shadcn) components.
- A separate hand-rolled design-token system (`--space-*`, `--radius-*`, `--font-*`, `--accent`, etc.) used by the custom screen components' inline styles and [App.css](src/App.css).

`GradientBackground` ([oceanic-shimmer.tsx](src/components/ui/oceanic-shimmer.tsx)) renders both a `dark-blue` and `light-white` animated background simultaneously, cross-fading opacity based on `theme` — not conditionally mounted/unmounted.

### Component conventions

- `.jsx` files are the hand-written screen components (top-level pages); `.tsx` files under `src/components/ui/` are shadcn/ui primitives plus a few bespoke `.tsx` components (`UserHistorySidebar`, `ChitravitsLogo`, `oceanic-shimmer`). Both coexist — this is not a strict TS migration.
- Path alias `@/*` → `src/*` (configured in both [vite.config.js](vite.config.js) and [tsconfig.json](tsconfig.json)) — use it for new imports.
- The sidebar system ([components/ui/sidebar.tsx](src/components/ui/sidebar.tsx)) is shadcn's composable `Sidebar`/`SidebarProvider`/`SidebarTrigger`/`SidebarInset` primitives; [UserHistorySidebar.tsx](src/components/UserHistorySidebar.tsx) is the app-specific instance, grouped Today / Yesterday / Previous 7 Days / Previous 30 Days / Older, computed client-side from each conversation's real `updated_at`.
- `cn()` in [src/lib/utils.ts](src/lib/utils.ts) (`clsx` + `tailwind-merge`) is the standard class-merging helper used throughout `ui/` components.

## Backend

[backend/](backend/) is a separate FastAPI service — see [backend/README.md](backend/README.md) for full setup. Routes stay thin; logic lives in `backend/app/services/`, which is the only layer that talks to `backend/app/db/supabase.py`. Uses the existing, private Supabase Storage bucket **`Satquery`** (never `satquery-data` — that name doesn't exist; the backend never creates a bucket).

### API conventions

- All routes live under `/api/v1`. Every response uses the envelope `{"success", "data", "error": {"code", "message", "details"} | null}` from `schemas/common.py` (`ApiResponse.ok(...)` / `ApiResponse.fail(...)`). `error.details` is optional structured context beyond one message (`dict | None`, `None` for almost every error) — currently only the change-detection gate on `POST /analysis` uses it, to carry the full failed-checks list + T1/T2 summary the frontend renders (`apiClient.formatChangeDetectionError`). Exception: `/health/*` return `success: false` with populated `data` — and HTTP 200 — when unhealthy.
- Services signal errors by raising `core/exceptions.py` subclasses, never `HTTPException`: `NotFoundError` (404), `ValidationAppError` (422, optional `details=`), `SupabaseError` (500, `SUPABASE_ERROR`), `StorageError` (500, overridable code). `main.py` maps them to the envelope; unhandled exceptions become `INTERNAL_ERROR` with no traceback.
- Use specific `SCREAMING_SNAKE` error codes (existing: `IMAGE_NOT_FOUND`, `JOB_NOT_FOUND`, `RESULT_NOT_FOUND`, `INVALID_QUERY`, `UNSUPPORTED_FILE_TYPE`, `EMPTY_FILE`, `FILE_TOO_LARGE`, `INVALID_METADATA`, `STORAGE_UPLOAD_FAILED`, …). A given code always maps to one HTTP status.
- Path IDs are typed `UUID` so FastAPI rejects malformed IDs with 422 `VALIDATION_ERROR`.
- New route checklist: schema in `schemas/`, logic in a service, thin route, register the router in `main.py`, test in `backend/tests/` using the `client`/`fake_supabase` fixtures. If the route module calls `get_supabase()` directly, add a monkeypatch for it in `tests/conftest.py` (it patches per-module references).

### Database & storage notes

- Tables: `profiles` (single row), `user_settings` (one per profile), `conversations`, `imagery` (nullable `pair_id` + `pair_position` for image pairs; `preview_path` + `preview_status` for TIFF previews), `analysis_jobs` (FK `imagery_id` → `imagery.id`, enforced; nullable FK `comparison_imagery_id` → `imagery.id` for pair queries; both tables have nullable `conversation_id` → `conversations.id`), `analysis_results`, `evidence`, `audit_logs` (never written). Schema source of truth: `backend/supabase/schema.sql`; changes go in a new numbered file under `backend/supabase/migrations/` and are applied **manually** in the Supabase SQL editor — there is no migration runner, and the app has no way to run DDL.
- **RLS is enabled on all tables** by migration `0004` with no policies, so the anon/publishable key reads nothing (verified); `profile_dashboard()` is executable by `service_role` only. The backend uses the service-role key, which bypasses RLS. A new table needs `enable row level security` too.
- Uploads: `imagery/{uuid4}/{original filename}`; DB row only after a successful Storage upload; delete is DB-row-first then Storage object (the `analysis_jobs` FK can block the DB delete, and Storage-first would orphan the row). Private bucket → `GET /imagery/{id}` returns a fresh 1-hour signed `url`.
- TIFF/GeoTIFF uploads (`services/raster_service.py`, rasterio -- its wheel bundles GDAL/PROJ, no system packages): parsed in a worker thread BEFORE the Storage upload; the row gets real `latitude`/`longitude` (scene centre) and `bbox` (`{west,south,east,north,crs:"EPSG:4326",source_crs}`) reprojected from the file's CRS, `cloud_cover` only from a real metadata tag. A PNG preview (long edge ≤ 1600, read decimated so big rasters aren't decoded at full size; 2–98 % stretch for non-8-bit; nodata transparent; `mode` true_color only when bands really are R/G/B — else palette / grayscale / band_composite) is stored at `imagery/{uuid}/thumbnail.png` BEFORE the row insert, and the row records it (migration `0007`): `preview_path` + `preview_status` (`ready` / `failed`, NULL for non-TIFF). What the file is (size, bands, dtype, CRS, transform, bounds, nodata, colour interpretation), how the preview was composed, and `preview_error` go in `metadata.raster`. The original at `storage_path` is never modified. If the insert fails, the original and preview this request stored are removed. Unreadable file → upload still 201 with `preview_status: failed`; no CRS → preview still made, coordinates null. **Older TIFF rows** (`preview_status` NULL — stored before 0007, or by a backend without the pipeline, e.g. a deploy on older code sharing this Supabase) get their preview generated ONCE on first open (`imagery_service.resolve_thumbnail_url` → `ensure_preview`: reuse an existing thumbnail.png, else download the original read-only, render, store) and the outcome is written back — never regenerated; a transient Storage error records nothing and retries. Without 0007 the backend falls back to signing the conventional path. `thumbnail_url` (upload response, `GET /imagery/{id}`, conversation detail) is the signed preview_path. Delete also removes the preview. Frontend: `filePreview.getImageryPreviewUrl()` (thumbnail → browser-decodable original → placeholder, never the raw .tif URL) and `getImageryGeo()` feed ImageViewer's HUD.
- `MAX_UPLOAD_SIZE_MB=50` mirrors Supabase's platform default; the project's real limit is a dashboard setting not visible via the API.

### Environment

`backend/.env` (template `backend/.env.example`, gitignored): `SUPABASE_URL`, `SUPABASE_SECRET_KEY` (service role, backend only), `SUPABASE_PUBLISHABLE_KEY` (loaded but unused), `SUPABASE_STORAGE_BUCKET` (default `Satquery`), `MAX_UPLOAD_SIZE_MB` (default 50), `CORS_ORIGINS` (default `http://localhost:3000,http://localhost:5173`), `APP_ENV`, `APP_NAME`, `APP_VERSION`. Frontend: optional root `.env` with `VITE_API_BASE_URL` (none exists; the client defaults to `http://localhost:8000/api/v1`). Never put Supabase keys in `VITE_*` variables. Never print `.env` values.

## Rules for this repo

- **AI layer boundaries.** LangGraph orchestration lives in `backend/app/orchestrator/` (no model or DB code there); the model contract + registry live in `backend/app/ml/` (no torch/HF imports in `contracts.py`/`registry.py`). The registry is empty until a real model is integrated — tasks then fail with `MODEL_NOT_AVAILABLE`; never register a placeholder that returns text. No LangChain APIs (langchain-core is only a transitive LangGraph dependency). No fake answers: answers, confidences and evidence come only from a `ModelResponse`. The API still only creates `queued` jobs; nothing runs the graph yet (worker = next step).
- **Input Validation boundaries** (`backend/app/validation/`, `POST /validation/validate` and `POST /validation/change-detection`). Answers only "is this input structurally/semantically valid for the requested workflow" — never NDVI/change-detection/registration/resampling/tiling, never an AI/model call, never LangChain/LangGraph/agentic logic. Its own package, storage-agnostic (Supabase only meets it at `imagery_service.build_validation_image`); modality/band identity comes from the raster's real structure or an explicit hint, never a filename. Workflows are declarative (`workflow_validator.WORKFLOW_REGISTRY`) — add a new one there, don't scatter `if/else`. `/validation/change-detection` is a second, purpose-built T1/T2 endpoint (own `ChangeDetectionRequirements`/`ChangeDetectionIssue` shapes in `schemas.py`) that stops at the FIRST failing check, in a fixed order, rather than collecting every issue like the generic endpoint — its own docstring explains the two places it deliberately reorders the brief's own numbered steps and why. See `backend/app/validation/__init__.py` for the full scope and pipeline.
- **No fabricated application data** in the primary flow — backend data, an empty state, or a real error; never a fallback to sample data. Static UI copy (headings, placeholders, suggestion chips) is fine.
- **Never log secrets.** `core/logging.py` silences `httpx`, `httpcore`, `hpack` and `h2`, which print request headers (incl. the service-role key) at DEBUG; `tests/test_logging.py` guards this. Keep it that way when adding HTTP libraries.
- **Theme Transition is PERMANENTLY LOCKED — DO NOT MODIFY.** Under no circumstances should `src/lib/themeTransition.js`, `src/components/ui/ThemeTransitionPattern.jsx`, or the satellite orbital animation styles in `src/index.css` (1600ms, `cubic-bezier(0.32, 0, 0.2, 1)`, View Transitions API circular reveal, and Top Layer dialog overlay) be changed or redesigned. The user has explicitly frozen this implementation.
- Don't redesign the UI; functional changes only.
- Don't delete or recreate Supabase tables/buckets, and don't delete user rows/objects (real user data exists) — clean up only test data you created.

## Known issues / TODO (details and file:line references in PROJECT_STATUS.md §20–21)

1. The service-role key was written to plaintext DEBUG logs before the `hpack` logging fix — rotate it as a precaution.
2. ~~RLS disabled~~ — enabled by migration 0004.
3. ~~TIFF previews~~ — server-side thumbnails + real coordinates (see Database & storage notes). TIFFs uploaded before this, or unparseable ones, show the honest "Preview unavailable" placeholder. Thumbnails of small rasters (e.g. 120 px BigEarthNet patches) are not upscaled, so they render small in the viewer.
4. `ImageViewer` overlays fabricated Bengaluru coordinates/elevation/scale and CSS "NDWI/SAR" filters on real uploads.
5. No auth (by design for the SIH demo): one workspace profile, history is global. The old hardcoded "Shruti Daware" footer is gone.
6. ~~No compensating Storage delete~~ — a failed insert now removes the original (and preview) the upload just stored, for single and pair uploads.
7. Docker never verified (daemon not running on this machine).
8. Legacy mock screens still reachable from the real flow.
