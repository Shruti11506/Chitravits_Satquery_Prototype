# SatQuery AI: demo deployment (free / near-free)

Written 2026-09-26 for the 30 Sept SIH screening. Read together with
`docs/ai-integration/HANDOFF.md`. **Deploying does not make the AI work by itself.**
HANDOFF T1–T5 (model client, EarthMind server, worker, showing results in chat)
must be done first. Today nothing processes queued jobs.

## 1. Where each part runs

```
Browser
  │
  ▼
Vercel (free)                 React/Vite build, VITE_API_BASE_URL → Render
  │
  ▼
Render (free, Docker)         FastAPI /api/v1 + job worker thread (RUN_WORKER_IN_API=1)
  │        │
  │        └──► Supabase (free, already in use)   Postgres + Storage bucket "Satquery"
  │
  ├──HTTPS + X-SatQuery-Key──► Modal: satquery-earthmind  (L4 GPU, scale-to-zero)
  │                               VQA, captioning, grounding masks, optical+SAR
  └──HTTPS + X-SatQuery-Key──► Modal: satquery-mcd-mamba  (L4 GPU, scale-to-zero)
                                  change detection mask + area
```

Why this split:

- **Modal** is the only free option that runs your *existing* FastAPI model servers unchanged on a real GPU. It costs nothing while idle and includes monthly free credits.
- **HF ZeroGPU** would need a Gradio rewrite and clashes with EarthMind's pinned torch/transformers.
- **Render + Vercel + Supabase** cost nothing for the CPU parts.
- The backend doesn't change: only the `*_SERVICE_URL` values differ from local, and the same containers move to SAC/institutional GPUs later.

**Fallback (fastest, zero cost):** keep the model servers on the college GPU PC
and expose them with a Cloudflare quick tunnel:

```
cloudflared tunnel --url http://127.0.0.1:8101   # prints https://xxxx.trycloudflare.com
```

Put that URL in `EARTHMIND_SERVICE_URL` on Render. The downside is that the PC must stay on,
and the URL changes every restart. The shared-key check then has to go in `serving/common.py`,
because the Modal wrapper that adds it isn't used.

## 2. Code changes needed for hosting (small, on top of HANDOFF)

1. **Shared key to the model servers.** In `backend/app/core/config.py`, add
   `SERVING_API_KEY: str = ""`. In `app/ml/services/remote.py`, send the header
   `X-SatQuery-Key: <SERVING_API_KEY>` on `/v1/predict` when it's set.
2. **Worker inside the API** (Render's free plan has no background workers). Give
   `app/worker.py` a `start_background_worker()` that runs the same poll loop in
   a daemon thread. Then, in `app/main.py`:
   ```python
   @app.on_event("startup")
   def _maybe_start_worker():
       if os.getenv("RUN_WORKER_IN_API") == "1":
           from app.worker import start_background_worker
           start_background_worker()
   ```
   Also, on start, mark jobs stuck in `processing` for more than 15 min as `failed`
   (`INTERNAL_ERROR: worker restarted`). Free Render instances restart when they sleep.
3. **Dockerfile** now honours `$PORT` (done in this folder).
4. `.env.example`: add `EARTHMIND_SERVICE_URL=`, `MCD_MAMBA_SERVICE_URL=`,
   `SERVING_API_KEY=`, `RUN_WORKER_IN_API=`.

## 3. Step by step

### A. Model servers on Modal (GPU)

```
pip install modal && modal setup
modal secret create satquery-serving SERVING_API_KEY=<random 40+ chars>
# HANDOFF T2: copy docs/ai-integration/reference/sat_ml/serving → sat_ml/serving first
modal run    sat_ml/deploy/modal_earthmind.py::download_public_weights
#   or: modal volume put satquery-weights <fine-tuned folder> /EarthMind-ft  (+ edit EARTHMIND_MODEL_PATH)
set SERVING_API_KEY=<same value>   &&   modal run sat_ml/deploy/modal_earthmind.py::smoke_test
modal deploy sat_ml/deploy/modal_earthmind.py
```

✅ `smoke_test` prints real EarthMind text for `demo_images/00004.jpg`.
If it fails with `No module named X`, add X to the image's `pip_install` list and re-run.

MCD-Mamba: upload the trained `.pth` to `/mcd/model.pth` and set
`MCD_MODE`/`MCD_OPT_BANDS`/`MCD_CONFIG` **exactly as trained**. Then run
`modal deploy sat_ml/deploy/modal_mcd_mamba.py`. If the kernel build fails, use the tunnel fallback.

### B. Backend on Render

1. Push `render.yaml` (repo root of `sat_`) and the Dockerfile change.
2. In the Render dashboard, go to New → Blueprint → the repo. Fill in the `sync:false` secrets:
   `SUPABASE_*`, `CORS_ORIGINS=https://<your>.vercel.app`, the two Modal URLs, and `SERVING_API_KEY`.
3. ✅ `https://satquery-api.onrender.com/api/v1/health` returns success.

### C. Frontend on Vercel

1. In Vercel, go to New Project → the `sat_` repo (framework: Vite).
2. Add the env var `VITE_API_BASE_URL=https://satquery-api.onrender.com/api/v1`, then deploy.
3. Add the Vercel domain to Render's `CORS_ORIGINS` and redeploy Render.

## 4. Before sharing the link (no auth exists yet)

- **Rotate the Supabase service-role key.** It leaked to logs earlier (PROJECT_STATUS §20).
- Add a simple **access code** (env `DEMO_ACCESS_CODE`, checked in an API
  dependency, and entered once in the UI), or judges and bots can fill your storage
  and burn Modal credits.
- Rate-limit `POST /imagery` and `POST /analysis` (e.g. `slowapi`, ~20/min per IP).
- `APP_ENV=production` (already set in render.yaml) turns off the localhost CORS regex and DEBUG logs.

## 5. Judging-day checklist

- [ ] `MIN_CONTAINERS=1 modal deploy ...` about 30 min before. This keeps the GPU warm (roughly $0.8/h on an L4). Set it back to 0 afterwards.
- [ ] A free cron-job.org ping to `/api/v1/health` every 10 min, so Render doesn't sleep. The first wake takes about 50 s.
- [ ] Open the Supabase project the day before. Free projects pause after 7 days without activity.
- [ ] Run through the HANDOFF T7 matrix on the **deployed** URL, not localhost.
- [ ] Record a 2-minute screen video of the working flow as a backup.

## 6. Scope for 30 Sept (be honest in the PPT)

| Feature | Status target for screening |
|---|---|
| Upload + chat VQA/captioning (EarthMind) | Must work end to end |
| Agent routing + execution trace | Works via LangGraph; show `trace` / `decided_by` in the UI |
| Segmentation / grounding mask overlay | Mask PNG from evidence drawn over the image in ImageViewer |
| Change detection (MCD-Mamba) | Only if a trained checkpoint exists and T6 is done; otherwise say "in progress" |
| Map view (georeferenced) | TIFF bbox is already stored. A Leaflet map with the thumbnail at `bbox` is the next step |
| Change/Fusion/Pipeline/Analytics/Report screens | Still **mock data**. Hide or label them, per the no-fake-output rule |
