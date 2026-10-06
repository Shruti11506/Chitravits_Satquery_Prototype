"""Evidence Engine orchestrator (spec §32).

    QUERY
      ↓  planner        -> evidence requirements
      ↓  collector      -> evidence items (+ provenance)
      ↓  validator      -> per-item PASS/WARNING/FAIL + cross-item consistency
      ↓  fusion         -> requirements linked, coverage, ordered items
    EVIDENCE PACKAGE    -> handed to the answer generator

This is the single entry point the LangGraph node calls. It is pure and
synchronous — no I/O, no model calls — so it is trivially unit-testable with
constructed ToolResults and DataProfiles.
"""

from __future__ import annotations

from satquery.evidence.collector import collect_evidence
from satquery.evidence.fusion import fuse, summarize
from satquery.evidence.planner import plan_requirements
from satquery.evidence.schemas import EvidencePackage
from satquery.evidence.validator import cross_validate, validate_item
from satquery.preprocessor.schemas import AOIContext, DataProfile
from satquery.tools.schemas import AnalysisResult, ToolResult


def build_evidence_package(
    *,
    query_id: str,
    task: str,
    query_text: str,
    tool_results: list[ToolResult],
    data_profiles: list[DataProfile] | None = None,
    aoi_contexts: list[AOIContext] | None = None,
    analysis_result: AnalysisResult | None = None,
) -> EvidencePackage:
    """Run the full evidence pipeline and return a validated EvidencePackage."""
    data_profiles = data_profiles or []
    aoi_contexts = aoi_contexts or []

    requirements = plan_requirements(task, query_text)
    items = collect_evidence(tool_results, data_profiles)

    for item in items:
        validate_item(item, aoi_contexts)

    conflicts = cross_validate(items)
    if analysis_result is not None:
        conflicts = list(dict.fromkeys(conflicts + list(analysis_result.conflicts)))

    requirements, ordered, coverage, overall = fuse(requirements, items, conflicts)

    # Confidence is carried through from the signal-based analysis score only —
    # the evidence engine never invents a number (spec §34).
    confidence = analysis_result.confidence if analysis_result is not None else None

    return EvidencePackage(
        query_id=query_id,
        task=task,
        summary=summarize(ordered, requirements),
        requirements=requirements,
        items=ordered,
        conflicts=conflicts,
        coverage=coverage,
        validation_status=overall,
        confidence=confidence,
    )
