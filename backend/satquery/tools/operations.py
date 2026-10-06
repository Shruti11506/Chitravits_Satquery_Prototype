"""Query-driven operation planner (Tools.docx §26, spec principle).

Decides which *deterministic* tools a query needs — and, crucially, which it
does NOT. It never runs "every index because the image is multispectral":
it maps the specific intent (vegetation / water / built-up / burn / SAR flood /
grounding / explicit index) to the minimal set of feasible tools, gated by the
bands and modality actually available.

Returns a list of ``ToolSpec`` (possibly empty). An empty list means "no
deterministic tool applies — let the model path handle it" (e.g. a general
"what is visible?" VQA, or a general "what changed?" that belongs to
MCD-Mamba). The ``plan_tools`` node calls this first and only falls back to the
model selector when it returns nothing.
"""

from __future__ import annotations

import re

from satquery.tools.compute.runner import SPECTRAL_TOOLS
from satquery.tools.raster.bands import BandResolver
from satquery.tools.schemas import ToolSpec

# --- intent cues -----------------------------------------------------------
_EXPLICIT_INDEX = re.compile(r"\b(ndvi|ndwi|mndwi|ndbi|ndmi|nbr|savi|evi|bai)\b", re.IGNORECASE)
_VEG = re.compile(r"\b(vegetation|crop|forest|greenery|canopy|plant|foliage|ndvi)\b", re.IGNORECASE)
_WATER = re.compile(r"\b(water|flood|flooded|lake|river|inundat\w*|wetland|coastline)\b", re.IGNORECASE)
_BUILTUP = re.compile(r"\b(built.?up|urban|building|settlement|city|impervious|ndbi)\b", re.IGNORECASE)
_BURN = re.compile(r"\b(burn\w*|fire|wildfire|scar|nbr)\b", re.IGNORECASE)
_MOISTURE = re.compile(r"\b(moisture|water content|canopy water|ndmi)\b", re.IGNORECASE)
_SAR_WORD = re.compile(r"\b(sar|radar|backscatter|otsu|vv|vh|sentinel.?1)\b", re.IGNORECASE)
# Grounding / detection is an explicit *spatial* action: localise, outline, or
# return boxes for something. It is NOT triggered by a natural-language question
# that merely names an object ("how many airplanes?", "are there airplanes?",
# "describe the airplanes") -- those are VQA and belong to EarthMind. These cues
# are kept in step with the router's ``_GROUNDING_CUES`` so classification and
# planning never disagree.
_GROUNDING = re.compile(
    r"\b("
    r"where (is|are)|locate|locali[sz]\w*|pinpoint|highlight|delineate|"
    r"outline the|mark the|segment the|segment all|show me where|"
    r"identify (the )?location|bounding box(es)?|"
    r"detect (the|all|every)|object detection|return bounding box|find (the|all)"
    r")\b",
    re.IGNORECASE,
)
_DECREASE = re.compile(r"\b(decrease|loss|lost|decline|reduc\w*|less)\b", re.IGNORECASE)

# Phrasings that introduce the *target* of a grounding request; group 1 is the
# target expression. Ordered most-specific first. ("how many ...?" is NOT here:
# it is a VQA/counting question routed to EarthMind, not a grounding target.)
_TARGET_PATTERNS = (
    re.compile(r"\bbounding box(?:es)?\s+(?:around|for|of|on)\s+(?:the\s+)?(.+)", re.IGNORECASE),
    re.compile(
        r"\bshow me where\s+(?:the\s+|a\s+|an\s+)?(.+?)\s*(?:are|is)?\s*[?.!]*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bidentify\s+(?:the\s+)?location\s+of\s+(?:the\s+|a\s+|an\s+|all\s+(?:the\s+)?)?(.+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bwhere\s+(?:is|are)\s+(?:the\s+|a\s+|an\s+|all\s+(?:the\s+)?)?(.+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:highlight|locate|locali[sz]e|pinpoint|delineate|segment|outline|mark|"
        r"detect|find|identify|show(?:\s+me)?)\s+"
        r"(?:the\s+|a\s+|an\s+|all\s+(?:the\s+)?|any\s+)?(.+)",
        re.IGNORECASE,
    ),
)

# A bare object-detection request names no object; GeoGround still needs a
# target, so a generic one is used rather than passing the instruction verbatim.
_BARE_OBJECT_DETECTION = re.compile(
    r"^\s*(?:please\s+)?(?:perform|run|do)\s+object\s+detection\b", re.IGNORECASE
)

# Trailing scene references that are not part of the target expression.
_TARGET_TAIL = re.compile(
    r"\s*\b(?:in|on|within|from|for)\s+(?:this|the|that)\s+"
    r"(?:satellite\s+|aerial\s+|input\s+)?"
    r"(?:image|imagery|scene|photo|raster|picture|tile|area)\b.*$",
    re.IGNORECASE,
)
_TARGET_NOISE = re.compile(
    r"\b(?:(?:are|is)\s+there|and\s+(?:return|give|draw|show)\b.*|"
    r"and\s+bounding\s+box.*)\b.*$",
    re.IGNORECASE,
)
_TARGET_STRIP = " \t\n.,;:!?\"'()[]/"


def extract_grounding_target(query_text: str) -> str:
    """Pull the target expression out of a grounding query.

    GeoGround is driven by a natural-language *target* ("buildings", "water
    bodies"), not by the whole question, so the phrasing around it is stripped.
    The rules are deliberately transparent; when none matches, the query is
    passed through unchanged rather than guessing at a target.
    """
    text = (query_text or "").strip()
    if not text:
        return ""
    if _BARE_OBJECT_DETECTION.search(text):
        return "objects"
    for pattern in _TARGET_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        target = _TARGET_NOISE.sub("", _TARGET_TAIL.sub("", match.group(1)))
        target = target.strip(_TARGET_STRIP)
        if target:
            return target
    return _TARGET_TAIL.sub("", text).strip(_TARGET_STRIP) or text


def _modality(data_profiles: list, image_ref) -> str:
    if data_profiles:
        return (data_profiles[0].sensor_modality or "").lower()
    if image_ref is not None and getattr(image_ref, "modality", None) is not None:
        return image_ref.modality.value.lower()
    return ""


def _roles(data_profiles: list) -> dict[str, str]:
    """attachment_id -> role for profiles that carry before/after."""
    return {p.attachment_id: p.attachment_role for p in data_profiles if p.attachment_role}


def _has_temporal_pair(data_profiles: list) -> bool:
    roles = {p.attachment_role for p in data_profiles if p.attachment_role}
    return {"before", "after"} <= roles


def _feasible(index: str, profile) -> bool:
    """Can this spectral index's bands be resolved from the profile?"""
    if profile is None:
        return True  # unknown bands -> let the runner try / report missing
    required = SPECTRAL_TOOLS[index][0]
    resolver = BandResolver.from_profile(profile)
    return all(resolver.index_of(b) is not None for b in required)


def _spectral_spec(index: str, task: str, ids: list[str], reason: str) -> ToolSpec:
    return ToolSpec(tool_name=index, task=task, attachment_ids=ids,
                    op_kind="spectral", reason=reason)


def _first_ids(image_ref, data_profiles) -> list[str]:
    if image_ref is not None:
        return [image_ref.id]
    return [data_profiles[0].attachment_id] if data_profiles else []


def plan_operations(
    query_text: str,
    task: str,
    data_profiles: list,
    image_ref,
    available_tools: frozenset[str] = frozenset(),
) -> list[ToolSpec]:
    """Return the ToolSpecs a query needs (or [] to defer to the model selector).

    ``available_tools`` names the model services actually wired up. It only
    affects grounding: with the real GeoGround service configured the request
    becomes a model call; without it, the clearly-labelled mock grounding op
    runs so the spatial pipeline still exercises end-to-end.

    The classified ``task`` (the user's *intent*) is authoritative: a
    natural-language question about the image (VQA / general visual analysis)
    never triggers a deterministic specialist op here -- it defers to EarthMind.
    Only an explicit spatial/spectral/change *action* reaches the branches
    below. This is what stops "how many airplanes are present?" (a VQA question)
    from being mis-routed to GeoGround just because it names an object.
    """
    q = query_text or ""

    # Intent gate: VQA and general visual-analysis questions are answered by the
    # vision-language model, not by a deterministic grounding/spectral op. The
    # object nouns they contain ("airplanes", "buildings", "water") must not pull
    # in a specialist tool. Explicit actions classify as grounding /
    # multispectral / change and fall through to the branches below.
    if task in ("vqa", "visual_analysis"):
        return []

    modality = _modality(data_profiles, image_ref)
    is_sar = modality == "sar"
    profile0 = data_profiles[0] if data_profiles else None
    ids = _first_ids(image_ref, data_profiles)
    if not ids:
        return []

    # ---- Bi-temporal: index difference (optical) or SAR flood change -------
    if _has_temporal_pair(data_profiles):
        roles = _roles(data_profiles)
        before = next((i for i, r in roles.items() if r == "before"), None)
        after = next((i for i, r in roles.items() if r == "after"), None)
        if is_sar and _WATER.search(q):
            # Water masks on both dates -> area change compared downstream.
            return [
                ToolSpec(tool_name="sar_otsu", task=task, attachment_ids=[before],
                         op_kind="sar", params={"role": "before", "band": "VV"},
                         reason="SAR water extent at T1"),
                ToolSpec(tool_name="sar_otsu", task=task, attachment_ids=[after],
                         op_kind="sar", params={"role": "after", "band": "VV"},
                         reason="SAR water extent at T2"),
            ]
        index = None
        if _VEG.search(q):
            index = "ndvi"
        elif _WATER.search(q):
            index = "mndwi" if _feasible("mndwi", profile0) else "ndwi"
        if index and before and after:
            return [ToolSpec(
                tool_name=f"{index}_difference", task=task, attachment_ids=[before, after],
                op_kind="index_difference",
                params={"index": index, "before": before, "after": after},
                reason=f"{index.upper()} change between the two dates",
            )]
        return []  # general "what changed" -> defer to MCD-Mamba

    # ---- Grounding --------------------------------------------------------
    if _GROUNDING.search(q):
        target = extract_grounding_target(q)
        if "geoground" in available_tools:
            return [ToolSpec(
                tool_name="geoground", task=task, attachment_ids=ids,
                op_kind="model", params={"target": target},
                reason=f"text-guided grounding of {target!r} via GeoGround",
            )]
        # No GeoGround service: fall back to the mock grounding op, which labels
        # itself as a mock so the Evidence Engine never presents it as a real
        # detection.
        return [ToolSpec(tool_name="geoground", task=task, attachment_ids=ids,
                         op_kind="grounding", params={"target": target},
                         reason="object localization request (mock: GeoGround not configured)")]

    # ---- Single-image spectral / SAR --------------------------------------
    # Explicit index named in the query wins.
    m = _EXPLICIT_INDEX.search(q)
    if m and not is_sar:
        idx = m.group(1).lower()
        return [_spectral_spec(idx, task, ids, f"query explicitly requested {idx.upper()}")]

    if is_sar:
        if _WATER.search(q):
            return [ToolSpec(tool_name="sar_otsu", task=task, attachment_ids=ids,
                             op_kind="sar", params={"band": "VV"},
                             reason="SAR water/flood via dB + Otsu")]
        if _SAR_WORD.search(q):
            return [
                ToolSpec(tool_name="sar_db", task=task, attachment_ids=ids, op_kind="sar",
                         params={"band": "VV"}, reason="SAR backscatter in dB"),
                ToolSpec(tool_name="vv_vh", task=task, attachment_ids=ids, op_kind="sar",
                         primary=False, reason="VV/VH scattering ratio"),
            ]
        return []  # SAR image but a general question -> model path

    # Optical single-image intents.
    specs: list[ToolSpec] = []
    if _VEG.search(q):
        specs.append(_spectral_spec("ndvi", task, ids, "vegetation query -> NDVI"))
    if _WATER.search(q):
        if _feasible("ndwi", profile0):
            specs.append(_spectral_spec("ndwi", task, ids, "water query -> NDWI"))
        if _feasible("mndwi", profile0):
            specs.append(_spectral_spec("mndwi", task, ids, "water query -> MNDWI (SWIR)"))
    if _BUILTUP.search(q):
        specs.append(_spectral_spec("ndbi", task, ids, "built-up query -> NDBI"))
    if _BURN.search(q):
        specs.append(_spectral_spec("nbr", task, ids, "burn query -> NBR"))
        if _feasible("bai", profile0):
            specs.append(_spectral_spec("bai", task, ids, "burn query -> BAI"))
    if _MOISTURE.search(q):
        specs.append(_spectral_spec("ndmi", task, ids, "moisture query -> NDMI"))

    # Keep only feasible spectral tools; drop (with no error) those whose bands
    # are absent so the plan reflects what can actually be produced.
    return [s for s in specs if s.op_kind != "spectral" or _feasible(s.tool_name, profile0)]
