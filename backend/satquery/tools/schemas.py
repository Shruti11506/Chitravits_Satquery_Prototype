"""Tool execution contracts: plans, results, and structured analysis outputs.

Every result must carry: tool_name, status, execution_time_ms, answer/payload,
errors, evidence, and metadata. Evidence is always traceable to the tool that
produced it — never fabricated or merged without labelling the source.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class ToolStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class ToolSpec(BaseModel):
    """A single tool invocation specification inside an ExecutionPlan."""

    tool_name: str          # "earthmind" | "mcd_mamba" | "ndvi" | "sar_otsu" | ...
    task: str               # TaskType value
    attachment_ids: list[str] = Field(default_factory=list)
    primary: bool = True    # False for secondary/corroborating tools
    # How the executor runs this spec: "model" (client call) or a deterministic
    # runner ("spectral" | "sar" | "index_difference" | "grounding").
    op_kind: str = "model"
    params: dict = Field(default_factory=dict)   # band, threshold, index, reason, roles
    reason: str = ""        # why this specific tool was chosen (provenance/debug)
    # Ordering / data-flow within a multi-tool plan.
    order: int = 0          # execution order (ascending); ties may run in parallel
    depends_on: list[str] = Field(default_factory=list)  # tool_names whose output feeds this spec


class ExecutionPlan(BaseModel):
    """What the agent will run and why."""

    tools: list[ToolSpec] = Field(default_factory=list)
    task: str = ""
    reasoning: str = ""     # human-readable explanation of why these tools were selected
    # "single" | "parallel" (optical+SAR) | "sequential" (MCD-Mamba → EarthMind).
    workflow: str = "single"


class Evidence(BaseModel):
    """A single piece of evidence tied to a specific tool's output."""

    source_tool: str
    claim: str
    data: dict = Field(default_factory=dict)


class Measurement(BaseModel):
    """A quantitative measurement from a tool (area, fraction, count, …)."""

    name: str
    value: float
    unit: str
    source_tool: str


class Claim(BaseModel):
    """A semantic claim extracted from tool output."""

    text: str
    source_tool: str
    evidence: list[Evidence] = Field(default_factory=list)
    confidence: float | None = None


class SpatialResult(BaseModel):
    """A geospatial region returned by a tool (change mask, detected object, …)."""

    region_id: str
    change_type: str | None = None   # "increased" | "decreased" | "new" | "removed"
    area_ha: float | None = None
    bbox: list[float] | None = None  # [minx, miny, maxx, maxy] in image coords
    confidence: float | None = None
    source_tool: str = ""


class OutputArtifact(BaseModel):
    """A file a tool or remote model produced (change map, grounding overlay, GeoTIFF).

    ``url`` is an absolute, fetchable location when the producer is a remote
    wrapper API; ``path`` is a local filesystem path when the producer is a
    deterministic in-process tool. ``data_base64`` is only populated when the
    adapter was explicitly configured to inline the bytes, so the common
    response stays small.
    """

    name: str
    kind: str = "image"          # "change_map" | "overlay" | "raster" | "mask" | "image"
    url: str | None = None
    path: str | None = None
    media_type: str | None = None
    producer: str = ""           # tool/model that wrote it
    data_base64: str | None = None


class ToolResult(BaseModel):
    """The full output of one tool invocation.

    This is the agent's single internal result representation: every adapter,
    remote or local, normalises onto it. Fields map one-to-one onto what the
    response and the Evidence Engine expose — tool, status, answer, evidence,
    measurements, spatial information, output files, metadata (model/backend/
    device/confidence), latency and errors.
    """

    tool_name: str
    status: ToolStatus
    execution_time_ms: int
    answer: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    measurements: list[Measurement] = Field(default_factory=list)
    spatial_results: list[SpatialResult] = Field(default_factory=list)
    output_files: list[OutputArtifact] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)  # model, backend, device, latency_ms, timings_ms, …
    errors: list[str] = Field(default_factory=list)


class AnalysisResult(BaseModel):
    """Structured, multi-tool analysis result ready for response generation."""

    summary: str
    claims: list[Claim] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    measurements: list[Measurement] = Field(default_factory=list)
    spatial_results: list[SpatialResult] = Field(default_factory=list)
    output_files: list[OutputArtifact] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)
    tools_used: list[str] = Field(default_factory=list)
    tools_failed: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    confidence: float | None = None
