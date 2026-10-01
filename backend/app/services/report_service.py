"""Builds the downloadable PDF report of one analysis chat.

Everything in the report is read here from the database and Storage -- the
client only says WHICH chat (a conversation, or a legacy chat's image) and,
optionally, the name of the model attached in its workspace (a browser-only
setting the backend never sees). Nothing is invented: a field with no stored
value is left out, and a query with no stored result says so.

Rendering lives in report_pdf.py.
"""
from __future__ import annotations

import io
import logging
import re
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from PIL import Image as PILImage

from app.core.config import get_settings
from app.core.exceptions import NotFoundError, StorageError, SupabaseError, ValidationAppError
from app.db.supabase import execute_read, get_supabase
from app.services import (
    conversation_service,
    imagery_service,
    profile_service,
    project_service,
    raster_service,
    report_pdf,
    storage_service,
    title_service,
)
from app.validation.sensors import SAR_FAMILIES, identify_sensor

logger = logging.getLogger(__name__)

MAX_IMAGES = 6
EMBEDDABLE = {".png", ".jpg", ".jpeg", ".webp"}
MAX_OUTPUT_FIELDS = 20

_STATUS_NOTES = {
    "queued": "Result not available — this query is queued and has not been processed yet.",
    "processing": "Result not available — this query is still being processed.",
    "cancelled": "Result not available — this query was cancelled.",
}


# ---- Loading ---------------------------------------------------------------

def _rows(table: str, column: str, values: list[str]) -> list[dict]:
    if not values:
        return []
    client = get_supabase()
    try:
        response = execute_read(client.table(table).select("*").in_(column, values))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Supabase read failed for %s", table)
        raise SupabaseError(f"Failed to load {table} for the report.") from exc
    return response.data or []


def _load_chat(conversation_id: str | None, imagery_id: str | None) -> dict:
    if conversation_id:
        conversation = conversation_service.get_conversation(conversation_id)
        jobs = conversation_service.select_for_conversation("analysis_jobs", conversation_id)
        uploads = conversation_service.select_for_conversation("imagery", conversation_id)
        project = None
        if conversation.get("project_id"):
            try:
                project = project_service.get_project(conversation["project_id"])
            except NotFoundError:
                project = None
        return {"conversation": conversation, "jobs": jobs, "uploads": uploads, "project": project}
    if imagery_id:
        jobs = sorted(conversation_service.legacy_jobs(imagery_id), key=lambda j: j.get("created_at") or "")
        return {"conversation": None, "jobs": jobs, "uploads": [imagery_service.get_imagery(imagery_id)], "project": None}
    raise ValidationAppError("REPORT_TARGET_REQUIRED", "Choose a conversation or an image to report on.")


def _image_rows(chat: dict) -> list[dict]:
    """The images the chat's queries ran on (in order), else its uploads."""
    by_id = {row["id"]: row for row in chat["uploads"]}
    ordered: list[str] = []
    for job in chat["jobs"]:
        for key in ("imagery_id", "comparison_imagery_id"):
            if job.get(key) and job[key] not in ordered:
                ordered.append(job[key])
    if not ordered:
        ordered = [row["id"] for row in chat["uploads"]]
    rows = []
    for image_id in ordered[:MAX_IMAGES]:
        row = by_id.get(image_id)
        if row is None:
            try:
                row = imagery_service.get_imagery(image_id)
            except NotFoundError:
                continue
        rows.append(row)
    return rows


def _decodable(data: bytes) -> bool:
    try:
        with PILImage.open(io.BytesIO(data)) as img:
            img.verify()
        return True
    except Exception:  # noqa: BLE001
        return False


def _download(client, path: str) -> bytes | None:
    try:
        data = storage_service.download_file(client, path)
    except StorageError:
        return None
    return data if _decodable(data) else None


def _image_bytes(client, row: dict) -> tuple[bytes | None, str | None]:
    """(bytes, None) for an embeddable picture of the image, else (None, why)."""
    storage_path = row.get("storage_path")
    if not storage_path:
        return None, "the file is not in storage."
    if imagery_service.has_raster_source(storage_path):
        path = row.get("preview_path")
        if not path and "preview_status" not in row:  # migration 0007 not applied
            path = raster_service.thumbnail_path_for(storage_path)
        if not path:
            return None, "no preview of this TIFF could be rendered."
    elif storage_service.get_extension(storage_path) in EMBEDDABLE:
        path = storage_path
    else:
        return None, "this file type can't be embedded in a PDF."
    data = _download(client, path)
    return (data, None) if data else (None, "the image could not be loaded from storage.")


def _results(jobs: list[dict]) -> tuple[dict[str, dict], dict[str, list[dict]]]:
    results = _rows("analysis_results", "job_id", [j["id"] for j in jobs])
    by_job: dict[str, dict] = {}
    for result in sorted(results, key=lambda r: r.get("created_at") or ""):
        by_job[result["job_id"]] = result  # latest result per job wins
    evidence = _rows("evidence", "result_id", [r["id"] for r in by_job.values()])
    by_result: dict[str, list[dict]] = {}
    for item in evidence:
        by_result.setdefault(item["result_id"], []).append(item)
    return by_job, by_result


# ---- Formatting ------------------------------------------------------------

def _tz():
    tz_name = None
    try:
        tz_name = profile_service.get_current_profile().get("timezone")
    except Exception:  # noqa: BLE001 - a report must not fail over a timezone
        pass
    for name in (tz_name, get_settings().APP_TIMEZONE):
        if name:
            try:
                return ZoneInfo(name)
            except Exception:  # noqa: BLE001
                continue
    return timezone.utc


def _when(value: str | None, tz) -> str | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz).strftime("%d %b %Y, %H:%M %Z").strip()


def _confidence(value: Any) -> str | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{number:.1%}" if 0 <= number <= 1 else f"{number:g}"


def _humanize(key: str) -> str:
    return re.sub(r"[_\-]+", " ", key).strip().capitalize()


def _scalar_outputs(raw_output: Any) -> list[tuple[str, str]]:
    """Plain scalar fields of the model's structured `outputs`, if it has any."""
    if not isinstance(raw_output, dict):
        return []
    outputs = raw_output.get("outputs")
    if not isinstance(outputs, dict):
        final = raw_output.get("final_response")
        outputs = final.get("outputs") if isinstance(final, dict) else None
    if not isinstance(outputs, dict):
        return []
    pairs = []
    for key, value in outputs.items():
        if isinstance(value, bool):
            pairs.append((_humanize(key), "Yes" if value else "No"))
        elif isinstance(value, (int, float, str)) and str(value).strip():
            pairs.append((_humanize(key), str(value)[:500]))
        if len(pairs) >= MAX_OUTPUT_FIELDS:
            break
    return pairs


def _sensor(row: dict):
    return identify_sensor(
        sensor=row.get("sensor"),
        source=row.get("source"),
        filename=row.get("original_filename") or row.get("name"),
    )


def _sensor_label(ident) -> str | None:
    if ident.family is None:
        return None
    name = {"sentinel-1": "Sentinel-1", "sentinel-2": "Sentinel-2", "cartosat": "Cartosat", "risat": "RISAT"}[ident.family.value]
    return f"{name} ({ident.product})" if ident.product else name


def _resolution(raster: dict) -> str | None:
    transform, crs = raster.get("transform"), raster.get("crs")
    if not transform or not crs:
        return None
    x, y = abs(transform[0]), abs(transform[4])
    unit = "units"
    try:
        from rasterio.crs import CRS

        parsed = CRS.from_string(crs)
        unit = "°" if parsed.is_geographic else (parsed.linear_units or "units")
    except Exception:  # noqa: BLE001
        pass
    if unit in ("metre", "meter", "m"):
        return f"{x:g} × {y:g} m per pixel"
    if unit == "°":
        return f"{x:.6g}° × {y:.6g}° per pixel"
    return f"{x:g} × {y:g} {unit} per pixel"


def _image_name(row: dict) -> str:
    return row.get("original_filename") or row.get("name") or row["id"]


def _image_caption(row: dict, count: int) -> str:
    position = row.get("pair_position")
    role = {1: "Reference image (Image 1)", 2: "Comparison image (Image 2)"}.get(position)
    label = role or ("Input satellite imagery" if count == 1 else "Input satellite image")
    return f"{label} · {_image_name(row)}"


def safe_filename(title: str, generated: datetime) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", title).strip("_")[:60] or "Analysis"
    return f"SatQuery_Analysis_Report_{slug}_{generated.strftime('%Y-%m-%d')}.pdf"


# ---- Assembly --------------------------------------------------------------

def build_report(
    *, conversation_id: str | None = None, imagery_id: str | None = None, attached_model: str | None = None
) -> tuple[str, bytes]:
    """-> (filename, PDF bytes) for one chat."""
    chat = _load_chat(conversation_id, imagery_id)
    jobs = chat["jobs"]
    tz = _tz()
    generated = datetime.now(tz)
    client = get_supabase()

    conversation = chat["conversation"]
    title = None
    if conversation and conversation.get("title_source") in ("auto", "user"):
        title = conversation.get("title")
    if not title:
        title = next(
            (t for t in (title_service.generate_conversation_title(j.get("query")) for j in jobs) if t), None
        )
    title = title or "Satellite Image Analysis"

    results_by_job, evidence_by_result = _results(jobs)
    images = _image_rows(chat)

    # Input images
    input_images = []
    for row in images:
        data, why = _image_bytes(client, row)
        input_images.append({"caption": _image_caption(row, len(images)), "image": data, "note": why and f"Image not embedded — {why}"})

    # Per-query results
    job_items = []
    for job in jobs:
        result = results_by_job.get(job["id"])
        item: dict[str, Any] = {
            "query": job.get("query"),
            "job_id": job["id"],
            "status": (job.get("status") or "").capitalize() or None,
            "created_at": _when(job.get("created_at"), tz),
            "model_name": (result or {}).get("model_name") or job.get("model_name"),
            "visualizations": [],
        }
        if result:
            item["answer"] = result.get("answer")
            item["confidence"] = _confidence(result.get("confidence"))
            item["outputs"] = _scalar_outputs(result.get("raw_output"))
            evidence = evidence_by_result.get(result["id"], [])
            item["evidence"] = [
                {"type": _humanize(ev.get("evidence_type") or "") or None, "description": ev.get("description"), "confidence": _confidence(ev.get("confidence"))}
                for ev in evidence
            ]
            for ev in evidence:
                ref = ev.get("source_reference") or ""
                # Only our own Storage paths -- never fetch an arbitrary URL.
                if ref and "://" not in ref and storage_service.get_extension(ref) in EMBEDDABLE:
                    data = _download(client, ref)
                    if data:
                        caption = f"Output visualization · {_humanize(ev.get('evidence_type') or 'output')}"
                        if ev.get("description"):
                            caption += f" — {ev['description']}"
                        item["visualizations"].append({"image": data, "caption": caption})
            if not item["answer"] and not item["outputs"] and not item["evidence"]:
                item["pending_note"] = "Result not available — the model stored no answer for this query."
        elif job.get("status") == "failed":
            item["error"] = job.get("error_message") or "The analysis failed and recorded no error message."
        else:
            item["pending_note"] = _STATUS_NOTES.get(job.get("status"), "Result not available.")
        job_items.append(item)

    # Metadata
    sensors = [(_image_name(row), _sensor(row)) for row in images]
    metadata: list[tuple[str, Any]] = []
    if chat["project"]:
        metadata.append(("Project", chat["project"].get("name")))
    metadata.append(("Analysis", title))
    if jobs:
        ids = [j["id"][:8] for j in jobs]
        metadata.append(("Job ID" if len(ids) == 1 else "Job IDs", ", ".join(ids)))
    if attached_model:
        metadata.append(("Attached model", attached_model))
    if images:
        metadata.append(("Image" if len(images) == 1 else "Images", "\n".join(_image_name(r) for r in images)))
    sensor_names = sorted({label for _, ident in sensors if (label := _sensor_label(ident))})
    if sensor_names:
        metadata.append(("Sensor", ", ".join(sensor_names)))
    if jobs:
        metadata.append(("Analysis submitted", _when(jobs[0].get("created_at"), tz)))
    metadata.append(("Report generated", generated.strftime("%d %b %Y, %H:%M %Z").strip()))

    # Model & processing
    processing: list[tuple[str, Any]] = []
    models = sorted({m for m in (i.get("model_name") for i in job_items) if m})
    if models:
        processing.append(("Model" if len(models) == 1 else "Models", ", ".join(models)))
    families = {ident.family for _, ident in sensors if ident.family}
    if families:
        sar = bool(families & SAR_FAMILIES)
        optical = bool(families - SAR_FAMILIES)
        processing.append(("Processing type", "Optical + SAR" if sar and optical else "SAR" if sar else "Optical"))
    for name, row in ((_image_name(r), r) for r in images):
        raster = (row.get("metadata") or {}).get("raster") or {}
        prefix = f"{name}: " if len(images) > 1 else ""
        if raster.get("width") and raster.get("height"):
            size = f"{raster['width']} × {raster['height']} px"
            if raster.get("band_count"):
                size += f", {raster['band_count']} band{'s' if raster['band_count'] != 1 else ''}"
            if raster.get("dtypes"):
                size += f" ({', '.join(sorted(set(raster['dtypes'])))})"
            processing.append(("Image size", prefix + size))
        if (res := _resolution(raster)):
            processing.append(("Resolution", prefix + res))
        if raster.get("crs"):
            processing.append(("Coordinate system", prefix + raster["crs"]))
        if row.get("latitude") is not None and row.get("longitude") is not None:
            processing.append(("Scene centre", f"{prefix}{row['latitude']:.5f}, {row['longitude']:.5f}"))
    if jobs:
        counts: dict[str, int] = {}
        for job in jobs:
            counts[job.get("status") or "unknown"] = counts.get(job.get("status") or "unknown", 0) + 1
        processing.append(("Processing status", ", ".join(f"{n} {s}" for s, n in counts.items())))

    notes = []
    if attached_model:
        notes.append(
            "Responses produced in the browser by the attached workspace model are not included; "
            "this report contains only results stored by the SatQuery analysis service."
        )

    report = {
        "title": title,
        "generated_at": generated,
        "metadata": [(k, v) for k, v in metadata if v not in (None, "")],
        "queries": [j["query"] for j in jobs if j.get("query")],
        "input_images": input_images,
        "jobs": job_items,
        "processing": processing,
        "notes": notes,
    }
    return safe_filename(title, generated), report_pdf.render_report(report)
