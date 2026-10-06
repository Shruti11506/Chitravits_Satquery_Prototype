"""Analysis request endpoint.

Creates an analysis_jobs record (status "queued"). When the agent bridge is
enabled (``AGENT_ENABLED``), the queued job is then handed to the real SatQuery
LangGraph agent in a FastAPI background task; the response still returns
immediately with the queued job, so the frontend polls job -> result exactly as
before. With ``AGENT_ENABLED`` false (the default) this behaves identically to
the pre-agent milestone: a job is recorded and left for a future AI layer.
"""
import logging

from fastapi import APIRouter, BackgroundTasks, Query, status

from app.core.config import get_settings
from app.schemas.analysis import AnalysisCreate, AnalysisCreateResponse
from app.schemas.common import ApiResponse
from app.schemas.history import HistoryItem
from app.services import analysis_service, job_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analysis", tags=["Analysis"])


@router.post(
    "",
    response_model=ApiResponse[AnalysisCreateResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Create an analysis request; the SatQuery agent processes it when enabled",
)
def create_analysis(
    payload: AnalysisCreate, background_tasks: BackgroundTasks
) -> ApiResponse[AnalysisCreateResponse]:
    job = analysis_service.create_analysis(payload)

    # Hand the queued job to the real agent (understand_query -> preprocess ->
    # plan_tools -> execute_tools -> aggregate_results). The import is deferred
    # and guarded so a missing/broken agent package can never break job
    # creation itself -- the job is still recorded and simply stays queued.
    if get_settings().AGENT_ENABLED:
        try:
            from app.agent_bridge.runner import run_analysis_job

            background_tasks.add_task(run_analysis_job, str(job["id"]))
        except Exception:  # noqa: BLE001
            logger.exception("Could not schedule agent processing for job %s", job["id"])

    return ApiResponse.ok(
        AnalysisCreateResponse(
            job_id=job["id"],
            imagery_id=job["imagery_id"],
            comparison_imagery_id=job.get("comparison_imagery_id"),
            analysis_type=job["analysis_type"],
            query=job["query"],
            conversation_id=job.get("conversation_id"),
            status=job["status"],
        )
    )


@router.get(
    "/history",
    response_model=ApiResponse[list[HistoryItem]],
    summary="List analysis requests (analysis_jobs joined with imagery), most recent first",
)
def get_history(limit: int = Query(default=50, ge=1, le=200)) -> ApiResponse[list[HistoryItem]]:
    items = job_service.list_history(limit=limit)
    return ApiResponse.ok([HistoryItem(**item) for item in items])
