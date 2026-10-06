"""Build provenance records for evidence items (spec §17, §36).

Provenance is assembled from the physical facts already extracted upstream:
the ``DataProfile`` (CRS, bands, dates, extent, source file) and the
``ToolResult`` metadata (model/tool id, parameters, confidence). Nothing here
infers or invents lineage — it only copies what the pipeline already knows, so
every derived artifact can be traced back to its source raster and transform.
"""

from __future__ import annotations

from datetime import datetime, timezone

from satquery.evidence.schemas import Provenance
from satquery.preprocessor.schemas import DataProfile
from satquery.tools.schemas import ToolResult


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _bands_of(profile: DataProfile) -> list[str]:
    """Human band labels: designation if present, else polarization, else index."""
    labels: list[str] = []
    for b in profile.bands:
        if b.designation:
            labels.append(b.designation.split(" ")[0])  # "B02 (Blue…)" -> "B02"
        elif b.polarization:
            labels.append(b.polarization)
        else:
            labels.append(f"band{b.band_index}")
    return labels


def _extent_of(profile: DataProfile) -> list[float] | None:
    b = profile.bounds_wgs84
    if b is None:
        return None
    return [b.west, b.south, b.east, b.north]


def _crs_of(profile: DataProfile) -> str | None:
    if profile.crs and profile.crs.epsg:
        return f"EPSG:{profile.crs.epsg}"
    return None


def build_provenance(
    evidence_id: str,
    *,
    source_type: str,
    producer: str,
    profiles: list[DataProfile] | None = None,
    tool_result: ToolResult | None = None,
    parameters: dict | None = None,
    confidence: float | None = None,
    transformation: str | None = None,
) -> Provenance:
    """Assemble a Provenance record from the profiles/tool that produced the item.

    ``profiles`` are the DataProfiles that fed the evidence (one for a single
    raster, two for a bi-temporal change item). The first profile drives CRS,
    bands and extent; dates and input ids are collected across all of them.
    """
    profiles = profiles or []
    primary = profiles[0] if profiles else None

    source_file = primary.source_file if primary else None
    source_bands = _bands_of(primary) if primary else []
    crs = _crs_of(primary) if primary else None
    extent = _extent_of(primary) if primary else None
    modality = primary.sensor_modality if primary else None

    dates = [p.acquisition_date for p in profiles if p.acquisition_date]
    input_ids = [p.attachment_id for p in profiles if p.attachment_id]

    params = dict(parameters or {})
    output_path = None
    output_url = None
    output_files: list[dict] = []
    model = None
    if tool_result is not None:
        # Carry forward useful, non-sensitive tool metadata as parameters.
        for key in ("model", "backend", "device", "method", "threshold", "formula",
                    "bands_used", "target", "patch_size", "sar_used", "geo_referenced"):
            if key in tool_result.metadata and tool_result.metadata[key] is not None:
                params.setdefault(key, tool_result.metadata[key])
        # Merge a nested parameters dict (deterministic tools record L, coeffs, …).
        for k, v in (tool_result.metadata.get("parameters") or {}).items():
            params.setdefault(k, v)
        model = tool_result.metadata.get("model")
        output_path = tool_result.metadata.get("output_path")
        # Artifacts a remote model service wrote (change map, grounding overlay).
        for f in tool_result.output_files:
            output_files.append(
                {"name": f.name, "kind": f.kind, "url": f.url, "path": f.path}
            )
            if output_url is None and f.url:
                output_url = f.url
            if output_path is None and f.path:
                output_path = f.path
        if confidence is None:
            confidence = tool_result.metadata.get("confidence")

    # The *inputs* the preprocessor profiled, plus any the tool itself named
    # (the remote change adapter records which attachment was before/after).
    if tool_result is not None:
        for key in ("before_attachment_id", "after_attachment_id", "attachment_id"):
            aid = tool_result.metadata.get(key)
            if isinstance(aid, str) and aid and aid not in input_ids:
                input_ids.append(aid)

    return Provenance(
        evidence_id=evidence_id,
        source_type=source_type,
        producer=producer,
        model=model,
        transformation=transformation,
        source_file=source_file,
        source_bands=source_bands,
        sensor_modality=modality,
        parameters=params,
        crs=crs,
        spatial_extent=extent,
        acquisition_dates=dates,
        input_ids=input_ids,
        output_path=output_path,
        output_url=output_url,
        output_files=output_files,
        confidence=confidence,
        timestamp=_now_iso(),
    )
