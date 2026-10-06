"""Input/Task compatibility check (mentor requirements #2 and #5).

Runs *after* task classification and *before* tool selection. It answers one
question: given the classified task, are the attached inputs actually usable —
and if not, reject the request before any model or tool executes.

Checks performed (spec's explicit list):

* image count        — enough images for the task (bi-temporal / cross-modal need 2+)
* file format         — attachment URIs point at a supported raster/vector format
* modality            — the task's required modalities are present
* metadata            — temporal ordering metadata present where a task needs it
* spatial             — multi-image tasks: scenes plausibly overlap (CRS/bounds)
* temporal            — bi-temporal: before/after are distinct acquisitions
* optical/SAR pairing — cross-modal: exactly the optical + SAR pair is present
* missing/invalid     — attachments carry a resolvable reference

Blocking failures (``errors``) stop the graph before execution. Advisory issues
(``warnings``) travel into the response and the execution trace but do not block
— e.g. an unverifiable spatial overlap should inform, not refuse.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from satquery.agent.state import AgentError, TaskType
from satquery.input.schemas import ImageModality, UserQuery

# Formats the preprocessor / resolver can actually open.
_SUPPORTED_RASTER = frozenset({".tif", ".tiff", ".jp2", ".png", ".jpg", ".jpeg", ".img"})
_SUPPORTED_VECTOR = frozenset({".geojson", ".json", ".gpkg", ".shp", ".kml", ".parquet"})

# Tasks that operate on two or more images.
_MULTI_IMAGE_TASKS = frozenset({TaskType.CHANGE_DETECTION, TaskType.CROSS_MODAL_ANALYSIS})


@dataclass
class CompatibilityReport:
    """Outcome of the compatibility check."""

    errors: list[AgentError] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _suffix(uri: str | None) -> str:
    if not uri:
        return ""
    from pathlib import Path
    from urllib.parse import urlparse

    return Path(urlparse(uri).path).suffix.lower()


def _images(user_query: UserQuery) -> list:
    return [a for a in user_query.attachments if a.kind.value == "image"]


def _modalities(images: list) -> set[str]:
    return {a.modality.value for a in images if a.modality is not None}


def check_compatibility(
    task: TaskType,
    user_query: UserQuery,
    data_profiles: list | None = None,
) -> CompatibilityReport:
    """Validate the classified task against the actual inputs."""
    report = CompatibilityReport()
    images = _images(user_query)
    data_profiles = data_profiles or []

    # --- file format (all attachments that carry a URI) --------------------
    for a in user_query.attachments:
        suffix = _suffix(a.uri)
        if not suffix:
            continue  # no URI ⇒ resolved by id later; nothing to check here
        allowed = _SUPPORTED_VECTOR if a.kind.value == "vector" else _SUPPORTED_RASTER
        if suffix not in allowed:
            report.errors.append(AgentError(
                code="UNSUPPORTED_FORMAT",
                message=(
                    f"Attachment '{a.id}' has an unsupported {a.kind.value} format "
                    f"'{suffix}'. Supported: {', '.join(sorted(allowed))}."
                ),
                stage="check_compatibility",
            ))

    # --- image count -------------------------------------------------------
    if task in _MULTI_IMAGE_TASKS and len(images) < 2:
        report.errors.append(AgentError(
            code="INSUFFICIENT_IMAGES",
            message=(
                f"Task '{task.value}' needs at least two images; "
                f"{len(images)} image attachment(s) were provided."
            ),
            stage="check_compatibility",
        ))
        return report  # further multi-image checks are moot

    # --- optical/SAR pairing (cross-modal) ---------------------------------
    if task is TaskType.CROSS_MODAL_ANALYSIS:
        mods = _modalities(images)
        optical_like = mods & {
            ImageModality.OPTICAL.value,
            ImageModality.MULTISPECTRAL.value,
            ImageModality.HYPERSPECTRAL.value,
        }
        has_sar = ImageModality.SAR.value in mods
        if not (optical_like and has_sar):
            report.errors.append(AgentError(
                code="MODALITY_MISMATCH",
                message=(
                    "Optical + SAR cross-modal analysis needs one optical and one SAR "
                    f"image; got modalities {sorted(mods) or ['(unlabelled)']}."
                ),
                stage="check_compatibility",
            ))
            return report

    # --- temporal compatibility (bi-temporal change) ----------------------
    if task is TaskType.CHANGE_DETECTION:
        roles = {a.role.value for a in images if a.role is not None}
        timestamps = [a.timestamp for a in images if a.timestamp is not None]
        if {"before", "after"} <= roles:
            before = next((a.timestamp for a in images if a.role and a.role.value == "before"), None)
            after = next((a.timestamp for a in images if a.role and a.role.value == "after"), None)
            if before is not None and after is not None and str(before) == str(after):
                report.errors.append(AgentError(
                    code="TEMPORAL_INCOMPATIBLE",
                    message=(
                        "Change detection needs two different acquisition dates; the "
                        f"'before' and 'after' images share the timestamp {before}."
                    ),
                    stage="check_compatibility",
                ))
                return report
        else:
            report.warnings.append(
                "Change detection: images are not labelled 'before'/'after'; "
                "the first two images will be used in upload order."
            )
        if len(timestamps) < 2:
            report.warnings.append(
                "Change detection: acquisition timestamps are missing, so temporal "
                "ordering cannot be verified from metadata."
            )

    # --- spatial compatibility (multi-image tasks, needs profiles) ---------
    if task in _MULTI_IMAGE_TASKS and len(data_profiles) >= 2:
        report.warnings.extend(_spatial_warnings(data_profiles))

    return report


def _spatial_warnings(profiles: list) -> list[str]:
    """Advisory warnings when multi-image scenes may not cover the same area."""
    warnings: list[str] = []

    epsgs = {p.crs.epsg for p in profiles if getattr(p, "crs", None) and p.crs.epsg is not None}
    if len(epsgs) > 1:
        warnings.append(
            f"Images use different coordinate reference systems (EPSG {sorted(epsgs)}); "
            "results assume they were reprojected to a common grid."
        )

    boxes = []
    for p in profiles:
        b = getattr(p, "bounds_wgs84", None)
        if b is not None:
            boxes.append((b.west, b.south, b.east, b.north))
    if len(boxes) >= 2 and not _bboxes_overlap(boxes[0], boxes[1]):
        warnings.append(
            "The first two images do not appear to overlap spatially; a per-scene "
            "comparison may not be meaningful."
        )
    return warnings


def _bboxes_overlap(a: tuple, b: tuple) -> bool:
    aw, as_, ae, an = a
    bw, bs, be, bn = b
    # Treat all-zero (unknown) bounds as "cannot decide" → overlapping.
    if a == (0.0, 0.0, 0.0, 0.0) or b == (0.0, 0.0, 0.0, 0.0):
        return True
    return not (ae < bw or be < aw or an < bs or bn < as_)
