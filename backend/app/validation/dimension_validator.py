"""Image ratio / exact dimension validation for a T1/T2 pair (Change
Detection Input Validation brief, sections 3 and 4).

Two distinct, separately-coded checks on purpose:

* Aspect ratio, within a configurable tolerance -- catches a genuinely
  different framing/crop, but does NOT reject two same-ratio images just
  because one is a lower-resolution capture of the same scene (section 3's
  own 1920x1080 vs 1280x720 example).
* Exact width/height equality -- only enforced when the workflow actually
  needs pixel-to-pixel comparison (`ChangeDetectionRequirements.
  require_exact_dimensions`), which this prototype's change-detection path
  does, per the brief's own unconditional 10980x10980 vs 5120x5120 example.

Neither check resizes/crops/resamples anything -- see the package's "Do Not
Automatically Fix Invalid Inputs" rule.
"""
from __future__ import annotations

from app.validation.errors import ASPECT_RATIO_MISMATCH, IMAGE_DIMENSION_MISMATCH
from app.validation.schemas import ChangeDetectionIssue, RasterFacts


def aspect_ratio(width: int | None, height: int | None) -> float | None:
    if not width or not height:
        return None
    return width / height


def aspect_ratio_issue(
    t1: RasterFacts, t2: RasterFacts, *, tolerance: float, t1_label: str, t2_label: str
) -> ChangeDetectionIssue | None:
    ratio_1, ratio_2 = aspect_ratio(t1.width, t1.height), aspect_ratio(t2.width, t2.height)
    if ratio_1 is None or ratio_2 is None:
        return None  # nothing to compare -- INVALID_DIMENSIONS already covers a zero/missing size
    if abs(ratio_1 - ratio_2) > tolerance:
        return ChangeDetectionIssue.of(
            ASPECT_RATIO_MISMATCH,
            f"{t1_label} and {t2_label} have incompatible aspect ratios "
            f"({ratio_1:.4f} vs {ratio_2:.4f}, tolerance {tolerance}).",
            t1=f"{ratio_1:.4f}",
            t2=f"{ratio_2:.4f}",
        )
    return None


def exact_dimension_issue(
    t1: RasterFacts, t2: RasterFacts, *, t1_label: str, t2_label: str
) -> ChangeDetectionIssue | None:
    if t1.width == t2.width and t1.height == t2.height:
        return None
    return ChangeDetectionIssue.of(
        IMAGE_DIMENSION_MISMATCH,
        f"{t1_label} is {t1.width}x{t1.height}px but {t2_label} is {t2.width}x{t2.height}px. "
        "This change-detection workflow requires identical raster dimensions.",
        t1=f"{t1.width}x{t1.height}",
        t2=f"{t2.width}x{t2.height}",
    )
