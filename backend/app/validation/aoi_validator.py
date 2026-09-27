"""Basic AOI Validation (task brief section 10).

Checks only that the AOI geometry itself is well-formed, and -- for every
image that actually has real-world bounds -- that the AOI overlaps that
image. It does NOT clip, resample, register, or otherwise touch pixels;
those are later-stage concerns (section 10: "Do NOT perform... Image
clipping, Resampling, Registration, Change detection").
"""
from __future__ import annotations

from typing import Any

from shapely.errors import ShapelyError
from shapely.geometry import box, shape
from shapely.geometry.base import BaseGeometry

from app.validation.errors import AOI_OUTSIDE_IMAGE, INVALID_AOI, ValidationIssue
from app.validation.schemas import RasterFacts

_LON_RANGE = (-180.0, 180.0)
_LAT_RANGE = (-90.0, 90.0)


def parse_aoi(geometry: dict[str, Any]) -> tuple[BaseGeometry | None, ValidationIssue | None]:
    """The parsed geometry, or an INVALID_AOI issue -- never both."""
    try:
        geom = shape(geometry)
    except (ShapelyError, ValueError, TypeError, AttributeError, KeyError) as exc:
        return None, ValidationIssue.of(INVALID_AOI, f"The AOI geometry could not be parsed: {exc}", input="aoi")

    if geom.is_empty:
        return None, ValidationIssue.of(INVALID_AOI, "The AOI geometry is empty.", input="aoi")
    if not geom.is_valid:
        return None, ValidationIssue.of(INVALID_AOI, "The AOI geometry is not a valid polygon (self-intersecting or malformed).", input="aoi")
    if not _coordinates_in_range(geom):
        return None, ValidationIssue.of(
            INVALID_AOI,
            f"AOI coordinates must be within longitude {_LON_RANGE} and latitude {_LAT_RANGE}.",
            input="aoi",
        )
    return geom, None


def _coordinates_in_range(geom: BaseGeometry) -> bool:
    minx, miny, maxx, maxy = geom.bounds
    return _LON_RANGE[0] <= minx <= maxx <= _LON_RANGE[1] and _LAT_RANGE[0] <= miny <= maxy <= _LAT_RANGE[1]


def intersection_issues(geom: BaseGeometry, images: list[tuple[str, RasterFacts]]) -> list[ValidationIssue]:
    """AOI_OUTSIDE_IMAGE for every image with real bounds the AOI doesn't
    touch. Images with no bounds (e.g. a JPEG the workflow didn't require
    geospatial for) are silently skipped -- geospatial_validator already
    rejects them when the AOI made georeferencing required."""
    issues: list[ValidationIssue] = []
    for label, facts in images:
        if facts.bounds is None:
            continue
        west, south, east, north = facts.bounds
        image_box = box(west, south, east, north)
        if not geom.intersects(image_box):
            issues.append(ValidationIssue.of(
                AOI_OUTSIDE_IMAGE, "The AOI does not overlap this image's footprint.", input=label
            ))
    return issues
