"""LangGraph node wrapping the Evidence Engine.

Sits between ``aggregate_results`` and ``response_generation``:

    ... → aggregate_results → build_evidence → response_generation → END

It reads the aggregated tool output and the preprocessing profiles from state
and writes one ``evidence_package`` key. It never raises: on any failure it
records a structured AgentError and returns an empty package so the answer path
still completes (spec §51 graceful degradation).
"""

from __future__ import annotations

import logging

from satquery.evidence.engine import build_evidence_package
from satquery.evidence.schemas import EvidencePackage

logger = logging.getLogger(__name__)


def make_evidence_node():
    """Return the async ``build_evidence`` LangGraph node."""

    async def build_evidence(state) -> dict:
        from satquery.agent.state import AgentError  # local import avoids cycle

        task = state.get("task")
        task_value = task.value if task is not None else "unknown"
        tool_results = state.get("tool_results") or []
        analysis = state.get("analysis_result")

        # Nothing ran (blocking error path) — emit an empty, honest package.
        if not tool_results and analysis is None:
            return {"evidence_package": EvidencePackage(
                query_id=state.get("query_id", ""), task=task_value,
                summary="No tools ran; no evidence collected.",
            )}

        try:
            package = build_evidence_package(
                query_id=state.get("query_id", ""),
                task=task_value,
                query_text=state.get("query_text", ""),
                tool_results=tool_results,
                data_profiles=state.get("data_profiles") or [],
                aoi_contexts=state.get("aoi_contexts") or [],
                analysis_result=analysis,
            )
        except Exception as exc:  # noqa: BLE001 - node must not crash the graph
            logger.exception("Evidence engine failed")
            return {
                "evidence_package": EvidencePackage(
                    query_id=state.get("query_id", ""), task=task_value,
                    summary="Evidence engine error; see logs.",
                ),
                "errors": [AgentError(code="EVIDENCE_FAILED", message=str(exc), stage="build_evidence")],
            }

        logger.info(
            "build_evidence: %d items, coverage=%.2f, status=%s",
            len(package.items), package.coverage, package.validation_status.value,
        )
        return {"evidence_package": package}

    return build_evidence
