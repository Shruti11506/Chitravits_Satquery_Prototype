"""Signal-based confidence scoring — no LLM-generated percentages.

Signals used:
  1. tool_success_rate: fraction of planned tools that succeeded.
  2. data_quality: mean valid_pixel_ratio across DataProfiles (None if no profiles).
  3. evidence_density: at least one measurement or spatial result raises confidence.
  4. inter_tool_agreement: multiple tools, no conflicts → small boost.

Returns None when there is nothing meaningful to score (e.g. single tool, no
measurements, no quality signal).  The EarthMind VQA path always returns None
because the model provides no calibrated score and there is only one tool.
"""

from __future__ import annotations

from satquery.tools.schemas import AnalysisResult, ToolResult, ToolStatus


def compute_confidence(
    tool_results: list[ToolResult],
    data_profiles: list,  # list[DataProfile] — not typed here to avoid circular import
    analysis_result: AnalysisResult,
) -> float | None:
    """Return a [0, 1] confidence score or None if no reliable signal exists."""
    if not tool_results:
        return None

    succeeded = [r for r in tool_results if r.status == ToolStatus.SUCCESS]
    if not succeeded:
        return None

    # Single tool with no measurements/spatial info: no meaningful confidence.
    has_measurements = bool(analysis_result.measurements)
    has_spatial = bool(analysis_result.spatial_results)
    multi_tool = len(succeeded) > 1

    if not multi_tool and not has_measurements and not has_spatial:
        return None

    # --- Build score from signals ---

    # Signal 1: tool success rate.
    success_rate = len(succeeded) / len(tool_results)

    # Signal 2: data quality from DataProfiles.
    valid_ratios = [
        p.quality.valid_pixel_ratio
        for p in data_profiles
        if hasattr(p, "quality") and p.quality.valid_pixel_ratio is not None
    ]
    data_quality = sum(valid_ratios) / len(valid_ratios) if valid_ratios else 1.0

    # Signal 3: evidence density (spatial results, measurements).
    evidence_bonus = 0.05 if (has_measurements or has_spatial) else 0.0

    # Signal 4: inter-tool agreement.
    agreement_bonus = 0.0
    if multi_tool and not analysis_result.conflicts:
        agreement_bonus = 0.05

    score = success_rate * 0.5 + data_quality * 0.4 + evidence_bonus + agreement_bonus
    return min(round(score, 3), 1.0)
