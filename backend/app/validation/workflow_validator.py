"""Query <-> Input Compatibility (task brief sections 7 and 9): the
declarative table of what each SatQuery workflow needs, and the code that
checks submitted images against it.

`WorkflowRequirements` is deliberately data, not a chain of `if/else` --
adding a new workflow means adding one entry to `WORKFLOW_REGISTRY`, never
touching the validators themselves (section 19: "Keep workflow requirements
declarative rather than scattering if/else conditions throughout the
codebase.").
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.validation import band_validator, geospatial_validator, modality_validator
from app.validation.change_detection_validator import validate_change_detection_inputs
from app.validation.errors import (
    IMAGE_COUNT_MISMATCH,
    NOT_DISTINCT_OBSERVATIONS,
    UNKNOWN_SENSOR,
    UNKNOWN_WORKFLOW,
    UNSUPPORTED_SENSOR,
    WORKFLOW_INPUT_MISMATCH,
    ValidationIssue,
)
from app.validation.raster_validator import extension_of
from app.validation.schemas import ChangeDetectionImageMetadata, ChangeDetectionRequirements, ImageInput, RasterFacts
from app.validation.sensors import SensorIdentification, identify_sensor


@dataclass(frozen=True)
class WorkflowRequirements:
    display_name: str
    required_images: int
    # None = any modality is acceptable (e.g. a captioning workflow). A
    # flat list applies to every image; a dict keyed by role applies a
    # different allow-list per role (needed for optical+SAR, where the two
    # images must be different modalities from each other).
    allowed_modalities: list[str] | dict[str, list[str]] | None = None
    # One inner list per image position (in the order images are submitted):
    # the named bands that image must contain. [] / an all-empty list means
    # no band constraint. See band_validator.positional_band_issues for how
    # a shared single-band requirement (e.g. VV at every position) is
    # enforced consistently rather than position-by-position.
    required_bands: list[list[str]] = field(default_factory=list)
    requires_geospatial: bool = False
    # The exact multiset of roles expected, e.g. ["t1", "t2"] or
    # ["optical", "sar"]. None = role-agnostic (a single-image workflow, or
    # one that doesn't care which role label was sent).
    required_roles: list[str] | None = None
    # True for workflows whose band interpretation depends on the sensor
    # (band math such as NDVI): an image whose sensor can't be identified is
    # UNKNOWN_SENSOR, one from an out-of-scope sensor UNSUPPORTED_SENSOR.
    # Other workflows (VQA, captioning, ...) ignore the sensor entirely.
    requires_known_sensor: bool = False
    # Set for a T1/T2 change workflow that must go through the dedicated
    # change-detection validator (change_detection_validator.py) instead of
    # the per-image checks below -- so it can't be used to bypass it.
    change_detection: ChangeDetectionRequirements | None = None


# The compatibility matrix from the task brief, expressed declaratively.
# Workflow keys are this API's own vocabulary (see `AnalysisType` in
# schemas/analysis.py for the closest existing concept) -- intentionally not
# reused 1:1, since a request type ("general_analysis") isn't the same thing
# as an input-shape requirement.
# No SAR polarisation workflows: Sentinel-1 / RISAT get no band or
# polarisation validation (scope decision); SAR change goes through
# `bitemporal_change`, i.e. the change-detection validator.
WORKFLOW_REGISTRY: dict[str, WorkflowRequirements] = {
    "visual_vqa": WorkflowRequirements(display_name="Visual VQA", required_images=1),
    "scene_captioning": WorkflowRequirements(display_name="Scene captioning", required_images=1),
    "region_grounding": WorkflowRequirements(display_name="Region grounding", required_images=1),
    "ndvi": WorkflowRequirements(
        display_name="NDVI",
        required_images=1,
        # Not "rgb": a plain RGB image has no NIR band.
        allowed_modalities=["optical", "multispectral"],
        required_bands=[["red", "nir"]],  # Sentinel-2 B8A (nir_narrow) also satisfies "nir"
        requires_known_sensor=True,
    ),
    "bitemporal_change": WorkflowRequirements(
        display_name="Bi-temporal change analysis",
        required_images=2,
        required_roles=["t1", "t2"],
        change_detection=ChangeDetectionRequirements(),
    ),
    "optical_sar_analysis": WorkflowRequirements(
        display_name="Optical + SAR analysis",
        required_images=2,
        allowed_modalities={"optical": ["optical", "rgb", "multispectral"], "sar": ["sar"]},
        required_roles=["optical", "sar"],
    ),
}


def get_workflow(workflow_key: str) -> WorkflowRequirements | None:
    return WORKFLOW_REGISTRY.get(workflow_key)


def unknown_workflow_issue(workflow_key: str) -> ValidationIssue:
    known = ", ".join(sorted(WORKFLOW_REGISTRY))
    return ValidationIssue.of(
        UNKNOWN_WORKFLOW, f"'{workflow_key}' is not a known workflow. Known workflows: {known}."
    )


def structural_issues(workflow: WorkflowRequirements, images: list[ImageInput]) -> list[ValidationIssue]:
    """Image COUNT, ROLES and DISTINCTNESS -- the checks that are about the
    shape of the request rather than any one image's content."""
    issues: list[ValidationIssue] = []

    if len(images) != workflow.required_images:
        issues.append(ValidationIssue.of(
            IMAGE_COUNT_MISMATCH,
            f"{workflow.display_name} requires exactly {workflow.required_images} image(s); received {len(images)}.",
        ))
        return issues  # role/band/geospatial checks below assume the count is right

    if workflow.required_roles is not None:
        submitted = sorted(image.role for image in images)
        if submitted != sorted(workflow.required_roles):
            issues.append(ValidationIssue.of(
                WORKFLOW_INPUT_MISMATCH,
                f"{workflow.display_name} expects images with roles {sorted(workflow.required_roles)}; "
                f"received {submitted}.",
            ))

    if workflow.required_images > 1:
        seen_ids = [image.imagery_id for image in images if image.imagery_id]
        if len(seen_ids) != len(set(seen_ids)):
            issues.append(ValidationIssue.of(
                NOT_DISTINCT_OBSERVATIONS,
                f"{workflow.display_name} requires distinct images; the same image was submitted more than once.",
            ))

    return issues


def compatibility_issues(
    workflow: WorkflowRequirements, images: list[ImageInput], facts: list[RasterFacts]
) -> list[ValidationIssue]:
    """Per-image geospatial + modality + band checks against what `workflow` declares.

    Only called once `structural_issues` found the count/roles/distinctness
    correct -- `images`, `facts` and `workflow.required_bands` (when set)
    are all the same length here.
    """
    if workflow.change_detection is not None:
        return _change_detection_issues(workflow, images, facts)

    issues: list[ValidationIssue] = []
    geospatial_required = workflow.requires_geospatial
    sensors = [sensor_for(image, image_facts) for image, image_facts in zip(images, facts)]

    for image, image_facts, sensor in zip(images, facts, sensors):
        label = image.imagery_id or image.filename
        if workflow.requires_known_sensor:
            issues.extend(sensor_issues(sensor, workflow_label=workflow.display_name, input_label=label))

        issues.extend(geospatial_validator.geospatial_issues(
            image_facts, input_label=label, required=geospatial_required, extension=extension_of(image.filename)
        ))

        decision = modality_validator.infer_modality(
            image_facts, extension=extension_of(image.filename), sensor_id=sensor, hint=image.modality_hint
        )
        conflict = modality_validator.hint_conflict_issue(decision, input_label=label)
        if conflict:
            issues.append(conflict)
        else:
            issues.extend(modality_validator.modality_issues(
                decision.modality, workflow.allowed_modalities, role=image.role,
                workflow_label=workflow.display_name, input_label=label,
            ))

    if workflow.required_bands and any(workflow.required_bands):
        labels = [image.imagery_id or image.filename for image in images]
        issues.extend(band_validator.positional_band_issues(
            list(zip(labels, facts)), workflow.required_bands, workflow_label=workflow.display_name, sensors=sensors
        ))

    return issues


def sensor_for(image: ImageInput, facts: RasterFacts) -> SensorIdentification:
    return identify_sensor(sensor=image.sensor, source=image.source, filename=image.filename, facts=facts)


def sensor_issues(sensor: SensorIdentification, *, workflow_label: str, input_label: str) -> list[ValidationIssue]:
    if sensor.status == "unsupported":
        return [ValidationIssue.of(
            UNSUPPORTED_SENSOR,
            f"This image is from '{sensor.raw_value}', which is not a supported sensor "
            "(Sentinel-1, Sentinel-2, Cartosat, RISAT).",
            input=input_label,
        )]
    if sensor.status == "unknown":
        return [ValidationIssue.of(
            UNKNOWN_SENSOR,
            f"{workflow_label} needs to know which sensor produced this image (Sentinel-1, Sentinel-2, Cartosat or "
            "RISAT) to interpret its bands, and none was found in its metadata or filename.",
            input=input_label,
        )]
    return []


def _change_detection_issues(
    workflow: WorkflowRequirements, images: list[ImageInput], facts: list[RasterFacts]
) -> list[ValidationIssue]:
    """The dedicated T1/T2 validator, for a change workflow in the generic
    registry. It stops at its first failing check; that issue is returned,
    labelled with the image it is about when it names only one."""
    by_role = {image.role: (image, image_facts) for image, image_facts in zip(images, facts)}
    metadata = {}
    for role, label in (("t1", "T1"), ("t2", "T2")):
        image, image_facts = by_role[role]
        metadata[role] = ChangeDetectionImageMetadata(
            label=label, facts=image_facts, extension=extension_of(image.filename), filename=image.filename,
            sensor=image.sensor, source=image.source, modality_hint=image.modality_hint, imagery_id=image.imagery_id,
            content_type=image.content_type, storage_path=image.storage_path, sha256=image.sha256,
            pixel_sha256=image.pixel_sha256, acquisition_date=image.acquisition_date, content=image.content,
            content_loader=image.content_loader,
        )
    result = validate_change_detection_inputs(metadata["t1"], metadata["t2"], workflow.change_detection)
    issues = []
    for error in result.errors:
        if error.t1 is not None and error.t2 is None:
            image_label = by_role["t1"][0].imagery_id or by_role["t1"][0].filename
        elif error.t2 is not None and error.t1 is None:
            image_label = by_role["t2"][0].imagery_id or by_role["t2"][0].filename
        else:
            image_label = None
        issues.append(ValidationIssue.of(error.code, error.message, input=image_label))
    return issues
