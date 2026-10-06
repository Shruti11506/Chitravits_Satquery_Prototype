"""Evidence Engine contracts (spec §32–§36).

The Evidence Engine sits between tool/model execution and answer generation. It
turns raw ``ToolResult`` outputs into *validated, provenance-carrying evidence
items* organised against the evidence the query actually requires.

Design rules taken from the SatQuery operations research (Tools.docx):
- Every evidence item is traceable to the tool/model/raster that produced it
  (§17 provenance, §36) — nothing is fabricated or merged without labelling.
- Validation status is one of PASS / WARNING / FAIL, never an invented score
  (§34). Numeric confidence is only carried when a real signal exists.
- Deterministic tools are *evidence generators*, not answers; the package is
  handed to the answer generator, which references the items (§37).

These models reuse ``Measurement`` and ``SpatialResult`` from
``satquery.tools.schemas`` so evidence stays consistent with tool output.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from satquery.tools.schemas import Measurement, SpatialResult


class ValidationStatus(StrEnum):
    """Lightweight evidence validation verdict (spec §34)."""

    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"

    @property
    def rank(self) -> int:
        return {"pass": 0, "warning": 1, "fail": 2}[self.value]


def worst_status(statuses: list["ValidationStatus"]) -> ValidationStatus:
    """The most severe status in a list (FAIL > WARNING > PASS). Empty -> PASS."""
    if not statuses:
        return ValidationStatus.PASS
    return max(statuses, key=lambda s: s.rank)


class EvidenceType(StrEnum):
    """The kinds of evidence the engine can carry (spec §33)."""

    VQA_ANSWER = "vqa_answer"
    GROUNDING_BOX = "grounding_box"
    SEGMENTATION_MASK = "segmentation_mask"
    CHANGE_MASK = "change_mask"
    SPECTRAL_INDEX = "spectral_index"   # NDVI/NDWI/MNDWI/NDBI/NBR/NDMI/SAVI/EVI/BAI
    SAR_FEATURE = "sar_feature"         # VV/VH, ratio, RVI, dB
    SAR_OTSU = "sar_otsu"
    WATER_MASK = "water_mask"
    RASTER_STATISTICS = "raster_statistics"
    MEASUREMENT = "measurement"
    COORDINATES = "coordinates"
    TEMPORAL_METADATA = "temporal_metadata"
    SOURCE_IMAGE = "source_image"
    CLAIM = "claim"
    OTHER = "other"


class Provenance(BaseModel):
    """Full lineage of one evidence item (spec §17, §36).

    A result such as "23% of the area changed" is only meaningful if another
    engineer can reconstruct which imagery, tool, parameters, CRS and area
    calculation produced it — this record is what makes that possible.
    """

    evidence_id: str
    source_type: str = "tool"                 # "model" | "tool" | "raster" | "derived"
    producer: str = ""                        # tool id: "earthmind", "mcd_mamba", "geoground", "ndvi"
    # The actual model/weights behind ``producer`` when one ran, as the service
    # itself reported it (e.g. "EarthMind4B_multi", "STMambaBCD_multimodal").
    model: str | None = None
    # What was done to the input to obtain this evidence, in one phrase
    # ("bi-temporal change detection", "(NIR-RED)/(NIR+RED)"). Copied from the
    # tool's own declaration — never inferred.
    transformation: str | None = None
    source_file: str | None = None
    source_bands: list[str] = Field(default_factory=list)   # ["B08","B04"] | ["VV","VH"]
    sensor_modality: str | None = None        # "optical" | "sar" | ...
    parameters: dict = Field(default_factory=dict)          # formula, thresholds, L, ...
    crs: str | None = None                    # "EPSG:32633"
    spatial_extent: list[float] | None = None  # [west, south, east, north] WGS84
    acquisition_dates: list[str] = Field(default_factory=list)
    input_ids: list[str] = Field(default_factory=list)      # attachment ids
    output_path: str | None = None            # local path, for in-process tools
    output_url: str | None = None             # fetchable URL, for remote model services
    # Every artifact behind this evidence item: {name, kind, url, path}.
    output_files: list[dict] = Field(default_factory=list)
    confidence: float | None = None
    timestamp: str = ""                       # ISO-8601, when the evidence was built
    software: str = "satquery-evidence/0.1"


class ValidationCheck(BaseModel):
    """One lightweight validity check applied to an evidence item (spec §34)."""

    name: str            # "geospatial" | "modality" | "band" | "temporal" | "spatial" | "consistency"
    status: ValidationStatus
    detail: str = ""


class EvidenceItem(BaseModel):
    """A single validated piece of evidence supporting (or opposing) the answer."""

    id: str
    type: EvidenceType
    subtype: str | None = None                # "ndvi", "change", "flood", ...
    name: str                                 # display name: "NDVI Difference"
    claim: str = ""                           # human-readable statement of what it shows
    confidence: float | None = None
    is_mock: bool = False                     # produced by a mock/demo adapter (spec §48/§56)
    measurements: list[Measurement] = Field(default_factory=list)
    spatial: list[SpatialResult] = Field(default_factory=list)
    data: dict = Field(default_factory=dict)
    provenance: Provenance
    checks: list[ValidationCheck] = Field(default_factory=list)
    validation_status: ValidationStatus = ValidationStatus.PASS
    layer_id: str | None = None               # map layer this evidence activates (spec §55)
    requirement_ids: list[str] = Field(default_factory=list)

    def recompute_status(self) -> "EvidenceItem":
        self.validation_status = worst_status([c.status for c in self.checks])
        return self


class EvidenceRequirement(BaseModel):
    """What evidence the query needs, from the planner (spec §32 requirements)."""

    id: str
    description: str
    expected_types: list[EvidenceType] = Field(default_factory=list)
    required: bool = True
    satisfied: bool = False
    satisfied_by: list[str] = Field(default_factory=list)   # evidence item ids


class EvidencePackage(BaseModel):
    """The validated, fused evidence handed to the answer generator (spec §32)."""

    query_id: str = ""
    task: str = ""
    summary: str = ""                          # short description of the evidence set
    requirements: list[EvidenceRequirement] = Field(default_factory=list)
    items: list[EvidenceItem] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    coverage: float = 0.0                      # satisfied required / total required
    validation_status: ValidationStatus = ValidationStatus.PASS
    confidence: float | None = None

    # -- convenience accessors -------------------------------------------
    def items_for(self, requirement_id: str) -> list[EvidenceItem]:
        return [i for i in self.items if requirement_id in i.requirement_ids]

    def valid_items(self) -> list[EvidenceItem]:
        return [i for i in self.items if i.validation_status is not ValidationStatus.FAIL]
