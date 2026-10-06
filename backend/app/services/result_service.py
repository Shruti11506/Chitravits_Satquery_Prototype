"""Business logic for analysis_results and evidence.

Retrieval, plus persistence for the agent bridge: ``create_result`` /
``create_evidence`` store what the SatQuery agent actually returned. Nothing
here invents an answer, a bounding box or a confidence score -- it only writes
values passed in by the bridge, which got them from the model.
"""
import logging

from app.core.exceptions import NotFoundError, SupabaseError
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

RESULTS_TABLE = "analysis_results"
EVIDENCE_TABLE = "evidence"


def create_result(row: dict) -> dict:
    """Insert one analysis_results row (from the agent) and return it."""
    client = get_supabase()
    try:
        response = client.table(RESULTS_TABLE).insert(row).execute()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Supabase insert failed for analysis_results (job %s)", row.get("job_id"))
        raise SupabaseError("Failed to save the analysis result.") from exc
    if not response.data:
        raise SupabaseError("Analysis result insert returned no data.")
    return response.data[0]


def create_evidence(rows: list[dict]) -> list[dict]:
    """Insert evidence rows for a result. No-op for an empty list."""
    if not rows:
        return []
    client = get_supabase()
    try:
        response = client.table(EVIDENCE_TABLE).insert(rows).execute()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Supabase insert failed for evidence (%d rows)", len(rows))
        raise SupabaseError("Failed to save analysis evidence.") from exc
    return response.data or []


def get_result(result_id: str) -> dict:
    client = get_supabase()

    try:
        response = (
            client.table(RESULTS_TABLE).select("*").eq("id", result_id).maybe_single().execute()
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Supabase get failed for analysis_results %s", result_id)
        raise SupabaseError("Failed to fetch analysis result.") from exc

    if not response or not response.data:
        raise NotFoundError("RESULT_NOT_FOUND", f"Result '{result_id}' was not found.")

    return response.data


def get_evidence(result_id: str) -> list[dict]:
    # Confirms the parent result exists so callers get RESULT_NOT_FOUND
    # instead of a silently empty list for a bad id.
    get_result(result_id)

    client = get_supabase()
    try:
        response = client.table(EVIDENCE_TABLE).select("*").eq("result_id", result_id).execute()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Supabase list failed for evidence of result %s", result_id)
        raise SupabaseError("Failed to fetch evidence.") from exc

    return response.data or []
