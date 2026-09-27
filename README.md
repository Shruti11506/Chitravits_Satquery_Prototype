# SatQuery AI

Enterprise remote sensing vision-language intelligence platform for multi-sensor satellite imagery (Optical, Multispectral, and SAR).

Combines a React + Vite frontend (Tailwind/Vanilla CSS aerospace dark theme) and a high-performance FastAPI backend integrated with **Supabase** (PostgreSQL + Storage) and **Rasterio/GDAL** for server-side geospatial raster inspection.

```
Browser → Frontend (Vite, :5173/:5174) → FastAPI Backend (:8000) → Supabase Cloud (PostgreSQL + Storage)
```

Every developer runs the frontend **and** the backend on their own computer, and every backend connects to the **same Supabase project** — synchronizing conversations, assets, projects, and analysis jobs. The frontend communicates exclusively with the FastAPI backend and never exposes Supabase keys.

---

## Key Features

### 1. Multi-Sensor Satellite Imagery Ingestion
- **GeoTIFF / TIFF / PNG / JPEG support**: Handles true multispectral and SAR satellite rasters as well as standard RGB images.
- **Server-Side Raster Inspection**: Uses Rasterio and GDAL to extract real raster metadata: driver format, width/height dimensions, band counts, color interpretation, data types, affine geotransforms, bounds, and Coordinate Reference Systems (CRS).
- **Fast Cloud Previews**: Dynamic generation of web-optimized PNG previews and thumbnails for GeoTIFFs stored in private Supabase buckets.

### 2. Bi-Temporal Change Detection & Hard Validation Gate
- **Hard Gate Architecture**: Validation is a mandatory pre-condition before any change detection analysis request is created, job queued, or active scene established.
- **Strict Modality Rules**:
  - `Optical + Optical` → **Valid**
  - `Multispectral + Multispectral` → **Valid**
  - `SAR VV + SAR VV` or `SAR VH + SAR VH` → **Valid**
  - `SAR VV + SAR VH` → **Invalid** (`SAR_POLARIZATION_MISMATCH`)
  - `Multispectral GeoTIFF + RGB JPEG` → **Invalid** (`IMAGE_TYPE_MISMATCH`)
  - `Optical + SAR` → **Invalid** (`IMAGE_TYPE_MISMATCH`)
- **Fail-Closed Modality Detection**: Any image with unknown modality immediately fails with `UNKNOWN_MODALITY`.
- **Comprehensive Compatibility Checks**:
  - **Band Consistency**: Required spectral bands must exist in both epochs.
  - **Pixel Dimensions & Aspect Ratio**: Validates exact dimensions and aspect ratios within strict tolerances.
  - **Geospatial & CRS Alignment**: Validates CRS matching between epochs without silent auto-reprojection.
  - **Temporal & Observation Order**: Ensures T1 baseline precedes T2 target.
- **Interactive Blocking Modal**: Incompatible pairs immediately trigger a dedicated dark-themed **Invalid Input** modal detailing Image 1 vs Image 2 attributes and resolution guidance, blocking model invocation and preventing active scene pollution.

### 3. Projects & Workspaces
- Group multi-turn analysis conversations and satellite imagery under scoped Projects.
- Full CRUD API with persistence in Supabase PostgreSQL (`projects` table, migration `0008_projects.sql`).
- Quick-filter workspaces, project badges, and persistent conversation assignments.

### 4. Library & Asset Workspace
- ChatGPT-inspired file and asset management with custom folder support.
- Live metadata cards displaying sensor types, acquisition dates, file sizes, and band configurations.

### 5. Custom Model Attachment & Edge Inference
- Connect external models with configurable tasks (Segmentation, Detection, VQA).
- Confidence thresholding, inference parameter tuning, and dual cloud + local model execution.

---

## First-Time Setup (Fresh Clone)

Requirements: **Node.js 20+**, **Python 3.10+** (developed on 3.12), Git.

```bash
git clone https://github.com/Shruti11506/sat_.git
cd sat_
npm install
npm run setup
```

`npm run setup` creates `backend/.venv`, installs `backend/requirements.txt`, and creates `backend/.env` from `backend/.env.example` (existing `.env` is never overwritten).

Then open **`backend/.env`** and fill in your Supabase credentials:

| Variable | Description |
|---|---|
| `SUPABASE_URL` | Project URL: `https://<ref>.supabase.co` |
| `SUPABASE_SECRET_KEY` | Secret key (`sb_secret_…`) or `service_role` key (never publishable/anon) |
| `SUPABASE_STORAGE_BUCKET` | Storage bucket name (defaults to `Satquery`) |

---

## Running the Application

```bash
npm run dev
```

This concurrently launches:
1. **FastAPI Backend**: `http://127.0.0.1:8000`
2. **Vite Frontend**: `http://localhost:5173` (or `:5174` if `:5173` is busy)

Interactive Swagger API Documentation is available at:
- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`

---

## Health & Verification

1. Backend Health: `http://localhost:8000/api/v1/health` → `{"status": "healthy"}`
2. Supabase Connectivity: `http://localhost:8000/api/v1/health/supabase` → `{"supabase": "connected"}`
3. Change Detection Validation API: `POST http://localhost:8000/api/v1/validation/change-detection`

---

## Testing

### Backend Unit & Regression Suite (327 tests)
```bash
cd backend
.venv\Scripts\python -m pytest -q      # Windows
# source .venv/bin/activate && pytest -q  # macOS/Linux
```

### Frontend Production Build
```bash
npm run build
```

---

## Documentation Links

- [Backend Foundation & Endpoints](backend/README.md)
- [Architecture & Coding Standards](CLAUDE.md)
