"""Evidence fusion (spec §35).

Ties validated evidence items back to the planner's requirements: marks which
requirements are satisfied, orders the items for presentation, records
conflicts, and computes overall coverage and validation status. The output is
the numbered evidence set the answer generator references (§37).

Fusion does not invent agreement — an item satisfies a requirement only when
its type matches and it did not FAIL validation.
"""

from __future__ import annotations

from satquery.evidence.schemas import (
    EvidenceItem,
    EvidenceRequirement,
    EvidenceType,
    ValidationStatus,
    worst_status,
)

# Presentation order: lead with the primary analytical evidence, end with sources.
_TYPE_ORDER: dict[EvidenceType, int] = {
    EvidenceType.VQA_ANSWER: 0,
    EvidenceType.CHANGE_MASK: 1,
    EvidenceType.SEGMENTATION_MASK: 1,
    EvidenceType.GROUNDING_BOX: 1,
    EvidenceType.SPECTRAL_INDEX: 2,
    EvidenceType.SAR_FEATURE: 2,
    EvidenceType.SAR_OTSU: 2,
    EvidenceType.WATER_MASK: 2,
    EvidenceType.MEASUREMENT: 3,
    EvidenceType.RASTER_STATISTICS: 3,
    EvidenceType.COORDINATES: 4,
    EvidenceType.TEMPORAL_METADATA: 5,
    EvidenceType.CLAIM: 6,
    EvidenceType.SOURCE_IMAGE: 9,
    EvidenceType.OTHER: 7,
}


def _satisfies(item: EvidenceItem, req: EvidenceRequirement) -> bool:
    return item.type in req.expected_types and item.validation_status is not ValidationStatus.FAIL


def fuse(
    requirements: list[EvidenceRequirement],
    items: list[EvidenceItem],
    conflicts: list[str],
) -> tuple[list[EvidenceRequirement], list[EvidenceItem], float, ValidationStatus]:
    """Link items to requirements and compute coverage + overall status.

    Returns (requirements, ordered_items, coverage, overall_status).
    """
    # Link each requirement to the items that satisfy it.
    for req in requirements:
        matches = [it for it in items if _satisfies(it, req)]
        req.satisfied = len(matches) > 0
        req.satisfied_by = [it.id for it in matches]
        for it in matches:
            if req.id not in it.requirement_ids:
                it.requirement_ids.append(req.id)

    # Coverage over *required* requirements.
    required = [r for r in requirements if r.required]
    coverage = (
        sum(1 for r in required if r.satisfied) / len(required) if required else 1.0
    )

    # Order items for presentation.
    ordered = sorted(
        items,
        key=lambda it: (_TYPE_ORDER.get(it.type, 8), 0 if it.requirement_ids else 1, it.id),
    )

    # Overall status: worst across analytical items (source images excluded so a
    # missing-CRS source does not dominate the verdict for the actual evidence).
    analytical = [it for it in ordered if it.type is not EvidenceType.SOURCE_IMAGE]
    overall = worst_status([it.validation_status for it in analytical])

    return requirements, ordered, coverage, overall


def summarize(items: list[EvidenceItem], requirements: list[EvidenceRequirement]) -> str:
    """A short, factual description of the evidence set (not the final answer)."""
    analytical = [it for it in items if it.type is not EvidenceType.SOURCE_IMAGE]
    if not analytical:
        return "No analytical evidence was produced."
    names = ", ".join(it.name for it in analytical)
    unmet = [r.description for r in requirements if r.required and not r.satisfied]
    base = f"{len(analytical)} evidence item(s): {names}."
    if unmet:
        base += f" Missing: {'; '.join(unmet)}."
    return base
