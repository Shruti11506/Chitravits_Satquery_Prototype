"""Evidence planner: query + task -> evidence requirements (spec §32).

Given the classified task and the query text, decide what evidence *should*
be present for a well-supported answer. This is deliberately rule-based and
transparent (Tools.docx §26 "neutral selection rule"): the planner does not
run anything, it only states expectations, so the fusion stage can later report
coverage and the validator can flag gaps.

The mapping follows the task→evidence table in Tools.docx §6/§19.
"""

from __future__ import annotations

from satquery.evidence.schemas import EvidenceRequirement, EvidenceType

# Keyword groups used to refine requirements for the multispectral/SAR/tool tasks,
# where the coarse TaskType does not say which index/feature is expected.
_VEG_WORDS = ("vegetation", "ndvi", "evi", "savi", "crop", "forest", "green", "canopy")
_WATER_WORDS = ("water", "flood", "ndwi", "mndwi", "lake", "river", "inundat", "wetland")
_BUILTUP_WORDS = ("built", "urban", "building", "ndbi", "settlement", "city")
_BURN_WORDS = ("burn", "fire", "nbr", "bai", "scar", "wildfire")
_SAR_WORDS = ("sar", "radar", "backscatter", "vv", "vh", "sentinel-1", "sentinel 1", "otsu")


def _has(text: str, words: tuple[str, ...]) -> bool:
    return any(w in text for w in words)


def plan_requirements(task: str, query_text: str) -> list[EvidenceRequirement]:
    """Return the evidence requirements for a query.

    ``task`` is a ``TaskType`` value string. Unknown tasks still get a single
    generic "answer" requirement so coverage is always computable.
    """
    q = (query_text or "").lower()
    reqs: list[EvidenceRequirement] = []

    def add(rid: str, desc: str, types: list[EvidenceType], required: bool = True) -> None:
        reqs.append(EvidenceRequirement(id=rid, description=desc, expected_types=types, required=required))

    if task in ("vqa", "visual_analysis"):
        add("answer", "A model answer to the visual question", [EvidenceType.VQA_ANSWER])

    elif task == "change_detection":
        add("change_region", "Where change occurred (change mask/regions)",
            [EvidenceType.CHANGE_MASK, EvidenceType.SEGMENTATION_MASK])
        add("change_stats", "How much changed (area/fraction statistics)",
            [EvidenceType.MEASUREMENT, EvidenceType.RASTER_STATISTICS], required=False)
        add("temporal", "Two comparable dated observations",
            [EvidenceType.TEMPORAL_METADATA], required=False)
        add("explanation", "A natural-language reading of the change",
            [EvidenceType.VQA_ANSWER, EvidenceType.CLAIM], required=False)

    elif task == "grounding":
        add("localization", "Bounding boxes / regions for the requested objects",
            [EvidenceType.GROUNDING_BOX, EvidenceType.SEGMENTATION_MASK])
        add("coordinates", "Geographic coordinates for the detections",
            [EvidenceType.COORDINATES], required=False)

    elif task == "multispectral_analysis":
        # Refine by what the query asks about.
        if _has(q, _WATER_WORDS):
            add("water_evidence", "Water/flood evidence (NDWI/MNDWI or SAR mask)",
                [EvidenceType.SPECTRAL_INDEX, EvidenceType.WATER_MASK, EvidenceType.SAR_OTSU])
        if _has(q, _VEG_WORDS):
            add("vegetation_evidence", "Vegetation evidence (NDVI/EVI/SAVI)",
                [EvidenceType.SPECTRAL_INDEX])
        if _has(q, _BUILTUP_WORDS):
            add("builtup_evidence", "Built-up evidence (NDBI)", [EvidenceType.SPECTRAL_INDEX])
        if _has(q, _BURN_WORDS):
            add("burn_evidence", "Burned-area evidence (NBR/BAI)", [EvidenceType.SPECTRAL_INDEX])
        if _has(q, _SAR_WORDS):
            add("sar_evidence", "SAR-derived evidence (VV/VH, dB, Otsu)",
                [EvidenceType.SAR_FEATURE, EvidenceType.SAR_OTSU, EvidenceType.WATER_MASK])
        if not reqs:
            add("spectral_evidence", "A relevant spectral/SAR evidence layer",
                [EvidenceType.SPECTRAL_INDEX, EvidenceType.SAR_FEATURE])
        add("statistics", "Numerical statistics for the evidence layer",
            [EvidenceType.RASTER_STATISTICS, EvidenceType.MEASUREMENT], required=False)

    else:  # unknown / other
        add("answer", "Some evidence supporting the response",
            [EvidenceType.VQA_ANSWER, EvidenceType.CLAIM, EvidenceType.OTHER])

    return reqs
