"""Translate between the backend's job/imagery model and the agent's contracts.

Two directions:
  * ``build_user_query``: an analysis_jobs row (+ its imagery rows) -> the
    agent's ``UserQuery`` (with ``AttachmentRef``s the SupabaseAttachmentResolver
    can resolve by imagery id).
  * ``result_row_from_response`` / ``evidence_rows_from_response``: the agent's
    ``AgentResponse`` -> analysis_results / evidence rows. Every evidence row
    keeps its ``source_tool`` so provenance survives into the database.
"""
from __future__ import annotations

import logging
import re

from satquery.input.schemas import (
    AttachmentKind,
    AttachmentRef,
    ImageModality,
    InputProvenance,
    InputType,
    LanguageSource,
    TemporalRole,
    UserQuery,
)

logger = logging.getLogger(__name__)

_SENSOR_TYPE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

# sat_ AnalysisType -> agent TaskType value. Only concrete, supported mappings
# override the agent's own text classifier; the rest fall through to it.
_ANALYSIS_TO_TASK = {
    "vqa": "vqa",
    "captioning": "visual_analysis",
    "scene_description": "visual_analysis",
    "change_detection": "change_detection",
    "change_vqa": "change_detection",
    # optical_sar_analysis, region_grounding, general_analysis: let the agent
    # classify from the query text (honest UNSUPPORTED_TASK if no tool fits).
}


def _sensor_type(sensor: str | None) -> str | None:
    if not sensor:
        return None
    candidate = sensor.strip().lower()
    return candidate if _SENSOR_TYPE_RE.match(candidate) else None


def _modality(row: dict) -> ImageModality | None:
    """Best-effort modality from sensor/source/metadata; default optical.

    Deliberately conservative: an unknown scene is treated as optical (the
    EarthMind domain) rather than SAR, so a plain "what is visible?" query is
    not misrouted to the unimplemented multispectral path.
    """
    hints = " ".join(
        str(row.get(k) or "")
        for k in ("sensor", "source", "name", "original_filename")
    ).lower()
    if "sentinel-1" in hints or "sentinel1" in hints or "sar" in hints:
        return ImageModality.SAR
    if "hyperspectral" in hints:
        return ImageModality.HYPERSPECTRAL
    if "multispectral" in hints:
        return ImageModality.MULTISPECTRAL
    return ImageModality.OPTICAL


def _attachment(row: dict, role: TemporalRole | None) -> AttachmentRef:
    imagery_id = str(row["id"])
    return AttachmentRef(
        id=imagery_id,
        kind=AttachmentKind.IMAGE,
        type=_sensor_type(row.get("sensor")),
        modality=_modality(row),
        role=role,
        uri=f"satquery://{imagery_id}",
    )


def build_user_query(job: dict, primary: dict, comparison: dict | None) -> UserQuery:
    """Build the agent's UserQuery from a job row and its imagery row(s)."""
    analysis_type = job.get("analysis_type") or "general_analysis"
    is_pair = comparison is not None

    attachments: list[AttachmentRef] = []
    if is_pair:
        # imagery_id = T1 = before (reference), comparison = T2 = after.
        attachments.append(_attachment(primary, TemporalRole.BEFORE))
        attachments.append(_attachment(comparison, TemporalRole.AFTER))
    else:
        attachments.append(_attachment(primary, None))

    session_id = str(job.get("conversation_id") or job["id"])
    metadata: dict = {}
    task_override = _ANALYSIS_TO_TASK.get(analysis_type)
    if task_override:
        metadata["task"] = task_override

    return UserQuery(
        query=job.get("query") or "",
        input_type=InputType.TEXT,
        language="en",
        session_id=session_id,
        attachments=tuple(attachments),
        metadata=metadata,
        provenance=InputProvenance(
            language_source=LanguageSource.DEFAULT,
            session_generated=False,
        ),
    )


def result_row_from_response(job: dict, response) -> dict:
    """analysis_results row from a completed AgentResponse."""
    data = response.data or {}
    return {
        "job_id": str(job["id"]),
        "answer": data.get("answer") or response.message,
        "confidence": data.get("confidence"),
        "model_name": data.get("model") or data.get("tool_selected"),
        "analysis_type": job.get("analysis_type"),
        "raw_output": data,  # full structured payload (JSON-safe primitives)
    }


def evidence_rows_from_response(result_id: str, response) -> list[dict]:
    """evidence rows from a completed AgentResponse, provenance preserved."""
    data = response.data or {}
    rows: list[dict] = []

    for e in data.get("evidence", []) or []:
        rows.append({
            "result_id": result_id,
            "evidence_type": "claim",
            "description": e.get("claim"),
            "source_reference": e.get("source_tool"),
            "metadata": e.get("data") or {},
        })

    for s in data.get("spatial_results", []) or []:
        change_type = s.get("change_type")
        area_ha = s.get("area_ha")
        desc = f"{change_type} ({area_ha} ha)" if change_type else s.get("region_id")
        rows.append({
            "result_id": result_id,
            "evidence_type": "change_region",
            "description": desc,
            "source_reference": s.get("source_tool"),
            "bbox": {"bbox": s.get("bbox")} if s.get("bbox") else None,
            "confidence": s.get("confidence"),
            "metadata": {
                "region_id": s.get("region_id"),
                "area_ha": area_ha,
                "change_type": change_type,
            },
        })

    for m in data.get("measurements", []) or []:
        rows.append({
            "result_id": result_id,
            "evidence_type": "measurement",
            "description": f"{m.get('name')} = {m.get('value')} {m.get('unit')}",
            "source_reference": m.get("source_tool"),
            "metadata": m,
        })

    # Files the models produced (change maps, grounding overlays): one evidence
    # row each, carrying the fetchable URL so the frontend can show the image.
    for f in data.get("output_files", []) or []:
        rows.append({
            "result_id": result_id,
            "evidence_type": "output_file",
            "description": f"{f.get('kind', 'image')} produced by {f.get('producer')}",
            "source_reference": f.get("producer"),
            "metadata": {
                "name": f.get("name"),
                "kind": f.get("kind"),
                "url": f.get("url"),
                "path": f.get("path"),
                "media_type": f.get("media_type"),
            },
        })

    return rows
