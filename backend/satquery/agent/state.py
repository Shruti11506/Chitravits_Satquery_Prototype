"""Typed state for the SatQuery LangGraph agent.

``AgentState`` is the single object threaded through the graph. It is a
``TypedDict`` (LangGraph merges the partial dict each node returns) whose values
are themselves typed pydantic models -- no free-form dictionaries carrying
meaning. ``errors`` uses an ``add`` reducer so any node can append without
clobbering earlier entries.
"""

from __future__ import annotations

import operator
from enum import StrEnum
from typing import Annotated, TypedDict

from pydantic import BaseModel, Field

from satquery.evidence.schemas import EvidencePackage
from satquery.input.schemas import AttachmentRef, UserQuery
from satquery.preprocessor.schemas import AOIContext, DataProfile
from satquery.tools.schemas import AnalysisResult, ExecutionPlan, ToolResult


class TaskType(StrEnum):
    """The remote-sensing task the router classified the query as.

    Only VQA and VISUAL_ANALYSIS route to EarthMind today. The rest are declared
    so the router can name them and so callers get an honest UNSUPPORTED result,
    but they are extension points, not implemented capabilities.
    """

    VQA = "vqa"
    VISUAL_ANALYSIS = "visual_analysis"
    MULTISPECTRAL_ANALYSIS = "multispectral_analysis"  # extension point
    CROSS_MODAL_ANALYSIS = "cross_modal_analysis"  # optical + SAR joint analysis (parallel)
    CHANGE_DETECTION = "change_detection"  # bi-temporal change (MCD-Mamba)
    GROUNDING = "grounding"  # extension point (not implemented)
    UNKNOWN = "unknown"


# Tasks that currently reach the EarthMind RGB VQA backend.
EARTHMIND_TASKS = frozenset({TaskType.VQA, TaskType.VISUAL_ANALYSIS})


class AgentError(BaseModel):
    """A structured, client-safe error captured during graph execution."""

    code: str
    message: str
    stage: str | None = None  # which node produced it (understand_query, earthmind_tool, ...)


class EarthMindResult(BaseModel):
    """The parsed, structured result of a successful EarthMind inference call."""

    task: str
    answer: str
    confidence: float | None = None  # None unless a calibrated score exists
    model: str
    device: str | None = None
    backend: str | None = None
    latency_ms: int | None = None
    timings_ms: dict[str, int] = Field(default_factory=dict)


class AgentState(TypedDict, total=False):
    """State passed between LangGraph nodes. All keys optional; nodes fill what they own."""

    # Inputs (set before the graph runs)
    user_query: UserQuery
    query_text: str
    session_id: str
    query_id: str

    # Routing / planning
    task: TaskType
    tool_selected: str | None
    image_ref: AttachmentRef | None

    # Input/task compatibility check (runs before tool selection)
    compatibility_ok: bool
    warnings: Annotated[list[str], operator.add]

    # Preprocessing output (one entry per raster/vector attachment)
    data_profiles: list[DataProfile]
    aoi_contexts: list[AOIContext]

    # Tool output (legacy EarthMind direct result — kept for backward compat)
    earthmind_result: EarthMindResult | None
    confidence: float | None
    latency_ms: int | None
    timings_ms: dict[str, int]

    # Tool layer (new pipeline: plan_tools → execute_tools → aggregate_results)
    execution_plan: ExecutionPlan | None
    tool_results: list[ToolResult]
    analysis_result: AnalysisResult | None
    confidence_score: float | None  # signal-based; distinct from model-emitted confidence

    # Evidence layer (build_evidence node: planner → collector → validator → fusion)
    evidence_package: EvidencePackage | None

    # Outcome
    errors: Annotated[list[AgentError], operator.add]
    final_answer: str | None
    completed: bool


def initial_state(user_query: UserQuery) -> AgentState:
    """Seed the graph state from a normalised ``UserQuery``."""
    return AgentState(
        user_query=user_query,
        query_text=user_query.query,
        session_id=user_query.session_id,
        query_id=user_query.query_id,
        task=TaskType.UNKNOWN,
        tool_selected=None,
        image_ref=None,
        compatibility_ok=True,
        warnings=[],
        data_profiles=[],
        aoi_contexts=[],
        earthmind_result=None,
        confidence=None,
        latency_ms=None,
        timings_ms={},
        execution_plan=None,
        tool_results=[],
        analysis_result=None,
        confidence_score=None,
        evidence_package=None,
        errors=[],
        final_answer=None,
        completed=False,
    )


def first_image_attachment(user_query: UserQuery) -> AttachmentRef | None:
    """Pick the attachment EarthMind should look at: the first image-kind ref, else the first ref."""
    images = [a for a in user_query.attachments if a.kind.value == "image"]
    if images:
        return images[0]
    return user_query.attachments[0] if user_query.attachments else None
