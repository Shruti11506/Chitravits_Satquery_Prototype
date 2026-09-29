"""Modality / Sensor Compatibility (task brief section 5).

Determines what kind of image this is -- "rgb", "optical", "multispectral",
"sar", or "unknown" -- from EVIDENCE, never from the filename directly
(`sensors.identify_sensor` may use a filename to name the sensor; the
modality then follows from that sensor or from the raster's own bands):

1. Identified bands (`band_validator.detect_named_bands`, sensor-aware):
   any SAR polarisation -> "sar"; any band only a multispectral sensor has
   (NIR, SWIR, red-edge, ...) -> "multispectral".
2. The identified sensor, unless it was identified from the filename alone:
   Sentinel-1 / RISAT -> "sar"; Sentinel-2 -> "multispectral"; Cartosat ->
   "optical" (PAN, or MX without band metadata; MX bands named NIR etc.
   already hit rule 1).
3. Red+green+blue identified -> "rgb"; a decoded JPEG/PNG -> "rgb".
4. Nothing else -> "unknown". A raster is NOT "multispectral" just because
   it has more than three bands -- an unnamed 4-band raster stays unknown.

`modality_hint` is validated, not trusted: with no evidence it is accepted
(`source="hint"`); consistent with the evidence it is accepted (and may
refine a generic "optical"); contradicting the evidence (e.g. a Sentinel-1
VV raster hinted "optical") it is a MODALITY_MISMATCH naming both values.

If a required workflow needs a modality that can't be established,
`modality_issues` rejects with MODALITY_MISMATCH rather than guessing
(brief section 5).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.validation.band_validator import SAR_POLARIZATIONS, detect_named_bands
from app.validation.errors import MODALITY_MISMATCH, ValidationIssue
from app.validation.raster_validator import PILLOW_EXTENSIONS
from app.validation.schemas import Modality, RasterFacts
from app.validation.sensors import SAR_FAMILIES, SensorFamily, SensorIdentification, identify_sensor

_SAR_BANDS = frozenset(SAR_POLARIZATIONS)
# Bands an RGB camera doesn't have -- their presence means a multispectral sensor.
_MULTISPECTRAL_BANDS = frozenset({
    "coastal", "red_edge_1", "red_edge_2", "red_edge_3", "nir", "nir_narrow",
    "water_vapour", "cirrus", "swir1", "swir2",
})

# hint -> evidence values it is consistent with.
_HINT_COMPATIBLE: dict[str, frozenset[str]] = {
    "optical": frozenset({"optical", "rgb", "multispectral"}),
    "rgb": frozenset({"rgb", "optical"}),
    "multispectral": frozenset({"multispectral", "optical"}),
    "sar": frozenset({"sar"}),
    "optical_sar": frozenset({"optical", "rgb", "multispectral", "sar", "optical_sar"}),  # not judgeable per image
}


@dataclass(frozen=True)
class ModalityDecision:
    modality: Modality
    source: str  # "bands" | "sensor" | "file_type" | "hint" | "none"
    evidence: Modality = "unknown"  # what the evidence alone says
    hint: str | None = None
    hint_conflict: bool = False


def _evidence(facts: RasterFacts, *, extension: str, sensor_id: SensorIdentification) -> tuple[Modality, str]:
    bands = detect_named_bands(facts, sensor_id).keys()
    if bands & _SAR_BANDS:
        return "sar", "bands"
    if bands & _MULTISPECTRAL_BANDS:
        return "multispectral", "bands"
    # A sensor known only from the FILENAME may select a band table, but never
    # decides modality on its own (a JPEG named "S1A_IW_GRDH_..." is not SAR).
    if sensor_id.is_supported and sensor_id.source != "filename":
        if sensor_id.family in SAR_FAMILIES:
            return "sar", "sensor"
        if sensor_id.family == SensorFamily.SENTINEL_2:
            return "multispectral", "sensor"
        if sensor_id.family == SensorFamily.CARTOSAT:
            return "optical", "sensor"
    if {"red", "green", "blue"} <= bands:
        return "rgb", "bands"
    if extension in PILLOW_EXTENSIONS:
        return "rgb", "file_type"  # a decoded JPEG/PNG pixel buffer is RGB/greyscale by construction
    return "unknown", "none"


def infer_modality(
    facts: RasterFacts, *, extension: str, sensor_id: SensorIdentification, hint: str | None
) -> ModalityDecision:
    evidence, source = _evidence(facts, extension=extension, sensor_id=sensor_id)
    if not hint:
        return ModalityDecision(evidence, source, evidence)
    if evidence == "unknown":
        return ModalityDecision(hint, "hint", evidence, hint)
    if evidence not in _HINT_COMPATIBLE.get(hint, frozenset()):
        return ModalityDecision(evidence, source, evidence, hint, hint_conflict=True)
    if evidence == "optical" and hint in ("rgb", "multispectral"):
        return ModalityDecision(hint, "hint", evidence, hint)  # the hint refines a generic "optical"
    return ModalityDecision(evidence, source, evidence, hint)


def detect_modality(
    facts: RasterFacts,
    *,
    extension: str,
    sensor: str | None,
    source: str | None,
    hint: str | None,
    filename: str | None = None,
    sensor_id: SensorIdentification | None = None,
) -> Modality:
    """Backward-compatible string form of `infer_modality`. On a hint that
    contradicts the evidence this returns the EVIDENCE value -- report the
    conflict itself with `hint_conflict_issue`."""
    if sensor_id is None:
        sensor_id = identify_sensor(sensor=sensor, source=source, filename=filename, facts=facts)
    return infer_modality(facts, extension=extension, sensor_id=sensor_id, hint=hint).modality


def hint_conflict_issue(decision: ModalityDecision, *, input_label: str) -> ValidationIssue | None:
    if not decision.hint_conflict:
        return None
    return ValidationIssue.of(
        MODALITY_MISMATCH,
        f"The modality hint '{decision.hint}' contradicts this image's own metadata, which identifies it "
        f"as '{decision.evidence}'.",
        input=input_label,
    )


def modality_issues(
    detected: Modality, allowed: list[str] | dict[str, list[str]] | None, *, role: str, workflow_label: str, input_label: str
) -> list[ValidationIssue]:
    if allowed is None:
        return []
    candidates = allowed.get(role) if isinstance(allowed, dict) else allowed
    if candidates is None or detected in candidates:
        return []

    if detected == "unknown":
        message = (
            f"{workflow_label} requires imagery of type {_join(candidates)}, but this image's modality "
            "could not be determined from its metadata. Supply it explicitly (modality_hint)."
        )
    else:
        message = f"{workflow_label} requires imagery of type {_join(candidates)}; this image is '{detected}'."
    return [ValidationIssue.of(MODALITY_MISMATCH, message, input=input_label)]


def _join(values: list[str]) -> str:
    return " or ".join(f"'{v}'" for v in values)
