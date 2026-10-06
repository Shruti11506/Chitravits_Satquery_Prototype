"""Auditable execution trace (mentor requirements #9 and #10).

A single, structured, client-safe summary of what the agent did — never the
model's chain-of-thought. It exposes exactly the fields the spec enumerates:
selected task, input summary, selected model/tool, tool execution order, key
permitted parameters, tool status, outputs/evidence generated, confidence, final
result, and warnings/errors.

Everything here is derived from the terminal ``AgentState`` (plan, tool results,
evidence package). The design rationale strings it carries (``reason``,
``workflow``) are structured provenance, not free-form reasoning.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from satquery.agent.state import AgentState, TaskType
from satquery.input.schemas import UserQuery
from satquery.tools.schemas import ToolStatus


class InputSummary(BaseModel):
    image_count: int = 0
    vector_count: int = 0
    modalities: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    formats: list[str] = Field(default_factory=list)
    timestamps: list[str] = Field(default_factory=list)


class ToolTraceEntry(BaseModel):
    order: int
    tool_name: str
    op_kind: str
    reason: str = ""
    depends_on: list[str] = Field(default_factory=list)
    permitted_parameters: dict = Field(default_factory=dict)
    status: str = "planned"          # planned | success | failed | skipped
    execution_time_ms: int | None = None
    error: str | None = None


class TraceError(BaseModel):
    code: str
    message: str
    stage: str | None = None


class ExecutionTrace(BaseModel):
    """The auditable record travelling in the response as ``data.execution_trace``."""

    query_id: str
    session_id: str
    selected_task: str
    workflow: str = "single"
    input_summary: InputSummary
    selected_tools: list[str] = Field(default_factory=list)
    tool_execution_order: list[ToolTraceEntry] = Field(default_factory=list)
    outputs: dict = Field(default_factory=dict)
    confidence: float | None = None
    final_status: str = "unknown"    # completed | failed
    final_result: str | None = None
    warnings: list[str] = Field(default_factory=list)
    errors: list[TraceError] = Field(default_factory=list)


def _input_summary(user_query: UserQuery) -> InputSummary:
    from pathlib import Path
    from urllib.parse import urlparse

    images = [a for a in user_query.attachments if a.kind.value == "image"]
    vectors = [a for a in user_query.attachments if a.kind.value == "vector"]
    formats: list[str] = []
    for a in user_query.attachments:
        if a.uri:
            suffix = Path(urlparse(a.uri).path).suffix.lstrip(".").lower()
            if suffix:
                formats.append(suffix)
    return InputSummary(
        image_count=len(images),
        vector_count=len(vectors),
        modalities=sorted({a.modality.value for a in images if a.modality is not None}),
        roles=sorted({a.role.value for a in images if a.role is not None}),
        formats=sorted(set(formats)),
        timestamps=[str(a.timestamp) for a in images if a.timestamp is not None],
    )


def build_trace(
    user_query: UserQuery,
    state: AgentState,
    *,
    final_status: str,
    final_result: str | None,
) -> ExecutionTrace:
    """Assemble the execution trace from the terminal graph state."""
    task: TaskType | None = state.get("task")
    plan = state.get("execution_plan")
    analysis = state.get("analysis_result")
    evidence_pkg = state.get("evidence_package")

    # Match planned specs to their results (results preserve execution order).
    results = list(analysis.tool_results) if analysis else []
    entries: list[ToolTraceEntry] = []
    specs = sorted(plan.tools, key=lambda s: s.order) if plan else []
    positional = len(specs) == len(results)
    for i, spec in enumerate(specs):
        res = results[i] if positional else next(
            (r for r in results if r.tool_name == spec.tool_name), None
        )
        entries.append(ToolTraceEntry(
            order=spec.order,
            tool_name=spec.tool_name,
            op_kind=spec.op_kind,
            reason=spec.reason,
            depends_on=list(spec.depends_on),
            permitted_parameters=dict(spec.params),
            status=res.status.value if res else "planned",
            execution_time_ms=res.execution_time_ms if res else None,
            error=(res.errors[0] if (res and res.status == ToolStatus.FAILED and res.errors) else None),
        ))

    outputs: dict = {}
    if analysis is not None:
        outputs.update({
            "tools_used": analysis.tools_used,
            "tools_failed": analysis.tools_failed,
            "measurements": len(analysis.measurements),
            "spatial_results": len(analysis.spatial_results),
            "evidence_claims": len(analysis.evidence),
            "conflicts": analysis.conflicts,
        })
    if evidence_pkg is not None:
        outputs.update({
            "evidence_items": len(evidence_pkg.items),
            "evidence_status": evidence_pkg.validation_status.value,
            "evidence_coverage": evidence_pkg.coverage,
            "layers": [it.layer_id for it in evidence_pkg.items if it.layer_id],
        })

    errors = [
        TraceError(code=e.code, message=e.message, stage=e.stage)
        for e in (state.get("errors") or [])
    ]

    return ExecutionTrace(
        query_id=state.get("query_id") or user_query.query_id,
        session_id=state.get("session_id") or user_query.session_id,
        selected_task=task.value if task else "unknown",
        workflow=plan.workflow if plan else "single",
        input_summary=_input_summary(user_query),
        selected_tools=[s.tool_name for s in specs],
        tool_execution_order=entries,
        outputs=outputs,
        confidence=state.get("confidence_score"),
        final_status=final_status,
        final_result=final_result,
        warnings=list(state.get("warnings") or []),
        errors=errors,
    )
