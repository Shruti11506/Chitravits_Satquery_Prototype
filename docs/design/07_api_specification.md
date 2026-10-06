# API Specification

## 1. DOCUMENT CONTROL

| Attribute | Details |
| :--- | :--- |
| **Document ID** | SQ-DOC-007 |
| **Document Title** | API Specification |
| **Project** | SatQuery AI (Problem Statement 26167) |
| **Organization** | Indian Space Research Organisation (ISRO), Department of Space |
| **Team** | Chitravits |
| **Version** | 4.1.0 |
| **Date** | 6 October 2026 |
| **Audience** | Frontend developers, integration engineers, backend engineers, evaluators |

This specification documents the API **as implemented in the prototype repository** (`backend/app/api/routes/`). Planned additions from the target design are listed separately in Section 8 and are not yet available. The authoritative machine-readable schema is the OpenAPI document served by the API at `/docs` and `/openapi.json`.

---

## 2. API OVERVIEW

The API is built with FastAPI (Python 3.12). The web interface accesses it only through its API client (`src/lib/apiClient.ts`). Analysis requests are processed as jobs: the client creates a job, polls its status, then retrieves the result and its evidence.

### 2.1 Base URL

`{BASE_URL}/api/v1`

| Environment | Base URL |
|---|---|
| Local development | `http://localhost:8000/api/v1` (started together with the web interface) |
| Hosted | Address of the hosted API service, configured in the web interface (`VITE_API_BASE_URL`) |

The validation endpoints are also mounted under `/api/validation` for diagnostic use.

### 2.2 Versioning

URI-based versioning (`/api/v1`). New request fields are optional so that existing clients continue to work.

### 2.3 Authentication

Not implemented in the prototype. The system operates with a single workspace profile resolved by the server; no endpoint accepts a user identifier. The API accesses the database with a server-side key that is never sent to the client. Authentication and roles are planned (Section 8.4).

### 2.4 Response Envelope

```json
{ "success": true,  "data": { },   "error": null }
{ "success": false, "data": null, "error": { "code": "IMAGE_NOT_FOUND", "message": "...", "details": null } }
```

| Rule | Description |
|---|---|
| One code, one status | Each error code always maps to the same HTTP status |
| `error.details` | Structured context, used by the pair compatibility check on `POST /analysis` |
| Health endpoints | Return HTTP 200 with `success: false` and populated `data` when a dependency is unavailable |
| Reports | `POST /reports` returns a PDF document on success; errors use the envelope |
| Malformed requests | 422 `VALIDATION_ERROR` (including malformed UUIDs in paths) |
| Unhandled errors | 500 `INTERNAL_ERROR`, without internal details |

### 2.5 Cross-Origin Access and Rate Limiting

Cross-origin requests are accepted from the configured origins (`CORS_ORIGINS`) and the hosted interface domain; any local port is accepted in development. Rate limiting is not implemented (Section 8.4).

---

## 3. ENDPOINT SUMMARY

| Method | Path | Purpose | Success Status |
|---|---|---|---|
| GET | `/health` | Service availability | 200 |
| GET | `/health/supabase` | Database and storage connectivity | 200 |
| GET | `/health/storage` | Storage connectivity | 200 |
| POST | `/imagery/upload` | Upload one image | 201 |
| POST | `/imagery/pair` | Upload an image pair | 201 |
| POST | `/imagery` | Register metadata for a file already in storage | 201 |
| GET | `/imagery?page=&page_size=` | List imagery | 200 |
| GET | `/imagery/{imagery_id}` | Imagery record with signed URLs | 200 |
| DELETE | `/imagery/{imagery_id}` | Delete imagery record and stored files | 200 |
| POST | `/validation/validate` | Validate images for a declared workflow | 200 |
| POST | `/validation/change-detection` | Pair compatibility check | 200 |
| POST | `/analysis` | Create an analysis job | 201 |
| GET | `/analysis/history?limit=` | Analysis jobs with image names | 200 |
| GET | `/jobs/{job_id}` | Job status | 200 |
| GET | `/results/{result_id}` | Stored result | 200 |
| GET | `/results/{result_id}/evidence` | Stored evidence | 200 |
| POST | `/conversations` | Create a conversation | 201 |
| GET | `/conversations?limit=` | List conversations | 200 |
| GET | `/conversations/{conversation_id}` | Conversation with images and jobs | 200 |
| PATCH | `/conversations/{conversation_id}` | Rename | 200 |
| POST | `/conversations/{conversation_id}/title` | Generate the automatic title once | 200 |
| DELETE | `/conversations/{conversation_id}` | Delete conversation, jobs, images and files | 200 |
| PATCH | `/conversations/legacy/{imagery_id}` | Rename an earlier (pre-conversation) chat | 200 |
| DELETE | `/conversations/legacy/{imagery_id}` | Delete an earlier chat | 200 |
| GET | `/projects` | List projects with counts | 200 |
| POST | `/projects` | Create a project | 201 |
| GET | `/projects/{project_id}` | Project with chats and files | 200 |
| PATCH | `/projects/{project_id}` | Update a project | 200 |
| DELETE | `/projects/{project_id}` | Delete a project (chats retained) | 200 |
| POST | `/projects/{project_id}/files` | Upload a project file | 201 |
| DELETE | `/projects/{project_id}/files/{file_id}` | Delete a project file | 200 |
| GET | `/profile` | Profile and headline statistics | 200 |
| PATCH | `/profile` | Update profile fields | 200 |
| GET | `/profile/dashboard` | Complete analytics dashboard | 200 |
| GET | `/profile/activity`, `/profile/insights`, `/profile/features`, `/profile/recent-activity` | Dashboard sections | 200 |
| POST | `/profile/avatar` | Upload profile image | 200 |
| DELETE | `/profile/avatar` | Remove profile image | 200 |
| GET | `/settings` | User preferences | 200 |
| PATCH | `/settings` | Update preferences | 200 |
| POST | `/reports` | PDF report of a conversation | 200 |

---

## 4. ENDPOINT SPECIFICATIONS

### 4.1 Imagery

#### POST /api/v1/imagery/upload

Multipart form fields:

| Field | Required | Description |
|---|---|---|
| `file` | Yes | Image file (GeoTIFF, TIFF, PNG, JPEG, WEBP; up to 50 MB) |
| `name` | No | Display name |
| `source`, `sensor` | No | Used as sensor evidence by validation |
| `acquisition_date` | No | ISO 8601 timestamp |
| `metadata` | No | JSON object as a string |
| `conversation_id` | No | Owning conversation |

Processing: file validation; for TIFF files, raster inspection, WGS84 footprint and preview generation; storage of the unmodified original at `imagery/{uuid}/{filename}`; creation of the imagery record. If record creation fails, the stored files are removed.

Response (201):

```json
{
  "success": true,
  "data": {
    "id": "6f1c...",
    "name": "scene",
    "original_filename": "S2B_MSIL2A_example.tif",
    "bucket": "Satquery",
    "storage_path": "imagery/6f1c.../S2B_MSIL2A_example.tif",
    "mime_type": "image/tiff",
    "file_size": 26600000,
    "status": "registered",
    "thumbnail_url": "https://...",
    "latitude": 12.97,
    "longitude": 77.59,
    "bbox": {"west": 77.5, "south": 12.9, "east": 77.7, "north": 13.0, "crs": "EPSG:4326", "source_crs": "EPSG:32643"}
  },
  "error": null
}
```

Values are illustrative. Errors: 422 `UNSUPPORTED_FILE_TYPE`, `EMPTY_FILE`, `FILE_TOO_LARGE`, `FILE_TYPE_MISMATCH`, `FILE_CORRUPTED`, `UNSUPPORTED_DTYPE`, `RESOURCE_LIMIT_EXCEEDED`, `MISSING_FILENAME`, `INVALID_METADATA`; 500 `STORAGE_UPLOAD_FAILED`.

#### POST /api/v1/imagery/pair

Multipart form fields: `image_1` (reference, T1), `image_2` (comparison, T2), `conversation_id` (optional). Both files are validated before either is stored. The two records share a `pair_id`, with `pair_position` 1 and 2, and are inserted together.

```json
{"success": true, "data": {"pair_id": "...", "image_1": {}, "image_2": {}}, "error": null}
```

`image_1` and `image_2` have the same shape as the upload response. Errors: 422 `IMAGE_PAIR_INCOMPLETE` and the upload errors (prefixed "Image 1:" or "Image 2:"); 503 `SCHEMA_NOT_MIGRATED` if the pair migration has not been applied.

#### GET /api/v1/imagery/{imagery_id}

Returns the imagery record with a signed access URL valid for one hour and, for TIFF files, a preview URL (generated once for records created before previews were introduced). Error: 404 `IMAGE_NOT_FOUND`.

#### GET /api/v1/imagery

Query parameters: `page` (default 1), `page_size` (1 to 100, default 20).

#### DELETE /api/v1/imagery/{imagery_id}

Deletes the database record, then the original and preview files. If an analysis job references the image, deletion is refused and no data is changed.

### 4.2 Input Validation

#### POST /api/v1/validation/validate

Checks already-uploaded images against a declared workflow and reports all applicable issues.

```json
{
  "workflow": "ndvi",
  "images": [{"imagery_id": "...", "role": "single", "modality_hint": null}],
  "query": "optional free text, not parsed"
}
```

| Field | Values |
|---|---|
| `workflow` | `visual_vqa`, `scene_captioning`, `region_grounding`, `ndvi`, `bitemporal_change`, `optical_sar_analysis` |
| `role` | `single`, `t1`, `t2`, `optical`, `sar` |
| `modality_hint` | Optional; checked against file evidence, never trusted on its own |

A rejection is a successful HTTP response with the verdict in `data`:

```json
{
  "status": "REJECT",
  "valid": false,
  "errors": [{"code": "BAND_MISSING", "message": "...", "input": "<imagery_id>"}],
  "warnings": [],
  "inputs": []
}
```

#### POST /api/v1/validation/change-detection

Ordered compatibility check for a T1/T2 pair; stops at the first failure.

```json
{
  "t1_imagery_id": "...",
  "t2_imagery_id": "...",
  "profile": "chat",
  "aspect_ratio_tolerance": null,
  "require_exact_dimensions": null,
  "require_matching_format": null,
  "require_geospatial": null,
  "require_known_sensor": null
}
```

| Profile | Behaviour |
|---|---|
| `chat` (default) | Sensor evidence optional; geospatial checks only when an image is georeferenced; dimension and aspect-ratio checks applied |
| `strict` | Known sensor and georeferencing required |

The remaining fields override the selected profile. Check order: file T1, file T2, distinct images, sensor, modality, format, aspect ratio, dimensions, band count, band identity, band compatibility, geospatial T1, geospatial T2, CRS, data type.

```json
{
  "status": "REJECT",
  "valid": false,
  "workflow": "change_detection",
  "t1": {"label": "T1", "modality": "Multispectral", "format": "GeoTIFF", "width": 1024, "height": 1024, "bands": 12, "crs": "EPSG:32643"},
  "t2": {"label": "T2", "modality": "RGB", "format": "JPEG", "width": 1024, "height": 1024, "bands": 3, "crs": null},
  "errors": [{"code": "MODALITY_MISMATCH", "message": "...", "t1": "Multispectral", "t2": "RGB"}],
  "warnings": [],
  "checks": {"file_t1": true, "file_t2": true, "distinct_images": true, "sensor": true, "modality": false},
  "check_details": {"modality": {"status": "fail", "detail": "..."}, "format": {"status": "skipped", "detail": "not reached"}}
}
```

The response is abbreviated. `t1` or `t2` is `null` when that image could not be read.

### 4.3 Analysis and Jobs

#### POST /api/v1/analysis

```json
{
  "imagery_id": "...",
  "analysis_type": "general_analysis",
  "query": "What changed between these dates?",
  "conversation_id": "...",
  "comparison_imagery_id": "..."
}
```

| Field | Description |
|---|---|
| `imagery_id` | Required; the image, or Image 1 (T1) of a pair |
| `analysis_type` | Required: `vqa`, `captioning`, `scene_description`, `change_detection`, `change_vqa`, `optical_sar_analysis`, `region_grounding`, `general_analysis`. The web interface sends `general_analysis`, leaving task selection to the orchestrator |
| `query` | Required; up to 2000 characters |
| `conversation_id` | Optional |
| `comparison_imagery_id` | Optional; Image 2 (T2) of a pair |

Server-side checks, in order:

1. Non-empty query (`INVALID_QUERY`)
2. Image exists (`IMAGE_NOT_FOUND`)
3. Change analysis types require a comparison image (`IMAGE_COUNT_MISMATCH`)
4. The two images differ (`INVALID_IMAGE_PAIR`)
5. Any pair passes the change-detection compatibility check with the `chat` profile (422 with details)
6. Conversation exists (`CONVERSATION_NOT_FOUND`)
7. Job created with status `queued`

Response (201):

```json
{
  "success": true,
  "data": {
    "job_id": "...",
    "imagery_id": "...",
    "comparison_imagery_id": "...",
    "analysis_type": "general_analysis",
    "query": "...",
    "conversation_id": "...",
    "status": "queued"
  },
  "error": null
}
```

Pair rejection (422):

```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "MODALITY_MISMATCH",
    "message": "...",
    "details": {
      "valid": false,
      "status": "REJECTED",
      "workflow": "change_detection",
      "error_code": "MODALITY_MISMATCH",
      "details": {"t1": "Optical", "t2": "SAR"},
      "errors": [],
      "t1": {},
      "t2": {}
    }
  }
}
```

**Job processing:** on the main code line the job remains `queued`. On the agent integration line, when `AGENT_ENABLED` is set, the job is processed in the background by the SatQuery agent (EarthMind, MCD-Mamba, optional GeoGround) after the response is returned, and the result and evidence are stored.

**Known limitation:** every image pair passes the change-detection check, which rejects optical-SAR pairs as `MODALITY_MISMATCH`. A pair type is planned (Section 8.1).

#### GET /api/v1/jobs/{job_id}

```json
{
  "id": "...",
  "imagery_id": "...",
  "comparison_imagery_id": null,
  "conversation_id": "...",
  "analysis_type": "general_analysis",
  "query": "...",
  "status": "completed",
  "model_name": "earthmind-4b",
  "result_id": "...",
  "error_message": null,
  "created_at": "...",
  "started_at": "...",
  "completed_at": "..."
}
```

`status`: `queued`, `processing`, `completed`, `failed`, `cancelled`. On failure, `error_message` contains the reason. Error: 404 `JOB_NOT_FOUND`. The web interface polls this endpoint at 1.2-second intervals for up to two minutes.

#### GET /api/v1/analysis/history

Analysis jobs joined with image names, most recent first. Query parameter `limit` (1 to 200, default 50).

### 4.4 Results and Evidence

#### GET /api/v1/results/{result_id}

```json
{
  "id": "...",
  "job_id": "...",
  "answer": "The scene shows irrigated cropland with a river along the eastern edge.",
  "confidence": null,
  "model_name": "earthmind-4b",
  "analysis_type": "general_analysis",
  "raw_output": {
    "tool_selected": "earthmind",
    "output_files": [],
    "spatial_results": [],
    "measurements": [],
    "execution_trace": {"tool_execution_order": [{"tool_name": "earthmind", "status": "completed"}]}
  },
  "created_at": "..."
}
```

`confidence` is `null` when the model does not report one (EarthMind). `raw_output` holds the full agent response, including the execution trace. Error: 404 `RESULT_NOT_FOUND`.

#### GET /api/v1/results/{result_id}/evidence

```json
[
  {
    "id": "...",
    "result_id": "...",
    "evidence_type": "measurement",
    "description": "changed_area = 12.4 ha",
    "source_reference": "mcd_mamba",
    "bbox": null,
    "confidence": null,
    "metadata": {"name": "changed_area", "value": 12.4, "unit": "ha"},
    "created_at": "..."
  },
  {
    "id": "...",
    "result_id": "...",
    "evidence_type": "output_file",
    "description": "change_map produced by mcd_mamba",
    "source_reference": "mcd_mamba",
    "bbox": null,
    "confidence": null,
    "metadata": {"kind": "change_map", "url": "...", "media_type": "image/png"},
    "created_at": "..."
  }
]
```

| `evidence_type` | Source in the agent response |
|---|---|
| `claim` | Statements with their source tool |
| `change_region` | Spatial results: region, change type, area in hectares, box, confidence |
| `measurement` | Named measurements with value and unit |
| `output_file` | Model output images (overlays, change maps) with URL |

`source_reference` always identifies the producing tool. Values above are illustrative.

### 4.5 Conversations

| Endpoint | Behaviour |
|---|---|
| `POST /conversations` | Creates a conversation titled "New Chat". The web interface creates conversations on first upload |
| `GET /conversations` | Lists conversations with at least one image or job, most recently active first (`limit` 1 to 200, default 100) |
| `GET /conversations/{id}` | Conversation with its images (current signed URLs) and jobs, oldest first |
| `PATCH /conversations/{id}` | Rename; marks the title as user-defined (never overwritten automatically). Error: `INVALID_TITLE` |
| `POST /conversations/{id}/title` | Generates the title once from the first meaningful query using a deterministic keyword method |
| `DELETE /conversations/{id}` | Deletes jobs, images and stored files, then the conversation |
| `PATCH` / `DELETE /conversations/legacy/{imagery_id}` | Rename (converting to a conversation) or delete a chat created before conversations existed |

### 4.6 Projects

Projects group conversations and reference files. Listing returns chat and file counts; detail returns chats, project files and chat uploads; deleting a project removes its files but keeps its conversations. Errors: `PROJECT_NOT_FOUND`, `PROJECT_FILE_NOT_FOUND`, `INVALID_PROJECT_NAME`.

### 4.7 Profile and Settings

| Endpoint | Behaviour |
|---|---|
| `GET /profile/dashboard` | User, statistics (queries, scenes analysed, current and longest streak), a year of daily activity, insights, feature usage, remote sensing usage, recent activity; aggregated by a database function |
| `PATCH /profile` | Updates `display_name`, `username`, `headline`, `bio` (only fields sent). Errors: `INVALID_DISPLAY_NAME`, `INVALID_USERNAME`, `INVALID_HEADLINE`, `INVALID_BIO` |
| `POST` / `DELETE /profile/avatar` | JPG, PNG or WEBP up to 5 MB |
| `GET` / `PATCH /settings` | Theme (`dark`, `light`, `system`), sidebar density, notification and privacy flags, `language` (currently `en` only), defaults for data type and analysis task. Unknown fields rejected with 422 |

Endpoints that depend on an unapplied migration return 503 `SCHEMA_NOT_MIGRATED`.

### 4.8 Reports

#### POST /api/v1/reports

```json
{"conversation_id": "...", "imagery_id": null, "attached_model": "optional display name"}
```

Exactly one of `conversation_id` or `imagery_id` (for an earlier chat) is required (`REPORT_TARGET_REQUIRED`). Returns `application/pdf` with a `Content-Disposition` filename. The report contains only stored data: jobs without a result are marked "Result not available", and simulated in-browser model output is excluded.

### 4.9 Health

| Endpoint | Response |
|---|---|
| `GET /health` | `{"status": "healthy"}` |
| `GET /health/supabase` | `{"supabase": "connected", "database": "connected", "storage": "connected", "bucket": "Satquery"}`; degraded states return `success: false` with HTTP 200 |
| `GET /health/storage` | Storage-only check |

---

## 5. DATA MODELS

### 5.1 Imagery Record

| Field | Type | Description |
|---|---|---|
| `id` | UUID | Identifier |
| `conversation_id` | UUID, optional | Owning conversation |
| `name`, `source`, `sensor` | Text | Descriptive fields; `sensor` and `source` used as sensor evidence |
| `acquisition_date` | Timestamp, optional | Orders bi-temporal images |
| `original_filename`, `bucket`, `storage_path`, `mime_type`, `file_size` | Text, number | Stored original |
| `latitude`, `longitude`, `bbox` | Number, JSON | WGS84 footprint |
| `cloud_cover` | Number, optional | From file metadata only |
| `metadata` | JSON | Raster properties, preview information, file and pixel SHA-256 |
| `pair_id`, `pair_position` | UUID, integer | Pair membership (1 or 2) |
| `preview_path`, `preview_status` | Text | Preview location and status (`ready`, `failed`) |

### 5.2 Analysis Request

```json
{
  "type": "object",
  "properties": {
    "imagery_id": {"type": "string", "format": "uuid"},
    "analysis_type": {"enum": ["vqa", "captioning", "scene_description", "change_detection",
                               "change_vqa", "optical_sar_analysis", "region_grounding", "general_analysis"]},
    "query": {"type": "string", "maxLength": 2000},
    "conversation_id": {"type": ["string", "null"], "format": "uuid"},
    "comparison_imagery_id": {"type": ["string", "null"], "format": "uuid"}
  },
  "required": ["imagery_id", "analysis_type", "query"]
}
```

### 5.3 Job, Result and Evidence

| Model | Fields |
|---|---|
| Job | `id`, `imagery_id`, `comparison_imagery_id`, `conversation_id`, `analysis_type`, `query`, `status`, `model_name`, `result_id`, `error_message`, `created_at`, `started_at`, `completed_at` |
| Result | `id`, `job_id`, `answer`, `confidence`, `model_name`, `analysis_type`, `raw_output`, `created_at` |
| Evidence | `id`, `result_id`, `evidence_type`, `description`, `source_reference`, `bbox`, `confidence`, `metadata`, `created_at` |

### 5.4 Execution Trace

Stored in `raw_output` of the result. The SatQuery agent records `execution_trace.tool_execution_order` (tool name and status for each step). The in-repository LangGraph orchestrator records one entry per node (`validate_inputs`, `route`, `execute_step`, `compose_response`) with the input configuration, candidate tasks, basis of the routing decision, model and outcome. Internal model reasoning is not recorded.

---

## 6. ERROR CODES

### 6.1 HTTP Error Codes

| HTTP | Code | Raised By | Meaning |
|---|---|---|---|
| 422 | `VALIDATION_ERROR` | Framework | Malformed request or identifier |
| 422 | `INVALID_QUERY` | Analysis | Empty query |
| 422 | `IMAGE_COUNT_MISMATCH` | Analysis, validation | Wrong number of images for the request or workflow |
| 422 | `INVALID_IMAGE_PAIR` | Analysis | Same image submitted twice |
| 422 | `IMAGE_PAIR_INCOMPLETE` | Pair upload | A pair file is missing |
| 422 | `UNSUPPORTED_FILE_TYPE`, `EMPTY_FILE`, `FILE_TOO_LARGE`, `FILE_TYPE_MISMATCH`, `FILE_CORRUPTED`, `UNSUPPORTED_DTYPE`, `MISSING_FILENAME`, `INVALID_METADATA`, `RESOURCE_LIMIT_EXCEEDED` | Upload | File rejected; nothing stored |
| 422 | Validation codes (Section 6.2) | Pair check in `POST /analysis` | Incompatible pair; no job created |
| 422 | `INVALID_TITLE`, `INVALID_PROJECT_NAME`, `INVALID_DISPLAY_NAME`, `INVALID_USERNAME`, `INVALID_HEADLINE`, `INVALID_BIO`, `REPORT_TARGET_REQUIRED` | Resources | Field validation |
| 404 | `IMAGE_NOT_FOUND`, `JOB_NOT_FOUND`, `RESULT_NOT_FOUND`, `CONVERSATION_NOT_FOUND`, `CHAT_NOT_FOUND`, `PROJECT_NOT_FOUND`, `PROJECT_FILE_NOT_FOUND` | Resources | Unknown identifier |
| 500 | `SUPABASE_ERROR` | Services | Database error |
| 500 | `STORAGE_UPLOAD_FAILED` | Storage | Storage error |
| 500 | `INTERNAL_ERROR` | Application | Unhandled error |
| 503 | `SUPABASE_NOT_CONFIGURED` | Configuration | Database credentials missing or invalid |
| 503 | `SCHEMA_NOT_MIGRATED` | Services | Required migration not applied |

### 6.2 Validation Codes

Returned inside validation responses, or as the error code of a rejected analysis request:

`MODALITY_MISMATCH`, `BAND_MISMATCH`, `BAND_MISSING`, `ASPECT_RATIO_MISMATCH`, `IMAGE_DIMENSION_MISMATCH`, `FILE_FORMAT_MISMATCH`, `CRS_MISMATCH`, `CRS_MISSING`, `INVALID_CRS`, `GEOREFERENCE_MISSING`, `DTYPE_MISMATCH`, `NOT_DISTINCT_OBSERVATIONS`, `UNKNOWN_SENSOR`, `UNSUPPORTED_SENSOR`, `INVALID_DIMENSIONS`, `INVALID_IMAGE`, `IMAGE_UNAVAILABLE`, `WORKFLOW_INPUT_MISMATCH`, `UNKNOWN_WORKFLOW`. Warning: `SAME_ACQUISITION_TIME`.

### 6.3 Job Failure Codes

Recorded on the job (`error_message`), not returned as HTTP errors:

| Source | Codes |
|---|---|
| Orchestrator | `MODEL_NOT_AVAILABLE`, `MODEL_INPUT_INVALID`, `MODEL_EXECUTION_FAILED`, `INPUT_AMBIGUOUS`, `INCOMPATIBLE_REQUEST`, `UNSUPPORTED_INPUT`, `IMAGE_NOT_STORED`, `NO_IMAGES`, `NO_RESULT`, `INVALID_INPUT`, `INVALID_QUERY` |
| SatQuery agent | `ATTACHMENT_NOT_FOUND`, `ATTACHMENT_UNRESOLVABLE`, `INVALID_IMAGE`, `UNSUPPORTED_TASK` |

---

## 7. MODEL SERVICE PROTOCOL

Interface between the backend and GPU model services (reference implementation in the repository's AI integration code; used for EarthMind, MCD-Mamba and any external model).

```
GET  /v1/health
  -> {"ready": bool, "model_name": str, "model_version": str, "tasks": [...], "detail": str}

POST /v1/predict   multipart/form-data
  request = {
    "task": "vqa | captioning | region_grounding | optical_sar_analysis | change_detection",
    "query": str, "context": {}, "params": {},
    "images": [{"field": "image_0", "imagery_id": str, "role": "single | t1 | t2 | optical | sar",
                "modality": "optical | sar | unknown", "mime_type": str, "acquisition_date": str, "metadata": {}}]
  }
  image_0, image_1 = file contents

200 -> {"model_name", "model_version", "answer", "confidence", "outputs": {}, "evidence": [...]}
503 -> {"code": "MODEL_NOT_AVAILABLE"}    422 -> {"code": "MODEL_INPUT_INVALID"}    500 -> {"code": "MODEL_EXECUTION_FAILED"}
```

Masks are returned as PNG data in `outputs`; the backend stores them as files and removes embedded data before saving `raw_output`. Hosted agent services use an equivalent multipart `POST /predict` endpoint ("wrapper" protocol). Requests are authenticated with a per-service key.

| Configuration Setting | Purpose |
|---|---|
| `AGENT_ENABLED` | Enables background processing of analysis jobs |
| `AGENT_MODEL_PROTOCOL` | `wrapper` (hosted services) or `native` (development stubs) |
| `AGENT_EARTHMIND_URL`, `AGENT_MCD_MAMBA_URL`, `AGENT_GEOGROUND_URL` | Model service addresses |
| `AGENT_*_API_KEY` | Per-service credentials (server-side only) |
| `AGENT_MCD_MAMBA_ENABLED`, `AGENT_GEOGROUND_ENABLED` | Enable or disable optional services |

---

## 8. PLANNED ADDITIONS

The following come from the target design (`02_system_architecture.md`, `05_technical_design.md`) and are **not yet implemented**.

### 8.1 Analysis Extensions

| Addition | Purpose |
|---|---|
| `pair_type` (`temporal` or `optical_sar`) on `POST /imagery/pair` and `POST /analysis` | Validate optical-SAR pairs with the `optical_sar_analysis` workflow instead of the change-detection check |
| `aoi` (GeoJSON polygon) on `POST /analysis` | Restrict analysis to a drawn area of interest |
| Multi-step plan for `change_vqa` | MCD-Mamba change evidence followed by EarthMind explanation |
| `GET /analysis/{job_id}/trace` | Dedicated access to the execution trace |
| Evidence fields `parent_evidence_ids`, `parameters`, `tool_version` | Evidence provenance |
| `verification` block in results (`claims`, `supported`, `status`) and result status `VERIFIED`, `QUALIFIED`, `PARTIAL`, `FAILED` | Claim verification |
| `GET /results/{result_id}/overlays/{overlay_id}` | Overlay raster or GeoJSON for the map |
| GeoJSON format for `POST /reports` | Geospatial export |

### 8.2 Capability and Model Discovery

| Addition | Purpose |
|---|---|
| `GET /capabilities?imagery_ids=` | Tasks supported by the selected images, with reasons for unavailable tasks |
| `GET /models` | Registered models and tools with capabilities, input requirements, version and evaluation status |

### 8.3 Multilingual and External Data

| Addition | Purpose |
|---|---|
| `language` on `POST /analysis` (`auto` or a language code) | Query language; answer returned in that language |
| `answer_language`, `answer_en` in results | Translated answer alongside the verified English answer |
| Additional values for the `language` setting (beginning with `hi`) | User preference |
| `GET /languages` | Supported languages |
| `connectors` on `POST /analysis`; `GET /connectors` | External data sources permitted for a query |

### 8.4 Security

| Addition | Purpose |
|---|---|
| JWT bearer authentication; 401 `UNAUTHORIZED` | Protected deployments |
| Roles ISRO_ANALYST, NDRF_OFFICER, PUBLIC_RESEARCHER; 403 `FORBIDDEN` | Role-based access |
| Object-level authorisation on imagery, jobs, results and evidence | Protection against OLA / BOLA |
| Rate limits on upload and analysis; 429 `RATE_LIMITED` | Resource protection |
| Audit logging (table already present) | Security-sensitive actions |

### 8.5 Planned Error Codes

`REGISTRATION_FAILED`, `INSUFFICIENT_RESOLUTION`, `INSUFFICIENT_EVIDENCE`, `UNVERIFIED_CLAIM`, `UNSUPPORTED_LANGUAGE`, `TRANSLATION_FAILED`, `CONNECTOR_UNAVAILABLE`, `UNAUTHORIZED`, `FORBIDDEN`, `RATE_LIMITED`. These follow the repository naming convention; they correspond to the `ERR_*` codes of the original design (for example, `ERR_REGISTRATION_FAILED`).

### 8.6 Design-to-Repository Name Mapping

| Original Design Name | Repository Endpoint |
|---|---|
| `POST /assets` | `POST /imagery/upload`, `POST /imagery/pair` |
| `GET /assets/{asset_id}` | `GET /imagery/{imagery_id}` |
| `POST /assets/validate-pair` | `POST /validation/change-detection` |
| `POST /query` | `POST /analysis` |
| `GET /query/{id}/status` | `GET /jobs/{job_id}` |
| `GET /query/{id}/result` | `GET /results/{result_id}` |
| `GET /evidence/{evidence_id}` | `GET /results/{result_id}/evidence` |

---
*End of Document*
