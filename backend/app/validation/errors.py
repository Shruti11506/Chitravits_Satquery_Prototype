"""Machine-readable codes an input-validation check can fail with.

One code always means one kind of problem, the same way `core/exceptions.py`
error codes work for the rest of the API. `ValidationIssue` is the shape of
one entry in a `ValidationResult.errors`/`.warnings` list (see schemas.py);
it is data returned from a validator, never raised as an exception -- a
request can fail several checks at once, and the caller should see all of
them, not just the first.
"""
from pydantic import BaseModel

# The list the task brief suggests, kept intact. A handful of additions
# below are for situations the brief describes but doesn't name a code for;
# each is commented with the rule it exists to serve.
UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
FILE_CORRUPTED = "FILE_CORRUPTED"
FILE_TOO_LARGE = "FILE_TOO_LARGE"
INVALID_IMAGE = "INVALID_IMAGE"
INVALID_DIMENSIONS = "INVALID_DIMENSIONS"
BAND_MISSING = "BAND_MISSING"
BAND_MISMATCH = "BAND_MISMATCH"
MODALITY_MISMATCH = "MODALITY_MISMATCH"
IMAGE_COUNT_MISMATCH = "IMAGE_COUNT_MISMATCH"
CRS_MISSING = "CRS_MISSING"
INVALID_CRS = "INVALID_CRS"
GEOREFERENCE_MISSING = "GEOREFERENCE_MISSING"
INVALID_AOI = "INVALID_AOI"
AOI_OUTSIDE_IMAGE = "AOI_OUTSIDE_IMAGE"
RESOURCE_LIMIT_EXCEEDED = "RESOURCE_LIMIT_EXCEEDED"
WORKFLOW_INPUT_MISMATCH = "WORKFLOW_INPUT_MISMATCH"

# The requested `workflow` key isn't in the declarative registry
# (workflow_validator.WORKFLOW_REGISTRY) -- a client/typo problem, distinct
# from any input being wrong.
UNKNOWN_WORKFLOW = "UNKNOWN_WORKFLOW"
# An `imagery_id` doesn't exist, or its Storage object is gone -- a reference
# problem, distinct from FILE_CORRUPTED/INVALID_IMAGE (the file's content).
IMAGE_UNAVAILABLE = "IMAGE_UNAVAILABLE"
# A multi-image workflow (bi-temporal, optical+SAR) was given the same image
# twice -- section 7's "T1 and T2 are distinct observations".
NOT_DISTINCT_OBSERVATIONS = "NOT_DISTINCT_OBSERVATIONS"

# The four codes the Change Detection Input Validation brief names explicitly
# (dimension_validator.py / geospatial_validator.py / change_detection_validator.py).
IMAGE_DIMENSION_MISMATCH = "IMAGE_DIMENSION_MISMATCH"  # T1/T2 pixel width/height differ, exact match required
FILE_FORMAT_MISMATCH = "FILE_FORMAT_MISMATCH"  # T1/T2 raster formats differ (e.g. GeoTIFF vs JPEG)
CRS_MISMATCH = "CRS_MISMATCH"  # both georeferenced, but to a different CRS -- never auto-reprojected here
# Change detection: T1 and T2 are both of a KNOWN modality, but different ones
# (e.g. RGB vs SAR). MODALITY_MISMATCH, by contrast, is one image against what
# a workflow allows, or against its own `modality_hint`. Kept as-is: the
# frontend and existing clients read it.
IMAGE_TYPE_MISMATCH = "IMAGE_TYPE_MISMATCH"
UNKNOWN_MODALITY = "UNKNOWN_MODALITY"  # Image modality / type cannot be determined (reserved; not emitted)
# Not given a code by name in that brief, but its own section 3 calls this
# out as a distinct check from IMAGE_DIMENSION_MISMATCH -- kept as its own
# code rather than overloading IMAGE_DIMENSION_MISMATCH for a different rule.
ASPECT_RATIO_MISMATCH = "ASPECT_RATIO_MISMATCH"

# Sensor scope (sensors.py): Sentinel-1, Sentinel-2, Cartosat, RISAT.
UNKNOWN_SENSOR = "UNKNOWN_SENSOR"  # no sensor evidence, and the workflow needs sensor-specific interpretation
UNSUPPORTED_SENSOR = "UNSUPPORTED_SENSOR"  # a sensor was recognised, but it is outside the supported four
# SAR polarisations don't satisfy an explicitly configured requirement
# (`expected_sar_polarizations` / `sar_polarization_policy="single_required"`).
# A plain T1/T2 polarisation difference stays BAND_MISMATCH, as before.
POLARIZATION_MISMATCH = "POLARIZATION_MISMATCH"
DTYPE_MISMATCH = "DTYPE_MISMATCH"  # T1/T2 pixel data types differ (e.g. uint16 vs float32)

ALL_CODES = frozenset({
    UNSUPPORTED_FORMAT, FILE_CORRUPTED, FILE_TOO_LARGE, INVALID_IMAGE, INVALID_DIMENSIONS,
    BAND_MISSING, BAND_MISMATCH, MODALITY_MISMATCH, IMAGE_COUNT_MISMATCH, CRS_MISSING,
    INVALID_CRS, GEOREFERENCE_MISSING, INVALID_AOI, AOI_OUTSIDE_IMAGE, RESOURCE_LIMIT_EXCEEDED,
    WORKFLOW_INPUT_MISMATCH, UNKNOWN_WORKFLOW, IMAGE_UNAVAILABLE, NOT_DISTINCT_OBSERVATIONS,
    IMAGE_DIMENSION_MISMATCH, FILE_FORMAT_MISMATCH, CRS_MISMATCH, ASPECT_RATIO_MISMATCH,
    IMAGE_TYPE_MISMATCH, UNKNOWN_MODALITY, UNKNOWN_SENSOR, UNSUPPORTED_SENSOR, POLARIZATION_MISMATCH,
    DTYPE_MISMATCH,
})


class ValidationIssue(BaseModel):
    """One failed (or noteworthy) check. `input` names which input it's about,
    e.g. an imagery id, a role ("T1"/"T2"), or "aoi" -- null for a
    request-level problem (e.g. an unknown workflow)."""

    code: str
    message: str
    input: str | None = None

    @classmethod
    def of(cls, code: str, message: str, *, input: str | None = None) -> "ValidationIssue":  # noqa: A002
        return cls(code=code, message=message, input=input)
