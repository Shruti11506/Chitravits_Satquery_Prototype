"""Pydantic/plain-dataclass shapes for the Input Validation layer.

Kept in this package rather than the app-wide `app/schemas/` -- see the
package docstring in `__init__.py` for why. Two kinds of shape live here:

* Wire shapes (`ValidationRequest`, `ValidationResult`, ...): what
  `POST /api/v1/validation/validate` accepts/returns. Pydantic, JSON-safe.
* Internal shapes (`ImageInput`, `RasterFacts`): what the validators
  themselves operate on. Plain dataclasses -- `ImageInput.content` is raw
  bytes, which never appears on the wire; only `app/api/routes/validation.py`
  and `imagery_service.build_validation_image()` construct one, by reading
  an already-uploaded image (see `service.py`'s docstring).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.validation.errors import ValidationIssue

# ---- Roles & modality -------------------------------------------------------
# Deliberately separate from `app.ml.contracts.ImageRole`/`Modality`: this
# package must stay usable even if the AI layer is absent, per the brief's
# "do not couple validation directly to the AI models".

ImageRole = Literal["single", "t1", "t2", "optical", "sar"]
ModalityHint = Literal["optical", "rgb", "multispectral", "sar", "optical_sar"]
# What a workflow allows / what an image is determined to be. "unknown" only
# ever appears as a DETECTED value, never something a workflow allows for a
# band-specific check -- see modality_validator.py.
Modality = Literal["optical", "rgb", "multispectral", "sar", "optical_sar", "unknown"]

# ---- Wire request ------------------------------------------------------------


class AOIInput(BaseModel):
    """A GeoJSON geometry object, e.g. {"type": "Polygon", "coordinates": [...]}.

    Validated structurally by aoi_validator.py; not a full GeoJSON Feature.
    """

    type: str
    coordinates: Any


class ValidationImageRef(BaseModel):
    """One already-uploaded image to check, by reference -- never re-uploads
    the file (see CLAUDE.md "Database & storage notes" / section 14 of the brief)."""

    imagery_id: UUID
    role: ImageRole = "single"
    # Only ever a caller-supplied hint (e.g. a UI toggle) -- validators never
    # invent a modality themselves. See modality_validator.py.
    modality_hint: ModalityHint | None = None


class ValidationRequest(BaseModel):
    """POST /api/v1/validation/validate body."""

    workflow: str = Field(..., description="A key in workflow_validator.WORKFLOW_REGISTRY, e.g. 'ndvi'.")
    images: list[ValidationImageRef] = Field(..., min_length=1)
    aoi: AOIInput | None = None
    query: str | None = Field(default=None, max_length=2000, description="Free text, carried through but not parsed.")

    @field_validator("workflow")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


# ---- Wire response -----------------------------------------------------------


class ValidatedImageInfo(BaseModel):
    """One entry of `ValidationResult.inputs` -- what was inspected, not the verdict.

    `imagery_id` mirrors `ImageInput.imagery_id` verbatim (a plain string,
    not necessarily a UUID): the wire REQUEST requires a real UUID
    (`ValidationImageRef.imagery_id`), but this package itself is
    storage-agnostic and doesn't otherwise assume Supabase's id shape.
    """

    imagery_id: str | None = None
    role: ImageRole
    filename: str
    format: str | None = None  # "GeoTIFF" | "TIFF" | "JPEG" | "PNG" | None (unreadable)
    width: int | None = None
    height: int | None = None
    bands: int | None = None
    dtype: str | None = None
    crs: str | None = None
    georeferenced: bool = False
    modality: Modality = "unknown"
    detected_bands: list[str] = Field(default_factory=list, description="Named bands found, e.g. ['red', 'nir'].")


class ValidationResult(BaseModel):
    status: Literal["VALID", "REJECT"]
    valid: bool
    errors: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[ValidationIssue] = Field(default_factory=list)
    inputs: list[ValidatedImageInfo] = Field(default_factory=list)

    @classmethod
    def build(cls, errors: list[ValidationIssue], warnings: list[ValidationIssue], inputs: list[ValidatedImageInfo]) -> "ValidationResult":
        valid = not errors
        return cls(status="VALID" if valid else "REJECT", valid=valid, errors=errors, warnings=warnings, inputs=inputs)


# ---- Internal (never serialized) ---------------------------------------------


@dataclass
class ImageInput:
    """One image for the validators to inspect.

    `content` is the actual file bytes and is always required for a format
    check (file_validator) -- but `known_properties`, when given, lets
    raster_validator build a `RasterFacts` WITHOUT re-parsing the bytes, for
    a TIFF whose structure was already recorded at upload time
    (`imagery.metadata.raster.properties`, see raster_service.py). This is
    the "don't duplicate the uploaded binary unnecessarily" path.
    """

    filename: str
    content_type: str | None
    role: ImageRole = "single"
    modality_hint: ModalityHint | None = None
    # Structured upload metadata (the `imagery.sensor`/`source` columns) --
    # NEVER the filename. See modality_validator.py's docstring for why.
    sensor: str | None = None
    source: str | None = None
    imagery_id: str | None = None
    size_bytes: int | None = None
    content: bytes | None = None
    known_properties: dict[str, Any] | None = None


@dataclass
class ChangeDetectionImageMetadata:
    """`t1_metadata`/`t2_metadata` -- everything `change_detection_validator.py`
    needs about one side of a T1/T2 pair, bundled so the module's main
    entry point can take exactly the two-metadata-plus-requirements shape
    that brief asks for (`validate_change_detection_inputs(t1_metadata,
    t2_metadata, workflow_requirements)`), without a long parameter list.
    """

    label: str  # "T1" or "T2" -- used in every message and error field
    facts: RasterFacts
    extension: str
    filename: str | None = None
    sensor: str | None = None
    source: str | None = None
    modality_hint: ModalityHint | None = None
    imagery_id: str | None = None


@dataclass(frozen=True)
class ChangeDetectionRequirements:
    """`workflow_requirements` -- the configurable knobs section 3/4/7/9 of
    the brief calls for, so a stricter or looser change-detection workflow
    never means editing the validator itself."""

    aspect_ratio_tolerance: float = 0.01
    # False only for a future, non-pixel-registered workflow -- the
    # prototype's own change-detection path needs identical rasters.
    require_exact_dimensions: bool = True
    require_matching_format: bool = True
    require_geospatial: bool = True


@dataclass
class RasterFacts:
    """What raster_validator.py determined about one image's structure.

    `error` set (and everything else default/empty) means the file could not
    be opened at all -- file_validator turns that into FILE_CORRUPTED.
    """

    format: str | None = None
    width: int | None = None
    height: int | None = None
    band_count: int | None = None
    dtypes: list[str] = field(default_factory=list)
    crs: str | None = None
    transform: list[float] | None = None
    bounds: tuple[float, float, float, float] | None = None  # (west, south, east, north), WGS84
    band_descriptions: list[str | None] = field(default_factory=list)
    color_interpretation: list[str] = field(default_factory=list)
    georeferenced: bool = False
    error: str | None = None


# ---- Change Detection Input Validation (its own wire contract) --------------
# A dedicated shape, not a reuse of ValidationRequest/ValidationResult above:
# the brief's own section 12 response keys errors by `t1`/`t2` (the
# conflicting VALUES, e.g. "Optical"/"SAR") rather than a generic `input`
# label, and section 15 wants a plain valid/errors/warnings result from the
# pure function -- both distinct enough from the generic shapes to warrant
# their own types rather than overloading one shape for two contracts.


class ChangeDetectionIssue(BaseModel):
    code: str
    message: str
    t1: str | None = None
    t2: str | None = None

    @classmethod
    def of(cls, code: str, message: str, *, t1: str | None = None, t2: str | None = None) -> "ChangeDetectionIssue":
        return cls(code=code, message=message, t1=t1, t2=t2)


class ChangeDetectionValidationResult(BaseModel):
    """What `change_detection_validator.validate_change_detection_inputs`
    returns -- section 15's `ValidationResult(valid, errors, warnings)`,
    named distinctly to avoid colliding with `ValidationResult` above."""

    valid: bool
    errors: list[ChangeDetectionIssue] = Field(default_factory=list)
    warnings: list[ChangeDetectionIssue] = Field(default_factory=list)


class ImageSummary(BaseModel):
    """One entry of a ChangeDetectionResponse's `t1`/`t2` -- section 12's shape."""

    filename: str | None = None
    format: str | None = None
    modality: Modality = "unknown"
    bands: list[str] = Field(default_factory=list)
    width: int | None = None
    height: int | None = None
    aspect_ratio: float | None = None
    crs: str | None = None


class ChangeDetectionRequest(BaseModel):
    """POST /api/v1/validation/change-detection body."""

    t1_imagery_id: UUID
    t2_imagery_id: UUID
    # Overrides for ChangeDetectionRequirements' defaults -- None keeps the default.
    aspect_ratio_tolerance: float | None = None
    require_exact_dimensions: bool | None = None
    require_matching_format: bool | None = None
    require_geospatial: bool | None = None


class ChangeDetectionResponse(BaseModel):
    status: Literal["VALID", "REJECT"]
    valid: bool
    workflow: str = "change_detection"
    t1: ImageSummary | None = None
    t2: ImageSummary | None = None
    errors: list[ChangeDetectionIssue] = Field(default_factory=list)
    warnings: list[ChangeDetectionIssue] = Field(default_factory=list)
