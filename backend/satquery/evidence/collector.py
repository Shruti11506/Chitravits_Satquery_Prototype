"""Evidence collector: tool/model outputs -> evidence items (spec §32).

Walks the successful ``ToolResult`` objects (and the DataProfiles that fed
them) and emits one or more ``EvidenceItem`` per output, each carrying full
provenance. Mapping from a tool to an evidence type is explicit and table-
driven so new tools (NDVI, SAR-Otsu, grounding) slot in without touching the
rest of the engine.

The collector does not validate — it only assembles. Validation status is set
later by ``validator.py``; here every item defaults to PASS.
"""

from __future__ import annotations

from satquery.evidence.provenance import build_provenance
from satquery.evidence.schemas import EvidenceItem, EvidenceType, Provenance
from satquery.preprocessor.schemas import DataProfile
from satquery.tools.schemas import ToolResult, ToolStatus

# Tool id -> (evidence type, display name, subtype). Extension point: add a row
# per new deterministic tool or specialist model.
_TOOL_EVIDENCE: dict[str, tuple[EvidenceType, str, str | None]] = {
    "earthmind": (EvidenceType.VQA_ANSWER, "EarthMind Answer", None),
    "mcd_mamba": (EvidenceType.CHANGE_MASK, "MCD-Mamba Change Mask", "change"),
    "ndvi": (EvidenceType.SPECTRAL_INDEX, "NDVI", "ndvi"),
    "ndwi": (EvidenceType.SPECTRAL_INDEX, "NDWI", "ndwi"),
    "mndwi": (EvidenceType.SPECTRAL_INDEX, "MNDWI", "mndwi"),
    "ndbi": (EvidenceType.SPECTRAL_INDEX, "NDBI", "ndbi"),
    "nbr": (EvidenceType.SPECTRAL_INDEX, "NBR", "nbr"),
    "ndmi": (EvidenceType.SPECTRAL_INDEX, "NDMI", "ndmi"),
    "savi": (EvidenceType.SPECTRAL_INDEX, "SAVI", "savi"),
    "evi": (EvidenceType.SPECTRAL_INDEX, "EVI", "evi"),
    "bai": (EvidenceType.SPECTRAL_INDEX, "BAI", "bai"),
    "sar_db": (EvidenceType.SAR_FEATURE, "SAR dB", "db"),
    "vv_vh": (EvidenceType.SAR_FEATURE, "VV/VH Ratio", "vv_vh"),
    "rvi": (EvidenceType.SAR_FEATURE, "RVI", "rvi"),
    "sar_otsu": (EvidenceType.SAR_OTSU, "SAR Otsu Water Mask", "otsu"),
    "geoground": (EvidenceType.GROUNDING_BOX, "GeoGround Detections", None),
}

# Tools backed by model weights (local or remote). Their evidence is recorded
# with ``source_type="model"`` so the provenance panel distinguishes a model
# inference from a deterministic raster computation.
_MODEL_TOOLS = frozenset({"earthmind", "mcd_mamba", "geoground"})

# Which tools consume two dated rasters (drive temporal provenance/evidence).
_BITEMPORAL_TOOLS = frozenset({"mcd_mamba"})

# What each tool did to its input, for the provenance record's
# ``transformation`` field. Stated by the registry/collector, never guessed;
# deterministic tools additionally record their formula in ``parameters``.
_TRANSFORMATIONS: dict[str, str] = {
    "earthmind": "vision-language inference over the image (and any upstream evidence)",
    "mcd_mamba": "bi-temporal change detection over the before/after pair",
    "geoground": "text-guided visual grounding of the requested target",
    "sar_otsu": "SAR backscatter to dB, then Otsu thresholding",
    "sar_db": "SAR backscatter converted to dB",
    "vv_vh": "VV/VH polarimetric ratio",
}


def _transformation_for(tool_name: str, tool: ToolResult) -> str:
    """One phrase describing the transformation this tool applied."""
    if tool_name.endswith("_difference"):
        index = tool_name[: -len("_difference")].upper()
        return f"per-pixel {index} difference between the two dates"
    formula = (tool.metadata or {}).get("formula")
    if isinstance(formula, str) and formula:
        return f"spectral index {formula}"
    return _TRANSFORMATIONS.get(tool_name, f"{tool_name} computation")


def _evidence_kind(tool_name: str) -> tuple[EvidenceType, str, str | None]:
    # Bi-temporal index differences (e.g. "ndvi_difference") are change evidence.
    if tool_name.endswith("_difference"):
        index = tool_name[: -len("_difference")]
        return (EvidenceType.CHANGE_MASK, f"{index.upper()} Difference", index)
    return _TOOL_EVIDENCE.get(tool_name, (EvidenceType.CLAIM, tool_name, None))


def _profiles_for(tool: ToolResult, profiles: list[DataProfile]) -> list[DataProfile]:
    """Pick the DataProfiles relevant to a tool result for provenance."""
    if tool.tool_name in _BITEMPORAL_TOOLS or tool.tool_name.endswith("_difference"):
        before = [p for p in profiles if p.attachment_role == "before"]
        after = [p for p in profiles if p.attachment_role == "after"]
        ordered = before + after
        return ordered or profiles
    return profiles[:1] if profiles else []


def _has_boxes(tool: ToolResult) -> bool:
    return any(s.bbox is not None for s in tool.spatial_results)


def collect_evidence(
    tool_results: list[ToolResult],
    data_profiles: list[DataProfile],
) -> list[EvidenceItem]:
    """Assemble evidence items from successful tool results and their sources."""
    items: list[EvidenceItem] = []
    layer_seq = 0

    for t_index, tool in enumerate(tool_results):
        if tool.status is not ToolStatus.SUCCESS:
            continue

        kind, name, subtype = _evidence_kind(tool.tool_name)
        profiles = _profiles_for(tool, data_profiles)
        confidence = tool.metadata.get("confidence")
        eid = f"ev_{tool.tool_name}_{t_index}"
        is_mock = "mock" in (
            f"{tool.metadata.get('backend', '')} {tool.metadata.get('model', '')}".lower()
        )

        # If a grounding-style tool returns boxes, its primary evidence is the boxes.
        if _has_boxes(tool) and kind not in (EvidenceType.CHANGE_MASK,):
            kind = EvidenceType.GROUNDING_BOX
            name = f"{tool.tool_name} detections"

        # A model tool is "model"-sourced regardless of what it emits: a
        # remote change mask or grounding box still came from model weights.
        is_model_tool = tool.tool_name in _MODEL_TOOLS or kind is EvidenceType.VQA_ANSWER
        prov = build_provenance(
            eid, source_type="model" if is_model_tool else "tool",
            producer=tool.tool_name, profiles=profiles, tool_result=tool, confidence=confidence,
            transformation=_transformation_for(tool.tool_name, tool),
        )

        layer_id = None
        if tool.spatial_results or tool.output_files or kind in (
            EvidenceType.CHANGE_MASK, EvidenceType.SEGMENTATION_MASK,
            EvidenceType.SPECTRAL_INDEX, EvidenceType.SAR_OTSU, EvidenceType.WATER_MASK,
        ):
            layer_id = f"layer_{layer_seq}"
            layer_seq += 1

        items.append(
            EvidenceItem(
                id=eid,
                type=kind,
                subtype=subtype,
                name=name,
                claim=tool.answer or "",
                confidence=confidence,
                is_mock=is_mock,
                measurements=list(tool.measurements),
                spatial=list(tool.spatial_results),
                data={
                    "tool_metadata": tool.metadata,
                    "output_files": [
                        {"name": f.name, "kind": f.kind, "url": f.url, "path": f.path}
                        for f in tool.output_files
                    ],
                },
                provenance=prov,
                layer_id=layer_id,
            )
        )

        # Break out change statistics as their own measurable evidence item (spec §31/§35).
        if tool.measurements and kind in (EvidenceType.CHANGE_MASK,):
            stat_id = f"ev_{tool.tool_name}_{t_index}_stats"
            items.append(
                EvidenceItem(
                    id=stat_id,
                    type=EvidenceType.MEASUREMENT,
                    subtype="change_statistics",
                    name="Change Statistics",
                    claim="; ".join(f"{m.name}={m.value:g} {m.unit}" for m in tool.measurements),
                    measurements=list(tool.measurements),
                    provenance=build_provenance(
                        stat_id, source_type="derived", producer=tool.tool_name,
                        profiles=profiles, tool_result=tool,
                    ),
                )
            )

    # Temporal-comparison evidence when two distinct dated observations exist
    # (bi-temporal tasks) — surfaces the dates as their own evidence item (spec §33).
    dated = [(p, p.acquisition_date) for p in data_profiles if p.acquisition_date]
    if len({d for _p, d in dated}) >= 2:
        tid = "ev_temporal"
        ordered_dates = sorted({d for _p, d in dated})
        items.append(
            EvidenceItem(
                id=tid,
                type=EvidenceType.TEMPORAL_METADATA,
                name="Temporal comparison",
                claim=f"Two comparable observations: {ordered_dates[0]} vs {ordered_dates[-1]}.",
                data={"acquisition_dates": ordered_dates},
                provenance=build_provenance(
                    tid, source_type="raster", producer="input",
                    profiles=[p for p, _d in dated],
                ),
            )
        )

    # One source-image evidence item per input raster (provenance panel, spec §54).
    for p_index, profile in enumerate(data_profiles):
        sid = f"ev_source_{p_index}"
        role = f" ({profile.attachment_role})" if profile.attachment_role else ""
        sat = profile.satellite_identity.satellite if profile.satellite_identity else None
        items.append(
            EvidenceItem(
                id=sid,
                type=EvidenceType.SOURCE_IMAGE,
                name=f"Source image{role}",
                claim=f"{sat or profile.sensor_modality} raster {profile.source_file}",
                data={"modality": profile.sensor_modality, "role": profile.attachment_role},
                provenance=build_provenance(
                    sid, source_type="raster", producer="input",
                    profiles=[profile],
                ),
            )
        )

    return items
