"""Process one queued analysis job with the real SatQuery agent.

Called as a FastAPI background task after a job row is created. Moves the job
queued -> processing -> completed/failed, and on success persists the agent's
answer (analysis_results) and evidence. Every failure path marks the job failed
with a client-safe message; nothing is ever faked.
"""
from __future__ import annotations

import logging

import anyio

from app.agent_bridge.agent import AgentUnavailableError, get_agent
from app.agent_bridge.mapping import (
    build_user_query,
    evidence_rows_from_response,
    result_row_from_response,
)
from app.services import imagery_service, job_service, result_service

logger = logging.getLogger(__name__)


async def _to_thread(func, *args):
    return await anyio.to_thread.run_sync(func, *args)


async def run_analysis_job(job_id: str) -> None:
    """Run the agent for one job id and persist the outcome."""
    try:
        job = await _to_thread(job_service.get_job, job_id)
    except Exception:  # noqa: BLE001 - can't even load the job; nothing to update
        logger.exception("Agent bridge could not load job %s", job_id)
        return

    try:
        await _to_thread(job_service.mark_processing, job_id)

        primary = await _to_thread(imagery_service.get_imagery, str(job["imagery_id"]))
        comparison = None
        if job.get("comparison_imagery_id"):
            comparison = await _to_thread(
                imagery_service.get_imagery, str(job["comparison_imagery_id"])
            )

        user_query = build_user_query(job, primary, comparison)

        try:
            agent = get_agent()
        except AgentUnavailableError as exc:
            logger.error("Agent unavailable for job %s: %s", job_id, exc)
            await _mark_failed(job_id, str(exc))
            return

        from satquery.agent.interface import AgentStatus

        response = await agent.process(user_query)

        if response.status == AgentStatus.COMPLETED:
            result = await _to_thread(
                result_service.create_result, result_row_from_response(job, response)
            )
            evidence_rows = evidence_rows_from_response(str(result["id"]), response)
            if evidence_rows:
                await _to_thread(result_service.create_evidence, evidence_rows)
            model_name = (response.data or {}).get("model") or (response.data or {}).get("tool_selected")
            await _to_thread(
                _mark_completed, job_id, str(result["id"]), model_name
            )
            logger.info("Job %s completed by tool=%s", job_id, (response.data or {}).get("tool_selected"))
        else:
            error = (response.data or {}).get("error") or {}
            message = error.get("message") or response.message or "Analysis failed."
            await _mark_failed(job_id, message)
            logger.info("Job %s failed: %s", job_id, error.get("code"))

    except Exception as exc:  # noqa: BLE001 - never leave a job stuck in processing
        logger.exception("Agent bridge crashed for job %s", job_id)
        await _mark_failed(job_id, f"Internal error while processing the analysis: {exc}")


def _mark_completed(job_id: str, result_id: str, model_name: str | None) -> None:
    job_service.mark_completed(job_id, result_id=result_id, model_name=model_name)


async def _mark_failed(job_id: str, message: str) -> None:
    try:
        await _to_thread(_mark_failed_sync, job_id, message)
    except Exception:  # noqa: BLE001 - best effort; already logged upstream
        logger.exception("Could not mark job %s failed", job_id)


def _mark_failed_sync(job_id: str, message: str) -> None:
    job_service.mark_failed(job_id, error_message=message)
