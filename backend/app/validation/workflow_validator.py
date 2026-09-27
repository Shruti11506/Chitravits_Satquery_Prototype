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
from app.validation.errors import IMAGE_COUNT_MISMATCH, NOT_DISTINCT_OBSERVATIONS, UNKNOWN_WORKFLOW, WORKFLOW_INPUT_MISMATCH, ValidationIssue
from app.validation.raster_validator import extension_of
from app.validation.schemas import ImageInput, RasterFacts


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


# The compatibility matrix from the task brief, expressed declaratively.
# Workflow keys are this API's own vocabulary (see `AnalysisType` in
# schemas/analysis.py for the closest existing concept) -- intentionally not
# reused 1:1, since a request type ("general_analysis") isn't the same thing
# as an input-shape requirement.
WORKFLOW_REGISTRY: dict[str, WorkflowRequirements] = {
    "visual_vqa": WorkflowRequirements(display_name="Visual VQA", required_images=1),
    "scene_captioning": WorkflowRequirements(display_name="Scene captioning", required_images=1),
    "region_grounding": WorkflowRequirements(display_name="Region grounding", required_images=1),
    "ndvi": WorkflowRequirements(
        display_name="NDVI",
        required_images=1,
        allowed_modalities=["optical", "rgb", "multispectral"],
        required_bands=[["red", "nir"]],
    ),
    "sar_vv_analysis": WorkflowRequirements(
        display_name="SAR VV analysis", required_images=1, allowed_modalities=["sar"], required_bands=[["vv"]]
    ),
    "sar_vh_analysis": WorkflowRequirements(
        display_name="SAR VH analysis", required_images=1, allowed_modalities=["sar"], required_bands=[["vh"]]
    ),
    "bitemporal_change": WorkflowRequirements(
        display_name="Bi-temporal change analysis", required_images=2, required_roles=["t1", "t2"]
    ),
    "sar_change_vv": WorkflowRequirements(
        display_name="SAR VV change analysis",
        required_images=2,
        allowed_modalities=["sar"],
        required_bands=[["vv"], ["vv"]],
        requires_geospatial=True,
        required_roles=["t1", "t2"],
    ),
    "sar_change_vh": WorkflowRequirements(
        display_name="SAR VH change analysis",
        required_images=2,
        allowed_modalities=["sar"],
        required_bands=[["vh"], ["vh"]],
        requires_geospatial=True,
        required_roles=["t1", "t2"],
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
    workflow: WorkflowRequirements, images: list[ImageInput], facts: list[RasterFacts], *, aoi_present: bool
) -> list[ValidationIssue]:
    """Per-image geospatial + modality + band checks against what `workflow` declares.

    Only called once `structural_issues` found the count/roles/distinctness
    correct -- `images`, `facts` and `workflow.required_bands` (when set)
    are all the same length here.
    """
    issues: list[ValidationIssue] = []
    geospatial_required = workflow.requires_geospatial or aoi_present

    for image, image_facts in zip(images, facts):
        label = image.imagery_id or image.filename
        issues.extend(geospatial_validator.geospatial_issues(
            image_facts, input_label=label, required=geospatial_required, extension=extension_of(image.filename)
        ))

        detected = modality_validator.detect_modality(
            image_facts, extension=extension_of(image.filename), sensor=image.sensor, source=image.source, hint=image.modality_hint
        )
        issues.extend(modality_validator.modality_issues(
            detected, workflow.allowed_modalities, role=image.role, workflow_label=workflow.display_name, input_label=label
        ))

    if workflow.required_bands and any(workflow.required_bands):
        labels = [image.imagery_id or image.filename for image in images]
        issues.extend(band_validator.positional_band_issues(
            list(zip(labels, facts)), workflow.required_bands, workflow_label=workflow.display_name
        ))

    return issues
