"""Result aggregator: converts a list of ToolResults into a structured AnalysisResult.

Rules:
- Each tool's output is preserved as a separate source; never fabricate agreement.
- Conflicts are noted when two tools make contradictory claims.
- The summary is built from successful tools; failed tools are noted separately.
"""

from __future__ import annotations

from satquery.tools.schemas import (
    AnalysisResult,
    Claim,
    Evidence,
    Measurement,
    OutputArtifact,
    SpatialResult,
    ToolResult,
    ToolStatus,
)


def aggregate(tool_results: list[ToolResult], user_query: str) -> AnalysisResult:
    """Build an AnalysisResult from a list of ToolResult objects."""
    succeeded = [r for r in tool_results if r.status == ToolStatus.SUCCESS]
    failed = [r for r in tool_results if r.status == ToolStatus.FAILED]

    tools_used = [r.tool_name for r in succeeded]
    tools_failed = [r.tool_name for r in failed]

    # Gather all evidence, measurements, spatial results — labelled by source_tool.
    all_evidence: list[Evidence] = []
    all_measurements: list[Measurement] = []
    all_spatial: list[SpatialResult] = []
    all_outputs: list[OutputArtifact] = []
    claims: list[Claim] = []

    for r in succeeded:
        all_evidence.extend(r.evidence)
        all_measurements.extend(r.measurements)
        all_spatial.extend(r.spatial_results)
        all_outputs.extend(r.output_files)

        if r.answer:
            claim = Claim(
                text=r.answer,
                source_tool=r.tool_name,
                evidence=list(r.evidence),
                confidence=r.metadata.get("confidence"),
            )
            claims.append(claim)

    # Build summary from successful tool answers.
    if succeeded:
        if len(succeeded) == 1:
            summary = succeeded[0].answer or "(no answer)"
        else:
            parts = [f"[{r.tool_name}] {r.answer}" for r in succeeded if r.answer]
            summary = "\n\n".join(parts) if parts else "(no answers from tools)"
    else:
        # All tools failed — collect errors for the summary.
        error_msgs = [e for r in failed for e in r.errors]
        summary = "; ".join(error_msgs) if error_msgs else "All tools failed to produce an answer."

    # Detect conflicts (simple: >1 tool, different summaries).
    conflicts: list[str] = []
    if len(succeeded) > 1:
        unique_answers = {r.answer for r in succeeded if r.answer}
        if len(unique_answers) > 1:
            conflicts.append(
                f"Tools {[r.tool_name for r in succeeded]} produced different answers; "
                "results presented independently above."
            )

    return AnalysisResult(
        summary=summary,
        claims=claims,
        evidence=all_evidence,
        measurements=all_measurements,
        spatial_results=all_spatial,
        output_files=all_outputs,
        tool_results=tool_results,
        tools_used=tools_used,
        tools_failed=tools_failed,
        conflicts=conflicts,
        confidence=None,  # set by confidence.py after aggregation
    )
