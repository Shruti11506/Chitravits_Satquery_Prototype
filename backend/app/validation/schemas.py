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

from dataclasses import dataclass, field, replace
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
    # Added fields (optional, default null): which sensor the evidence names,
    # and which evidence decided the sensor / modality. See sensors.py.
    sensor: str | None = Field(
        default=None, description="'sentinel-1' | 'sentinel-2' | 'cartosat' | 'risat', an unsupported sensor's name, or null."
    )
    sensor_status: Literal["supported", "unsupported", "unknown"] | None = None
    sensor_source: str | None = None
    modality_source: str | None = None


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


SarPolarizationPolicy = Literal["match_all", "single_required"]
SarPolarization = Literal["vv", "vh", "hh", "hv"]


@dataclass(frozen=True)
class ChangeDetectionRequirements:
    """`workflow_requirements` -- the configurable knobs section 3/4/7/9 of
    the brief calls for, so a stricter or looser change-detection workflow
    never means editing the validator itself. See CHAT_GATE_REQUIREMENTS /
    STRICT_REQUIREMENTS below for the two profiles the API uses."""

    # None disables the aspect-ratio check (reported "skipped", never "pass").
    aspect_ratio_tolerance: float | None = 0.01
    # False only for a future, non-pixel-registered workflow -- the
    # prototype's own change-detection path needs identical rasters.
    require_exact_dimensions: bool = True
    require_matching_format: bool = True
    # True: BOTH images must be georeferenced (a JPEG/PNG fails, and the
    # error names which image). False: see `geospatial_when_present`.
    require_geospatial: bool = True
    # Only when require_geospatial is False: if EITHER image carries a CRS,
    # validate both and compare CRSs; if neither does, skip the check.
    geospatial_when_present: bool = False
    # UNKNOWN_SENSOR when an image's sensor can't be identified (sensors.py).
    require_known_sensor: bool = False
    # UNSUPPORTED_SENSOR when an image is recognisably from another sensor.
    reject_unsupported_sensor: bool = True
    # DTYPE_MISMATCH when T1/T2 pixel data types differ. No per-sensor dtype
    # allowlist -- TODO(team) if a model ever needs one.
    require_matching_dtype: bool = True
    # "match_all": T1 and T2 must carry the same polarisation SET (VV+VH <->
    # VV+VH is fine). "single_required": each image exactly one polarisation.
    sar_polarization_policy: SarPolarizationPolicy = "match_all"
    # When set (e.g. ("vv", "vh") for a model trained on VV+VH), each image's
    # polarisations must equal it, else POLARIZATION_MISMATCH. None = no
    # model-specific requirement.
    expected_sar_polarizations: tuple[str, ...] | None = None

    def with_overrides(self, **overrides: Any) -> "ChangeDetectionRequirements":
        """Copy with every non-None override applied (API request fields)."""
        values = {key: value for key, value in overrides.items() if value is not None}
        if "expected_sar_polarizations" in values:
            values["expected_sar_polarizations"] = tuple(values["expected_sar_polarizations"])
        return replace(self, **values)


# The default for image pairs in the chat -- `POST /analysis` and
# `POST /validation/change-detection` (which the frontend calls after every
# pair upload). Demo-friendly: sensor evidence optional, and geospatial
# checks only when an image actually carries georeferencing, so two plain
# JPEG/PNG images still pair. Modality, bands, dimensions and dtype are
# still enforced.
CHAT_GATE_REQUIREMENTS = ChangeDetectionRequirements(require_geospatial=False, geospatial_when_present=True)
# Opt-in (`"profile": "strict"`): the sensor must be one of the four
# supported ones, and both images must be georeferenced.
STRICT_REQUIREMENTS = ChangeDetectionRequirements(require_geospatial=True, require_known_sensor=True)


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
    driver: str | None = None
    nodata: Any = None
    tags: dict[str, str] = field(default_factory=dict)
    band_tags: list[dict[str, str]] = field(default_factory=list)
    units: list[str | None] = field(default_factory=list)
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


class CheckDetail(BaseModel):
    """One entry of `check_details`: whether a check actually ran, and how."""

    status: Literal["pass", "fail", "skipped"]
    detail: str | None = None


class ChangeDetectionValidationResult(BaseModel):
    """What `change_detection_validator.validate_change_detection_inputs`
    returns -- section 15's `ValidationResult(valid, errors, warnings)`,
    named distinctly to avoid colliding with `ValidationResult` above."""

    valid: bool
    status: Literal["VALID", "REJECT"] = "VALID"
    confidence: str | None = None
    # Only checks that actually RAN: True = passed, False = failed. A check
    # that was skipped (disabled, not applicable, or never reached because an
    # earlier one failed) is absent here -- see check_details for why.
    checks: dict[str, bool] = Field(default_factory=dict)
    check_details: dict[str, CheckDetail] = Field(default_factory=dict)
    # The identified bands per image, in the order preprocessing would
    # receive them (SAR: VV, VH, HH, HV). None when bands weren't compared.
    ordered_bands: dict[str, list[str]] | None = None
    errors: list[ChangeDetectionIssue] = Field(default_factory=list)
    warnings: list[ChangeDetectionIssue] = Field(default_factory=list)


class ImageSummary(BaseModel):
    """One entry of a ChangeDetectionResponse's `t1`/`t2` -- section 12's shape."""

    filename: str | None = None
    format: str | None = None
    modality: Modality = "unknown"
    bands: list[str] = Field(default_factory=list)
    band_count: int | None = None
    width: int | None = None
    height: int | None = None
    aspect_ratio: float | None = None
    crs: str | None = None
    dtype: str | None = None
    sensor: str | None = None
    sensor_status: Literal["supported", "unsupported", "unknown"] | None = None
    sensor_source: str | None = None
    sensor_product: str | None = None


class ChangeDetectionRequest(BaseModel):
    """POST /api/v1/validation/change-detection body."""

    t1_imagery_id: UUID
    t2_imagery_id: UUID
    # "chat" (default) = CHAT_GATE_REQUIREMENTS, "strict" = STRICT_REQUIREMENTS.
    profile: Literal["chat", "strict"] = "chat"
    # Overrides applied on top of the profile -- None keeps the profile's value.
    aspect_ratio_tolerance: float | None = None
    require_exact_dimensions: bool | None = None
    require_matching_format: bool | None = None
    require_geospatial: bool | None = None
    require_known_sensor: bool | None = None
    require_matching_dtype: bool | None = None
    sar_polarization_policy: SarPolarizationPolicy | None = None
    expected_sar_polarizations: list[SarPolarization] | None = None

    def requirements(self) -> ChangeDetectionRequirements:
        base = STRICT_REQUIREMENTS if self.profile == "strict" else CHAT_GATE_REQUIREMENTS
        return base.with_overrides(
            aspect_ratio_tolerance=self.aspect_ratio_tolerance,
            require_exact_dimensions=self.require_exact_dimensions,
            require_matching_format=self.require_matching_format,
            require_geospatial=self.require_geospatial,
            require_known_sensor=self.require_known_sensor,
            require_matching_dtype=self.require_matching_dtype,
            sar_polarization_policy=self.sar_polarization_policy,
            expected_sar_polarizations=self.expected_sar_polarizations,
        )


class ChangeDetectionResponse(BaseModel):
    status: Literal["VALID", "REJECT"]
    valid: bool
    workflow: str = "change_detection"
    confidence: str | None = None
    checks: dict[str, bool] = Field(default_factory=dict)
    check_details: dict[str, CheckDetail] = Field(default_factory=dict)
    ordered_bands: dict[str, list[str]] | None = None
    t1: ImageSummary | None = None
    t2: ImageSummary | None = None
    errors: list[ChangeDetectionIssue] = Field(default_factory=list)
    warnings: list[ChangeDetectionIssue] = Field(default_factory=list)
    error_code: str | None = None
    message: str | None = None
