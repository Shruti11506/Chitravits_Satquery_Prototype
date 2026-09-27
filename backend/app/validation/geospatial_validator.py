"""Geospatial Validation (task brief section 4).

Only runs when geospatial info is actually required -- by the workflow
(`WorkflowRequirements.requires_geospatial`) or because the request carries
an AOI (an AOI can only be checked against a georeferenced image). When it
isn't required, this module has nothing to say: a plain JPEG passes a
Visual-VQA workflow untouched, exactly as section 4 asks.

JPEG/PNG are treated as non-georeferenced BY CONSTRUCTION -- raster_validator
never sets `crs`/`transform`/`bounds` for them, and no metadata is invented
here to make one up (section 4: "Do NOT assume... Do not attempt to
automatically invent or infer geospatial metadata").
"""
from __future__ import annotations

from app.validation.errors import CRS_MISMATCH, CRS_MISSING, GEOREFERENCE_MISSING, INVALID_CRS, ValidationIssue
from app.validation.raster_validator import PILLOW_EXTENSIONS, TIFF_EXTENSIONS
from app.validation.schemas import RasterFacts


def geospatial_issues(facts: RasterFacts, *, input_label: str, required: bool, extension: str) -> list[ValidationIssue]:
    if not required:
        return []

    if extension in PILLOW_EXTENSIONS:
        return [ValidationIssue.of(
            GEOREFERENCE_MISSING,
            "JPEG/PNG images carry no geospatial information. Upload a georeferenced "
            "GeoTIFF for this workflow, or omit the AOI.",
            input=input_label,
        )]

    if extension not in TIFF_EXTENSIONS:
        # An unsupported extension is already rejected by file_validator;
        # nothing further to say about its georeferencing.
        return []

    if facts.crs is None:
        return [ValidationIssue.of(
            CRS_MISSING, "The GeoTIFF has no coordinate reference system (CRS).", input=input_label
        )]
    if facts.transform is None:
        return [ValidationIssue.of(
            GEOREFERENCE_MISSING, "The GeoTIFF has a CRS but no geotransform.", input=input_label
        )]
    if facts.bounds is None:
        # A CRS and transform exist, but the footprint couldn't be reprojected
        # to WGS84 -- the strongest signal available that the CRS itself is
        # unusable (e.g. malformed, or the scene falls outside its domain).
        return [ValidationIssue.of(
            INVALID_CRS,
            f"The GeoTIFF's CRS ('{facts.crs}') could not be used to determine real-world bounds.",
            input=input_label,
        )]
    return []


def crs_match_issue(t1: RasterFacts, t2: RasterFacts, *, t1_label: str, t2_label: str) -> ValidationIssue | None:
    """Cross-image CRS equality, for a bi-temporal pair (change_detection_validator.py).

    Only meaningful once both images individually passed `geospatial_issues`
    (so both `crs` values are non-null) -- call this after that, not instead
    of it. Never reprojects to compare; a genuine mismatch is CRS_MISMATCH,
    for the user to resolve, not this layer.
    """
    if t1.crs is not None and t2.crs is not None and t1.crs != t2.crs:
        return ValidationIssue.of(
            CRS_MISMATCH,
            f"{t1_label} uses CRS '{t1.crs}' but {t2_label} uses '{t2.crs}'. "
            "Both images must share the same CRS; this validator does not reproject.",
            input=t2_label,
        )
    return None
