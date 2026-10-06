"""SatQuery Evidence Engine (spec §32–§37).

Turns validated tool/model outputs into a provenance-carrying, requirement-
checked ``EvidencePackage`` for the answer generator. Kept separate from the
offline Evaluation Engine: these are lightweight real-time checks, not
benchmark metrics (spec §2, §40).
"""

from satquery.evidence.engine import build_evidence_package
from satquery.evidence.node import make_evidence_node
from satquery.evidence.schemas import (
    EvidenceItem,
    EvidencePackage,
    EvidenceRequirement,
    EvidenceType,
    Provenance,
    ValidationCheck,
    ValidationStatus,
)

__all__ = [
    "build_evidence_package",
    "make_evidence_node",
    "EvidenceItem",
    "EvidencePackage",
    "EvidenceRequirement",
    "EvidenceType",
    "Provenance",
    "ValidationCheck",
    "ValidationStatus",
]
