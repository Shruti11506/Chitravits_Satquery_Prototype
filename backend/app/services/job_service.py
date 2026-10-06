"""Business logic for the analysis_jobs resource.

This module only creates and retrieves job *records*. It never executes,
schedules, or simulates AI processing -- jobs are created with status
"queued" and stay there until a future AI layer picks them up.
"""
import logging
from datetime import datetime, timezone
from uuid import UUID

from app.core.exceptions import NotFoundError, SchemaNotMigratedError, SupabaseError
from app.db.supabase import execute_read, get_supabase
from app.schemas.analysis import AnalysisType
from app.services.imagery_service import PAIR_MIGRATION_HINT

logger = logging.getLogger(__name__)

TABLE = "analysis_jobs"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def update_job(job_id: str, fields: dict) -> dict:
    """Patch an analysis_jobs row (status, result_id, timestamps, error).

    Used by the agent bridge to move a job through its lifecycle. Only the
    columns present in ``fields`` are changed; every column written here
    already exists in the current schema (no migration needed).
    """
    client = get_supabase()
    try:
        response = client.table(TABLE).update(fields).eq("id", job_id).execute()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Supabase update failed for analysis_jobs %s", job_id)
        raise SupabaseError("Failed to update analysis job.") from exc
    if not response.data:
        raise NotFoundError("JOB_NOT_FOUND", f"Analysis job '{job_id}' was not found.")
    return response.data[0]


def mark_processing(job_id: str) -> dict:
    return update_job(job_id, {"status": "processing", "started_at": _now_iso()})


def mark_completed(job_id: str, *, result_id: str, model_name: str | None = None) -> dict:
    fields: dict = {"status": "completed", "result_id": result_id, "completed_at": _now_iso()}
    if model_name:
        fields["model_name"] = model_name
    return update_job(job_id, fields)


def mark_failed(job_id: str, *, error_message: str) -> dict:
    return update_job(
        job_id,
        {"status": "failed", "error_message": (error_message or "")[:2000], "completed_at": _now_iso()},
    )


def create_job(
    imagery_id: UUID,
    analysis_type: AnalysisType,
    query: str | None,
    conversation_id: str | None = None,
    comparison_imagery_id: str | None = None,
) -> dict:
    client = get_supabase()
    row = {
        "imagery_id": str(imagery_id),
        "analysis_type": analysis_type.value,
        "query": query,
        "status": "queued",
    }
    if conversation_id:
        row["conversation_id"] = conversation_id
    if comparison_imagery_id:
        # Only for pair queries, so single-image queries never need migration 0006.
        row["comparison_imagery_id"] = comparison_imagery_id

    try:
        response = client.table(TABLE).insert(row).execute()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Supabase insert failed for analysis_jobs")
        if comparison_imagery_id and getattr(exc, "code", None) in {"PGRST204", "42703"}:
            raise SchemaNotMigratedError(PAIR_MIGRATION_HINT) from exc
        raise SupabaseError("Failed to create analysis job.") from exc

    if not response.data:
        raise SupabaseError("Analysis job insert returned no data.")

    return response.data[0]


def get_job(job_id: str) -> dict:
    client = get_supabase()

    try:
        response = client.table(TABLE).select("*").eq("id", job_id).maybe_single().execute()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Supabase get failed for analysis_jobs %s", job_id)
        raise SupabaseError("Failed to fetch analysis job.") from exc

    if not response or not response.data:
        raise NotFoundError("JOB_NOT_FOUND", f"Analysis job '{job_id}' was not found.")

    return response.data


def list_history(limit: int = 50) -> list[dict]:
    """Analysis jobs joined with their imagery's name, most recent first.

    Retrieval only -- reflects exactly what's stored, never invents a title
    or status. Used by the sidebar/history UI as its sole data source.
    """
    client = get_supabase()

    try:
        response = execute_read(
            client.table(TABLE).select("*").order("created_at", desc=True).limit(limit)
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Supabase list failed for analysis_jobs history")
        raise SupabaseError("Failed to list analysis history.") from exc

    jobs = response.data or []

    # One batched lookup for every distinct imagery_id, not one request per
    # job -- an N+1 pattern here previously fired dozens of rapid concurrent
    # requests against the shared Supabase client and intermittently tripped
    # a Cloudflare-level 400 under load (observed live with ~15 history rows).
    imagery_ids = list({job["imagery_id"] for job in jobs if job.get("imagery_id")})
    names_by_id: dict[str, str] = {}
    if imagery_ids:
        try:
            imagery_rows = execute_read(
                client.table("imagery").select("id,name").in_("id", imagery_ids)
            )
            names_by_id = {row["id"]: row["name"] for row in (imagery_rows.data or [])}
        except Exception:  # noqa: BLE001 - name enrichment is best-effort, never fails the whole list
            logger.exception("Failed to batch-fetch imagery names for history")

    return [
        {**job, "job_id": job["id"], "imagery_name": names_by_id.get(job["imagery_id"])}
        for job in jobs
    ]
