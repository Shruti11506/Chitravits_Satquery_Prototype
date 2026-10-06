"""``SatQueryAgent``: the real agent, implementing the existing ``Agent`` ABC.

Wraps the compiled LangGraph.  ``process`` runs the graph and maps the terminal
``AgentState`` onto the existing ``AgentResponse`` (status + message + structured
``data``), including a client-safe structured error and never a fabricated answer.
"""

from __future__ import annotations

import logging
import time

import httpx

from satquery.agent.graph import build_graph
from satquery.agent.interface import Agent, AgentResponse, AgentStatus
from satquery.agent.state import AgentState, initial_state
from satquery.agent.trace import build_trace
from satquery.agent.tools.attachment_resolver import AttachmentResolver
from satquery.agent.tools.earthmind_client import EarthMindClient
from satquery.config.settings import Settings
from satquery.input.schemas import UserQuery

logger = logging.getLogger(__name__)


def _serialise_analysis(analysis) -> dict:
    """Serialise an ``AnalysisResult`` into JSON-safe structured fields.

    Every item stays traceable to its ``source_tool`` — nothing is merged or
    fabricated across tools.
    """
    return {
        "evidence": [
            {"source_tool": e.source_tool, "claim": e.claim, "data": e.data}
            for e in analysis.evidence
        ],
        "measurements": [
            {"name": m.name, "value": m.value, "unit": m.unit, "source_tool": m.source_tool}
            for m in analysis.measurements
        ],
        "spatial_results": [
            {
                "region_id": s.region_id,
                "change_type": s.change_type,
                "area_ha": s.area_ha,
                "bbox": s.bbox,
                "confidence": s.confidence,
                "source_tool": s.source_tool,
            }
            for s in analysis.spatial_results
        ],
        # Files the models produced (change maps, grounding overlays, derived
        # rasters), each labelled with the tool that wrote it.
        "output_files": [
            {
                "name": f.name,
                "kind": f.kind,
                "url": f.url,
                "path": f.path,
                "media_type": f.media_type,
                "producer": f.producer,
                **({"data_base64": f.data_base64} if f.data_base64 else {}),
            }
            for f in analysis.output_files
        ],
        "tool_results": [
            {
                "tool_name": t.tool_name,
                "status": t.status.value,
                "execution_time_ms": t.execution_time_ms,
                "answer": t.answer,
                "errors": t.errors,
                # Per-tool provenance the UI shows next to the answer.
                "model": t.metadata.get("model"),
                "backend": t.metadata.get("backend"),
                "device": t.metadata.get("device"),
                "confidence": t.metadata.get("confidence"),
                "output_files": [
                    {"name": f.name, "kind": f.kind, "url": f.url, "path": f.path}
                    for f in t.output_files
                ],
            }
            for t in analysis.tool_results
        ],
        "tools_used": analysis.tools_used,
        "tools_failed": analysis.tools_failed,
        "conflicts": analysis.conflicts,
    }


# Evidence type -> map layer type (spec §27 layer types).
_LAYER_TYPE = {
    "change_mask": "change_mask",
    "segmentation_mask": "mask",
    "grounding_box": "bbox",
    "spectral_index": "raster",
    "sar_feature": "raster",
    "sar_otsu": "mask",
    "water_mask": "mask",
}


def _serialise_evidence(package) -> dict:
    """Serialise an ``EvidencePackage`` into the API's evidence + layers fields (spec §42).

    Emitted under dedicated keys so it never collides with the tool-level
    ``evidence`` field produced by ``_serialise_analysis``.
    """
    items = []
    layers = []
    for it in package.items:
        items.append({
            "id": it.id,
            "type": it.type.value,
            "subtype": it.subtype,
            "name": it.name,
            "claim": it.claim,
            "confidence": it.confidence,
            "is_mock": it.is_mock,
            "validation_status": it.validation_status.value,
            "layer_id": it.layer_id,
            "requirement_ids": it.requirement_ids,
            "measurements": [
                {"name": m.name, "value": m.value, "unit": m.unit} for m in it.measurements
            ],
            "checks": [
                {"name": c.name, "status": c.status.value, "detail": c.detail} for c in it.checks
            ],
            "provenance": it.provenance.model_dump(mode="json"),
        })
        if it.layer_id:
            layers.append({
                "id": it.layer_id,
                "name": it.name,
                "type": _LAYER_TYPE.get(it.type.value, "raster"),
                "source": it.provenance.producer,
                "evidence_id": it.id,
            })
    return {
        "evidence_items": items,
        "layers": layers,
        "evidence_requirements": [
            {
                "id": r.id, "description": r.description, "required": r.required,
                "satisfied": r.satisfied, "satisfied_by": r.satisfied_by,
                "expected_types": [t.value for t in r.expected_types],
            }
            for r in package.requirements
        ],
        "evidence_summary": package.summary,
        "evidence_coverage": package.coverage,
        "evidence_status": package.validation_status.value,
        "evidence_conflicts": package.conflicts,
    }


class SatQueryAgent(Agent):
    """LangGraph-backed orchestrator for SatQuery."""

    name = "satquery"

    def __init__(
        self,
        client: EarthMindClient,
        resolver: AttachmentResolver,
        *,
        mcd_mamba_client=None,
        geoground_client=None,
    ) -> None:
        self._client = client
        self._resolver = resolver
        self._mcd_mamba_client = mcd_mamba_client
        self._geoground_client = geoground_client
        self._graph = build_graph(
            client, resolver,
            mcd_mamba_client=mcd_mamba_client,
            geoground_client=geoground_client,
        )

    @property
    def model_clients(self) -> dict:
        """The bound model clients, for connectivity checks and diagnostics."""
        return {
            "earthmind": self._client,
            "mcd_mamba": self._mcd_mamba_client,
            "geoground": self._geoground_client,
        }

    async def process(self, user_query: UserQuery) -> AgentResponse:
        start = time.perf_counter()
        try:
            final: AgentState = await self._graph.ainvoke(initial_state(user_query))
        except Exception:  # noqa: BLE001
            logger.exception("Agent graph crashed for query %s", user_query.query_id)
            return AgentResponse(
                query_id=user_query.query_id,
                session_id=user_query.session_id,
                status=AgentStatus.FAILED,
                message="The agent failed to process the query.",
                data={"error": {"code": "AGENT_INTERNAL_ERROR",
                                "message": "An internal error occurred while processing the query."}},
            )
        processing_time_ms = int((time.perf_counter() - start) * 1000)
        return self._to_response(user_query, final, processing_time_ms=processing_time_ms)

    def _to_response(
        self, user_query: UserQuery, state: AgentState, *, processing_time_ms: int | None = None
    ) -> AgentResponse:
        task = state.get("task")
        errors = state.get("errors") or []
        analysis = state.get("analysis_result")

        data: dict = {
            "task": task.value if task else None,
            "tool_selected": state.get("tool_selected"),
        }
        if processing_time_ms is not None:
            data["processing_time_ms"] = processing_time_ms
        warnings = state.get("warnings") or []
        if warnings:
            data["warnings"] = list(warnings)

        # Evidence engine output travels with every response branch (spec §37, §42).
        evidence_package = state.get("evidence_package")
        if evidence_package is not None:
            data.update(_serialise_evidence(evidence_package))

        if analysis is not None and analysis.tools_used:
            # Extract backward-compat fields from the primary tool result.
            primary = analysis.tool_results[0] if analysis.tool_results else None
            meta = primary.metadata if primary else {}
            data.update({
                "answer": analysis.summary,
                "confidence": state.get("confidence_score"),  # None for single-tool VQA
                "model": meta.get("model"),
                "backend": meta.get("backend"),
                "device": meta.get("device"),
                "latency_ms": meta.get("latency_ms"),
                "timings_ms": meta.get("timings_ms") or {},
            })
            # Structured, traceable fields (the full AnalysisResult, serialised).
            data.update(_serialise_analysis(analysis))
            # MCD-Mamba scalar summaries (kept for direct display).
            if primary and primary.tool_name == "mcd_mamba":
                data.update({
                    "change_area_ha": meta.get("change_area_ha"),
                    "change_fraction": meta.get("change_fraction"),
                })
            data["execution_trace"] = build_trace(
                user_query, state, final_status="completed", final_result=analysis.summary,
            ).model_dump(mode="json")
            return AgentResponse(
                query_id=user_query.query_id,
                session_id=user_query.session_id,
                status=AgentStatus.COMPLETED,
                message=analysis.summary,
                data=data,
            )

        # Legacy path: direct EarthMind result (bypasses new tool layer).
        result = state.get("earthmind_result")
        if result is not None and not errors:
            data.update({
                "answer": result.answer,
                "confidence": result.confidence,
                "model": result.model,
                "backend": result.backend,
                "device": result.device,
                "latency_ms": result.latency_ms,
                "timings_ms": result.timings_ms,
            })
            data["execution_trace"] = build_trace(
                user_query, state, final_status="completed", final_result=result.answer,
            ).model_dump(mode="json")
            return AgentResponse(
                query_id=user_query.query_id,
                session_id=user_query.session_id,
                status=AgentStatus.COMPLETED,
                message=result.answer,
                data=data,
            )

        # Prefer non-preprocessing errors for the primary error code shown to clients.
        actionable = [e for e in errors if e.code != "PREPROCESSING_FAILED"]
        primary_err = actionable[0] if actionable else (errors[0] if errors else None)
        data["error"] = (
            {"code": primary_err.code, "message": primary_err.message}
            if primary_err
            else {"code": "UNKNOWN_ERROR", "message": "The query could not be answered."}
        )
        if len(errors) > 1:
            data["errors"] = [{"code": e.code, "message": e.message, "stage": e.stage} for e in errors]
        data["execution_trace"] = build_trace(
            user_query, state, final_status="failed", final_result=None,
        ).model_dump(mode="json")
        return AgentResponse(
            query_id=user_query.query_id,
            session_id=user_query.session_id,
            status=AgentStatus.FAILED,
            message=data["error"]["message"],
            data=data,
        )

    async def aclose(self) -> None:
        for client in self.model_clients.values():
            if client is not None:
                await client.aclose()


def build_satquery_agent(
    settings: Settings,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> SatQueryAgent:
    """Construct a ``SatQueryAgent`` from settings (used by ``create_app``).

    Every model client's URL, credential, protocol and timeouts come from
    configuration via :mod:`satquery.agent.tools.factory`, so pointing the agent
    at different deployments of the three services needs no code change.
    """
    from satquery.agent.tools.factory import build_model_clients

    clients = build_model_clients(settings, http_client=http_client)
    client = clients["earthmind"]
    if client is None:
        raise ValueError(
            "EarthMind is the agent's required model service: set EARTHMIND_API_URL "
            "(and leave SATQUERY_EARTHMIND_ENABLED unset or true)."
        )

    resolver = AttachmentResolver(
        root=settings.attachment_root,
        allow_http=settings.attachment_allow_http,
    )

    logger.info(
        "SatQuery agent model services: %s",
        ", ".join(
            f"{name}={'on' if c is not None else 'off'}" for name, c in clients.items()
        ),
    )
    return SatQueryAgent(
        client,
        resolver,
        mcd_mamba_client=clients["mcd_mamba"],
        geoground_client=clients["geoground"],
    )
