"""Tool registry: capability and input-requirement declarations for each tool.

The registry is static config, not runtime state. It is the single place that
states, for every tool the agent can run:

* which classified tasks it handles,
* what it is actually able to do (``capabilities``),
* what inputs it requires (image count, temporal pair, modality, named request
  parts) and what it accepts optionally.

The planner consults this before selecting a tool, and the permitted-parameter
allow-list in :mod:`satquery.tools.params` constrains what may be passed to it.
Together they stop a planner — rule-based today, LLM-driven later — from
inventing a tool capability or an API parameter the service does not have.

Adding a tool means adding an entry here, a parameter schema in ``params.py``,
and a handler in the executor.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ToolCapability:
    """What one tool can do and what it needs to do it."""

    tasks: frozenset[str]           # TaskType.value strings this tool handles
    requires_image: bool            # must have at least one image attachment
    requires_temporal_pair: bool = False  # must have both "before" and "after"
    supported_modalities: frozenset[str] = field(
        default_factory=frozenset
    )  # empty = any modality accepted

    # --- declared capabilities and input contract -------------------------
    # Free of wire details on purpose: the adapters own the HTTP schema, this
    # records what the tool is for and what the agent must supply.
    capabilities: frozenset[str] = field(default_factory=frozenset)
    description: str = ""
    kind: str = "model"             # "model" (remote inference) | "deterministic"
    min_images: int = 1
    max_images: int | None = None
    # Named inputs the tool's adapter requires / may use. These are agent-level
    # concepts ("before image", "target expression"), not HTTP field names.
    required_inputs: frozenset[str] = field(default_factory=frozenset)
    optional_inputs: frozenset[str] = field(default_factory=frozenset)
    # True when the tool can additionally consume a co-registered SAR pair.
    accepts_sar_pair: bool = False
    # Artifacts the tool may produce, so the response/evidence layers know what
    # to expect without probing.
    produces: frozenset[str] = field(default_factory=frozenset)


# --- Registry entries (tool_name -> capability) ---------------------------
# Order matters: ``tool_for_task`` returns the first *available* tool whose
# task set matches, so the specialist is listed before the generalist.
# GeoGround therefore wins "grounding" when it is configured, and EarthMind
# remains the fallback when it is not.

TOOL_REGISTRY: dict[str, ToolCapability] = {
    "geoground": ToolCapability(
        tasks=frozenset({"grounding"}),
        requires_image=True,
        requires_temporal_pair=False,
        capabilities=frozenset({
            "text_guided_visual_grounding",
            "referring_segmentation",
            "oriented_bounding_boxes",
            "geo_referenced_detections",   # only when the input carries a CRS
            "scene_captioning",            # optional, off by default
        }),
        description=(
            "Text-guided visual grounding and segmentation for remote-sensing "
            "imagery. Localises a natural-language target expression as pixel "
            "boxes, oriented boxes and masks, with geographic coordinates when "
            "the input raster is georeferenced."
        ),
        min_images=1,
        max_images=1,
        required_inputs=frozenset({"image", "target_expression"}),
        optional_inputs=frozenset({"max_points", "generate_caption"}),
        produces=frozenset({"bounding_boxes", "segmentation_mask", "overlay_image"}),
    ),
    "earthmind": ToolCapability(
        tasks=frozenset({
            "vqa", "visual_analysis", "grounding",
            "multispectral_analysis", "cross_modal_analysis",
        }),
        requires_image=True,
        requires_temporal_pair=False,
        capabilities=frozenset({
            "single_image_vqa",
            "satellite_image_understanding",
            "scene_description",
            "change_evidence_interpretation",  # reads an upstream change result
        }),
        description=(
            "Single-image visual question answering and scene understanding for "
            "satellite imagery. Also used as the interpretation step for a "
            "detected change: it turns another tool's change evidence into a "
            "natural-language reading, and never performs the detection itself."
        ),
        min_images=1,
        max_images=1,
        required_inputs=frozenset({"image", "query"}),
        optional_inputs=frozenset({"upstream_evidence"}),
        produces=frozenset({"answer"}),
    ),
    "mcd_mamba": ToolCapability(
        tasks=frozenset({"change_detection"}),
        requires_image=True,
        requires_temporal_pair=True,  # needs before + after pair
        capabilities=frozenset({
            "bi_temporal_change_detection",
            "change_map_generation",
            "change_area_statistics",
            "multimodal_optical_sar_change",  # SAR branch, when a SAR pair is supplied
        }),
        description=(
            "Bi-temporal change detection (STMambaBCD, multimodal). Consumes a "
            "pre-change and a post-change optical image — optionally plus a "
            "co-registered SAR pair — and produces a change map with pixel-level "
            "change statistics. It detects change; it does not explain it."
        ),
        min_images=2,
        max_images=4,                 # optical pair + optional SAR pair
        required_inputs=frozenset({"before_image", "after_image"}),
        optional_inputs=frozenset({"sar_before_image", "sar_after_image", "patch_size", "stride"}),
        accepts_sar_pair=True,
        produces=frozenset({"change_map", "change_statistics"}),
    ),
}


def tool_for_task(task: str, available: frozenset[str]) -> str | None:
    """Return the first registered tool that handles ``task`` and is in ``available``."""
    for name, cap in TOOL_REGISTRY.items():
        if name in available and task in cap.tasks:
            return name
    return None


def capability_card(tool_name: str) -> dict | None:
    """Registry + permitted parameters for one tool, as a JSON-safe dict.

    Used by ``GET /api/v1/models/health`` so operators and the frontend can see
    exactly which capabilities and parameters the agent will honour, instead of
    inferring them from code.
    """
    cap = TOOL_REGISTRY.get(tool_name)
    if cap is None:
        return None
    from satquery.tools.params import schema_for

    return {
        "tool": tool_name,
        "kind": cap.kind,
        "description": cap.description,
        "tasks": sorted(cap.tasks),
        "capabilities": sorted(cap.capabilities),
        "inputs": {
            "required": sorted(cap.required_inputs),
            "optional": sorted(cap.optional_inputs),
            "min_images": cap.min_images,
            "max_images": cap.max_images,
            "requires_temporal_pair": cap.requires_temporal_pair,
            "accepts_sar_pair": cap.accepts_sar_pair,
            "supported_modalities": sorted(cap.supported_modalities) or ["any"],
        },
        "permitted_parameters": sorted(schema_for(tool_name).allowed),
        "produces": sorted(cap.produces),
    }
