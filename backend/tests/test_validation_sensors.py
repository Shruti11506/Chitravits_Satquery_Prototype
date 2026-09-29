"""Sensor-aware input validation (Sentinel-1 / Sentinel-2 / Cartosat / RISAT):
sensor identification, sensor-specific band tables, evidence-based modality,
the SAR polarisation policy, dtype, geospatial per image, the chat vs strict
change-detection profiles, and `check_details`. No network, no model."""
import io

import numpy as np
import pytest
from PIL import Image
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from app.validation import band_validator, modality_validator, raster_validator
from app.validation.change_detection_validator import validate_change_detection_inputs
from app.validation.errors import (
    BAND_MISMATCH,
    BAND_MISSING,
    CRS_MISSING,
    DTYPE_MISMATCH,
    GEOREFERENCE_MISSING,
    IMAGE_DIMENSION_MISMATCH,
    IMAGE_TYPE_MISMATCH,
    MODALITY_MISMATCH,
    POLARIZATION_MISMATCH,
    UNKNOWN_SENSOR,
    UNSUPPORTED_SENSOR,
)
from app.validation.schemas import (
    CHAT_GATE_REQUIREMENTS,
    STRICT_REQUIREMENTS,
    ChangeDetectionImageMetadata,
    ChangeDetectionRequirements,
    ImageInput,
    RasterFacts,
)
from app.validation.sensors import SensorFamily, identify_sensor
from app.validation.service import validate_images

S2_NAME = "S2A_MSIL2A_20240101T050211_N0510_R020_T43PGQ_20240101T081000.tif"
S1_NAME = "S1A_IW_GRDH_1SDV_20240101T004016_20240101T004041_051900_064526_1A2B.tif"


# ---- fixtures ---------------------------------------------------------------------


def _geotiff(*, descriptions=(), count=None, dtype="uint16", crs="EPSG:32643", width=64, height=48, tags=None):
    count = count if count is not None else (len(descriptions) or 1)
    with MemoryFile() as mem:
        with mem.open(
            driver="GTiff", width=width, height=height, count=count, dtype=dtype,
            crs=crs, transform=from_origin(776000, 1440000, 10, 10),
        ) as dst:
            dst.write(np.zeros((count, height, width), dtype=dtype))
            for i, name in enumerate(descriptions, start=1):
                dst.set_band_description(i, name)
            if tags:
                dst.update_tags(**tags)
        return mem.read()


def _plain_tiff(*, count=1, dtype="uint16", width=64, height=48):
    with MemoryFile() as mem:
        with mem.open(driver="GTiff", width=width, height=height, count=count, dtype=dtype) as dst:
            dst.write(np.zeros((count, height, width), dtype=dtype))
        return mem.read()


def _image_bytes(fmt, width=64, height=48):
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=(10, 20, 30)).save(buf, format=fmt)
    return buf.getvalue()


def _meta(label, content, filename, *, sensor=None, hint=None, imagery_id=None) -> ChangeDetectionImageMetadata:
    image = ImageInput(filename=filename, content_type=None, content=content, size_bytes=len(content))
    return ChangeDetectionImageMetadata(
        label=label, facts=raster_validator.resolve_facts(image), extension=raster_validator.extension_of(filename),
        filename=filename, sensor=sensor, modality_hint=hint, imagery_id=imagery_id or label,
    )


def _img(filename, content, *, role="single", sensor=None, hint=None, imagery_id=None) -> ImageInput:
    return ImageInput(
        filename=filename, content_type=None, content=content, size_bytes=len(content),
        role=role, sensor=sensor, modality_hint=hint, imagery_id=imagery_id or filename,
    )


def _facts(descriptions, **kw):
    return RasterFacts(format="GeoTIFF", width=10, height=10, band_count=len(descriptions), band_descriptions=descriptions, **kw)


# ---- sensor identification ---------------------------------------------------------


@pytest.mark.parametrize("kwargs,family,source", [
    ({"sensor": "Sentinel-2B MSI"}, SensorFamily.SENTINEL_2, "db_sensor"),
    ({"source": "Copernicus Sentinel-1 GRD"}, SensorFamily.SENTINEL_1, "db_source"),
    ({"filename": S1_NAME}, SensorFamily.SENTINEL_1, "filename"),
    ({"filename": S2_NAME}, SensorFamily.SENTINEL_2, "filename"),
    ({"filename": "T43PGQ_20240101T050211_B04_10m.tif"}, SensorFamily.SENTINEL_2, "filename"),
    ({"filename": "risat1a_scene_hh.tif"}, SensorFamily.RISAT, "filename"),
    ({"sensor": "EOS-04"}, SensorFamily.RISAT, "db_sensor"),
    ({"sensor": "Cartosat-3"}, SensorFamily.CARTOSAT, "db_sensor"),
    ({"facts": _facts([None], tags={"SPACECRAFT_NAME": "Sentinel-2A"})}, SensorFamily.SENTINEL_2, "tiff_tag"),
    ({"facts": _facts(["B02", "B8A"])}, SensorFamily.SENTINEL_2, "band_naming"),
])
def test_supported_sensors_are_identified_with_their_evidence(kwargs, family, source):
    found = identify_sensor(**kwargs)
    assert found.status == "supported"
    assert found.family == family
    assert found.source == source


def test_explicit_sensor_field_outranks_the_filename():
    found = identify_sensor(sensor="RISAT-1A", filename=S1_NAME)
    assert found.family == SensorFamily.RISAT and found.source == "db_sensor"


@pytest.mark.parametrize("kwargs", [
    {"filename": "LC08_L2SP_144051_20240101_20240110_02_T1.tif"},
    {"sensor": "Landsat 8"},
    {"sensor": "WorldView-3"},
    {"source": "ICEYE"},
])
def test_out_of_scope_sensors_are_unsupported(kwargs):
    found = identify_sensor(**kwargs)
    assert found.status == "unsupported"
    assert found.family is None


def test_no_evidence_is_unknown_not_guessed():
    # "s1.tif" / "B4" alone are not evidence of anything.
    assert identify_sensor(filename="s1.tif", facts=_facts(["B4"])).status == "unknown"


def test_products_are_only_reported_when_stated():
    assert identify_sensor(filename=S2_NAME).product == "S2 L2A"
    assert identify_sensor(filename=S1_NAME).product == "S1 GRD"
    assert identify_sensor(sensor="Cartosat-3").product is None


# ---- sensor-specific band tables -----------------------------------------------------


def test_sentinel2_band_ids_map_through_the_sentinel2_table():
    s2 = identify_sensor(sensor="Sentinel-2")
    bands = band_validator.detect_named_bands(_facts(["B02", "B03", "B04", "B08", "B8A", "B11"]), s2)
    assert bands == {"blue": 1, "green": 2, "red": 3, "nir": 4, "nir_narrow": 5, "swir1": 6}
    assert band_validator.detect_named_bands(_facts(["B4"]), s2) == {"red": 1}  # B4 and B04 both accepted


def test_band_ids_are_not_interpreted_for_an_unknown_sensor():
    facts = _facts(["B4", "B8"])
    assert band_validator.detect_named_bands(facts, identify_sensor(filename="scene.tif")) == {}
    assert band_validator.unrecognised_band_names(facts) == ["B4", "B8"]


def test_band_ids_are_not_interpreted_for_an_unsupported_sensor():
    landsat = identify_sensor(sensor="Landsat 8")  # Landsat 8 B8 is panchromatic, not NIR
    assert band_validator.detect_named_bands(_facts(["B4", "B8"]), landsat) == {}


def test_self_describing_names_work_for_any_sensor():
    assert band_validator.detect_named_bands(_facts(["Red", "NIR", "VV"])) == {"red": 1, "nir": 2, "vv": 3}


def test_risat_compact_pol_labels_are_reported_not_guessed():
    risat = identify_sensor(sensor="RISAT-1A")
    facts = _facts(["RH", "RV"])
    assert band_validator.detect_named_bands(facts, risat) == {}
    assert band_validator.unrecognised_band_names(facts, risat) == ["RH", "RV"]


def test_cartosat_band_numbers_are_never_assumed():
    cartosat = identify_sensor(sensor="Cartosat-3 MX")
    assert cartosat.product == "Cartosat MX"
    assert band_validator.detect_named_bands(_facts(["B1", "B2", "B3", "B4"]), cartosat) == {}


def test_filename_never_decides_band_identity():
    # The filename names the sensor; the bands are still only what the raster says.
    bands = band_validator.detect_named_bands(_facts([None, None]), identify_sensor(filename=S2_NAME))
    assert bands == {}


# ---- modality ----------------------------------------------------------------------------


def _decide(facts, *, extension=".tif", filename=None, sensor=None, hint=None):
    sid = identify_sensor(sensor=sensor, filename=filename, facts=facts)
    return modality_validator.infer_modality(facts, extension=extension, sensor_id=sid, hint=hint)


def test_unknown_four_band_raster_is_unknown_not_multispectral():
    facts = raster_validator.extract_from_bytes(_geotiff(count=4), "scene.tif")
    assert _decide(facts).modality == "unknown"


def test_sensor_evidence_decides_modality():
    one_band = raster_validator.extract_from_bytes(_geotiff(count=1), "scene.tif")
    assert _decide(one_band, sensor="Sentinel-1").modality == "sar"
    assert _decide(one_band, sensor="RISAT-1A").modality == "sar"
    assert _decide(one_band, sensor="Cartosat-3 PAN").modality == "optical"
    four_band = raster_validator.extract_from_bytes(_geotiff(count=4), "scene.tif")
    assert _decide(four_band, sensor="Sentinel-2").modality == "multispectral"


def test_a_filename_alone_never_decides_modality():
    jpeg = raster_validator.extract_from_bytes(_image_bytes("JPEG"), "x.jpg")
    decision = _decide(jpeg, extension=".jpg", filename="S1A_IW_GRDH_1SDV_quicklook.jpg")
    assert decision.modality == "rgb"  # not "sar" just because of its name
    undescribed = raster_validator.extract_from_bytes(_geotiff(count=4), S2_NAME)
    assert _decide(undescribed, filename=S2_NAME).modality == "unknown"


def test_hint_without_evidence_is_accepted_and_recorded():
    facts = raster_validator.extract_from_bytes(_geotiff(count=2), "scene.tif")
    decision = _decide(facts, hint="sar")
    assert decision.modality == "sar" and decision.source == "hint" and not decision.hint_conflict


def test_hint_contradicting_evidence_is_a_modality_mismatch():
    facts = raster_validator.extract_from_bytes(_geotiff(descriptions=["VV"]), S1_NAME)
    decision = _decide(facts, filename=S1_NAME, hint="optical")
    assert decision.hint_conflict and decision.modality == "sar"
    issue = modality_validator.hint_conflict_issue(decision, input_label="x")
    assert issue.code == MODALITY_MISMATCH
    assert "'optical'" in issue.message and "'sar'" in issue.message


def test_multispectral_hint_on_plain_rgb_is_a_conflict():
    facts = raster_validator.extract_from_bytes(_image_bytes("PNG"), "x.png")
    assert _decide(facts, extension=".png", hint="multispectral").hint_conflict


def test_generic_pipeline_reports_the_hint_conflict():
    image = _img(S1_NAME, _geotiff(descriptions=["VV"]), hint="optical")
    result = validate_images(workflow="visual_vqa", images=[image])
    assert result.valid is False
    assert [e.code for e in result.errors] == [MODALITY_MISMATCH]


# ---- NDVI -----------------------------------------------------------------------------------


def test_ndvi_valid_for_sentinel2_red_nir():
    image = _img(S2_NAME, _geotiff(descriptions=["B02", "B03", "B04", "B08"]))
    result = validate_images(workflow="ndvi", images=[image])
    assert result.valid, result.errors
    assert result.inputs[0].sensor == "sentinel-2" and result.inputs[0].sensor_source == "filename"


def test_ndvi_accepts_b8a_as_nir():
    image = _img(S2_NAME, _geotiff(descriptions=["B04", "B8A"]))
    assert validate_images(workflow="ndvi", images=[image]).valid


def test_ndvi_missing_nir_band_is_rejected():
    image = _img(S2_NAME, _geotiff(descriptions=["B02", "B03", "B04"]))
    result = validate_images(workflow="ndvi", images=[image])
    assert result.valid is False
    missing = [e for e in result.errors if e.code == BAND_MISSING]
    assert missing and "NIR band is required" in missing[0].message


def test_rgb_jpeg_cannot_satisfy_ndvi():
    result = validate_images(workflow="ndvi", images=[_img("photo.jpg", _image_bytes("JPEG"))])
    codes = {e.code for e in result.errors}
    assert result.valid is False
    assert {BAND_MISSING, MODALITY_MISMATCH} <= codes  # "rgb" isn't an NDVI modality, and there's no NIR
    assert any("NIR band is required" in e.message for e in result.errors)


def test_rgb_geotiff_of_a_known_sensor_still_needs_nir_for_ndvi():
    image = _img("scene.tif", _geotiff(descriptions=["red", "green", "blue"]), sensor="Sentinel-2A")
    result = validate_images(workflow="ndvi", images=[image])
    assert [e.code for e in result.errors] == [BAND_MISSING]


def test_cartosat_without_product_band_metadata_fails_ndvi_clearly():
    image = _img("scene.tif", _geotiff(descriptions=["B1", "B2", "B3", "B4"]), sensor="Cartosat-3 MX")
    result = validate_images(workflow="ndvi", images=[image])
    messages = [e.message for e in result.errors if e.code == BAND_MISSING]
    assert messages and all("Cartosat product band metadata not available" in m for m in messages)


def test_unknown_sensor_fails_ndvi_but_the_same_image_passes_vqa():
    image = lambda: _img("scene.tif", _geotiff(descriptions=["red", "nir"]))
    ndvi = validate_images(workflow="ndvi", images=[image()])
    assert UNKNOWN_SENSOR in {e.code for e in ndvi.errors}
    assert validate_images(workflow="visual_vqa", images=[image()]).valid


def test_unsupported_sensor_fails_ndvi():
    image = _img("LC08_L2SP_144051_20240101_20240110_02_T1.tif", _geotiff(descriptions=["red", "nir"]))
    result = validate_images(workflow="ndvi", images=[image])
    assert UNSUPPORTED_SENSOR in {e.code for e in result.errors}


# ---- change detection: valid pairs -----------------------------------------------------------


def test_compatible_sentinel2_pair_is_valid_under_strict():
    bands = ["B02", "B03", "B04", "B08"]
    result = validate_change_detection_inputs(
        _meta("T1", _geotiff(descriptions=bands), S2_NAME), _meta("T2", _geotiff(descriptions=bands), S2_NAME),
        STRICT_REQUIREMENTS,
    )
    assert result.valid, result.errors
    assert result.confidence == "exact"
    assert result.ordered_bands == {"t1": ["blue", "green", "red", "nir"], "t2": ["blue", "green", "red", "nir"]}
    assert result.check_details["sensor"].status == "pass"


def test_compatible_optical_cartosat_pair_is_valid_under_strict():
    result = validate_change_detection_inputs(
        _meta("T1", _geotiff(count=1), "a.tif", sensor="Cartosat-3 PAN"),
        _meta("T2", _geotiff(count=1), "b.tif", sensor="Cartosat-3 PAN"),
        STRICT_REQUIREMENTS,
    )
    assert result.valid, result.errors


def test_sentinel1_vv_pair_is_valid():
    result = validate_change_detection_inputs(
        _meta("T1", _geotiff(descriptions=["VV"]), S1_NAME), _meta("T2", _geotiff(descriptions=["VV"]), S1_NAME),
        STRICT_REQUIREMENTS,
    )
    assert result.valid, result.errors
    assert result.ordered_bands == {"t1": ["vv"], "t2": ["vv"]}


def test_dual_pol_sentinel1_and_risat_pair_is_valid_with_ordered_bands():
    # Stored VH-then-VV on T2: the ordered list is still [vv, vh] -- never set/dict order.
    result = validate_change_detection_inputs(
        _meta("T1", _geotiff(descriptions=["VV", "VH"]), S1_NAME),
        _meta("T2", _geotiff(descriptions=["VH", "VV"]), "scene.tif", sensor="RISAT-1A"),
        STRICT_REQUIREMENTS,
    )
    assert result.valid, result.errors
    assert result.ordered_bands == {"t1": ["vv", "vh"], "t2": ["vv", "vh"]}


def test_jpeg_pair_is_valid_under_the_relaxed_chat_profile():
    result = validate_change_detection_inputs(
        _meta("T1", _image_bytes("JPEG"), "before.jpg"), _meta("T2", _image_bytes("JPEG"), "after.jpg"),
        CHAT_GATE_REQUIREMENTS,
    )
    assert result.valid, result.errors
    for name in ("geospatial_t1", "geospatial_t2", "crs", "sensor"):
        assert result.check_details[name].status == "skipped"
        assert name not in result.checks  # skipped checks are never reported as passed


def test_unknown_structurally_compatible_pair_is_valid_under_chat():
    result = validate_change_detection_inputs(
        _meta("T1", _geotiff(count=2), "a.tif"), _meta("T2", _geotiff(count=2), "b.tif"), CHAT_GATE_REQUIREMENTS
    )
    assert result.valid, result.errors
    assert result.confidence == "structural"
    assert result.check_details["modality"].status == "skipped"


# ---- change detection: invalid pairs ---------------------------------------------------------


def test_optical_vs_sar_pair_is_rejected():
    result = validate_change_detection_inputs(
        _meta("T1", _geotiff(descriptions=["B02", "B03", "B04", "B08"]), S2_NAME),
        _meta("T2", _geotiff(descriptions=["VV", "VH", "VV", "VH"]), S1_NAME),
        CHAT_GATE_REQUIREMENTS,
    )
    assert result.valid is False
    assert result.errors[0].code == IMAGE_TYPE_MISMATCH
    assert (result.errors[0].t1, result.errors[0].t2) == ("Multispectral", "SAR")
    assert result.checks["modality"] is False


def test_missing_required_bands_in_t2_is_rejected():
    result = validate_change_detection_inputs(
        _meta("T1", _geotiff(descriptions=["B02", "B03", "B04", "B08"]), S2_NAME),
        _meta("T2", _geotiff(descriptions=["B02", "B03", "B04", "B05"]), S2_NAME),
        CHAT_GATE_REQUIREMENTS,
    )
    assert result.errors[0].code == BAND_MISMATCH
    assert result.check_details["band_compatibility"].status == "fail"


def test_vv_vh_difference_without_configuration_stays_band_mismatch():
    result = validate_change_detection_inputs(
        _meta("T1", _geotiff(descriptions=["VV"]), "a.tif"), _meta("T2", _geotiff(descriptions=["VH"]), "b.tif"),
        CHAT_GATE_REQUIREMENTS,
    )
    assert result.errors[0].code == BAND_MISMATCH


def test_dual_pol_vs_single_pol_is_rejected_under_match_all():
    result = validate_change_detection_inputs(
        _meta("T1", _geotiff(descriptions=["VV", "VH"]), "a.tif"), _meta("T2", _geotiff(descriptions=["VV", "HH"]), "b.tif"),
        CHAT_GATE_REQUIREMENTS,
    )
    assert result.valid is False
    assert result.errors[0].code == BAND_MISMATCH


def test_expected_polarisations_reject_a_pair_that_lacks_them():
    required = CHAT_GATE_REQUIREMENTS.with_overrides(expected_sar_polarizations=("vv", "vh"))
    result = validate_change_detection_inputs(
        _meta("T1", _geotiff(descriptions=["VV"]), "a.tif"), _meta("T2", _geotiff(descriptions=["VV"]), "b.tif"), required
    )
    assert result.errors[0].code == POLARIZATION_MISMATCH
    assert "VV+VH" in result.errors[0].message


def test_expected_polarisations_name_the_failing_image():
    required = CHAT_GATE_REQUIREMENTS.with_overrides(expected_sar_polarizations=("vv",))
    result = validate_change_detection_inputs(
        _meta("T1", _geotiff(descriptions=["VV"]), "a.tif"), _meta("T2", _geotiff(descriptions=["VH"]), "b.tif"), required
    )
    assert result.errors[0].code == POLARIZATION_MISMATCH
    assert result.errors[0].t1 is None and result.errors[0].t2 == "VH"


def test_expected_polarisations_default_none_enforces_nothing_extra():
    assert CHAT_GATE_REQUIREMENTS.expected_sar_polarizations is None
    result = validate_change_detection_inputs(
        _meta("T1", _geotiff(descriptions=["VV", "VH"]), "a.tif"), _meta("T2", _geotiff(descriptions=["VV", "VH"]), "b.tif"),
        CHAT_GATE_REQUIREMENTS,
    )
    assert result.valid, result.errors


def test_single_required_policy_rejects_a_multi_pol_image():
    required = CHAT_GATE_REQUIREMENTS.with_overrides(sar_polarization_policy="single_required")
    result = validate_change_detection_inputs(
        _meta("T1", _geotiff(descriptions=["VV", "VH"]), "a.tif"), _meta("T2", _geotiff(descriptions=["VV", "VH"]), "b.tif"),
        required,
    )
    assert result.errors[0].code == POLARIZATION_MISMATCH
    assert "VV+VH" in result.errors[0].message


def test_dimension_mismatch_is_rejected_and_recorded():
    result = validate_change_detection_inputs(
        _meta("T1", _geotiff(count=1, width=64, height=48), "a.tif"),
        _meta("T2", _geotiff(count=1, width=128, height=96), "b.tif"),
        CHAT_GATE_REQUIREMENTS,
    )
    assert result.errors[0].code == IMAGE_DIMENSION_MISMATCH
    assert result.checks["dimensions"] is False
    assert result.check_details["band_count"].detail == "not reached"
    assert "band_count" not in result.checks


def test_dtype_mismatch_is_rejected():
    result = validate_change_detection_inputs(
        _meta("T1", _geotiff(count=1, dtype="uint16"), "a.tif"),
        _meta("T2", _geotiff(count=1, dtype="float32"), "b.tif"),
        CHAT_GATE_REQUIREMENTS,
    )
    assert result.errors[0].code == DTYPE_MISMATCH
    assert (result.errors[0].t1, result.errors[0].t2) == ("uint16", "float32")


def test_dtype_check_can_be_disabled_and_then_is_skipped():
    result = validate_change_detection_inputs(
        _meta("T1", _geotiff(count=1, dtype="uint16"), "a.tif"),
        _meta("T2", _geotiff(count=1, dtype="float32"), "b.tif"),
        CHAT_GATE_REQUIREMENTS.with_overrides(require_matching_dtype=False),
    )
    assert result.valid, result.errors
    assert result.check_details["dtype"].status == "skipped" and "dtype" not in result.checks


def test_matching_dtype_passes():
    result = validate_change_detection_inputs(
        _meta("T1", _geotiff(count=1, dtype="float32"), "a.tif"), _meta("T2", _geotiff(count=1, dtype="float32"), "b.tif"),
        CHAT_GATE_REQUIREMENTS,
    )
    assert result.valid and result.checks["dtype"] is True


def test_unsupported_sensor_pair_is_rejected():
    landsat = "LC08_L2SP_144051_20240101_20240110_02_T1.tif"
    result = validate_change_detection_inputs(
        _meta("T1", _geotiff(count=1), landsat), _meta("T2", _geotiff(count=1), landsat), CHAT_GATE_REQUIREMENTS
    )
    assert result.errors[0].code == UNSUPPORTED_SENSOR


def test_unknown_sensor_is_rejected_under_strict_validation():
    result = validate_change_detection_inputs(
        _meta("T1", _geotiff(count=1), "a.tif"), _meta("T2", _geotiff(count=1), "b.tif"), STRICT_REQUIREMENTS
    )
    assert result.errors[0].code == UNKNOWN_SENSOR
    assert result.checks["sensor"] is False


def test_hint_conflict_in_a_pair_is_modality_mismatch():
    result = validate_change_detection_inputs(
        _meta("T1", _geotiff(descriptions=["VV"]), S1_NAME, hint="optical"),
        _meta("T2", _geotiff(descriptions=["VV"]), S1_NAME),
        CHAT_GATE_REQUIREMENTS,
    )
    assert result.errors[0].code == MODALITY_MISMATCH


# ---- geospatial: each image on its own -----------------------------------------------------------

_NO_FORMAT_CHECK = STRICT_REQUIREMENTS.with_overrides(require_matching_format=False, require_known_sensor=False)


def test_strict_geospatial_fails_on_t2_when_t2_is_png():
    result = validate_change_detection_inputs(
        _meta("T1", _geotiff(count=3), "a.tif"),
        _meta("T2", _image_bytes("PNG"), "b.png"),
        _NO_FORMAT_CHECK,
    )
    assert result.errors[0].code == GEOREFERENCE_MISSING
    assert result.errors[0].t2 == "T2" and result.errors[0].t1 is None
    assert result.checks["geospatial_t1"] is True and result.checks["geospatial_t2"] is False


def test_strict_geospatial_fails_on_t1_when_t1_is_png():
    # Previously skipped entirely: the check only ran when T1 was a TIFF.
    result = validate_change_detection_inputs(
        _meta("T1", _image_bytes("PNG"), "a.png"),
        _meta("T2", _geotiff(count=3), "b.tif"),
        _NO_FORMAT_CHECK,
    )
    assert result.errors[0].code == GEOREFERENCE_MISSING
    assert result.errors[0].t1 == "T1" and result.errors[0].t2 is None


def test_strict_geospatial_rejects_a_jpeg_pair():
    result = validate_change_detection_inputs(
        _meta("T1", _image_bytes("JPEG"), "a.jpg"), _meta("T2", _image_bytes("JPEG"), "b.jpg"),
        STRICT_REQUIREMENTS.with_overrides(require_known_sensor=False),
    )
    assert {e.code for e in result.errors} == {GEOREFERENCE_MISSING}


def test_chat_profile_checks_geospatial_when_one_image_is_georeferenced():
    result = validate_change_detection_inputs(
        _meta("T1", _geotiff(count=1), "a.tif"), _meta("T2", _plain_tiff(count=1), "b.tif"), CHAT_GATE_REQUIREMENTS
    )
    assert result.errors[0].code == CRS_MISSING
    assert result.errors[0].t2 == "T2"


# ---- bitemporal_change can't bypass the change-detection validator ------------------------------


def test_bitemporal_change_optical_vs_sar_is_rejected():
    result = validate_images(workflow="bitemporal_change", images=[
        _img(S2_NAME, _geotiff(descriptions=["B02", "B03", "B04", "B08"]), role="t1", imagery_id="t1"),
        _img(S1_NAME, _geotiff(descriptions=["VV", "VH", "VV", "VH"]), role="t2", imagery_id="t2"),
    ])
    assert result.valid is False
    assert result.errors[0].code in (IMAGE_TYPE_MISMATCH, MODALITY_MISMATCH)


def test_bitemporal_change_compatible_pair_is_valid():
    result = validate_images(workflow="bitemporal_change", images=[
        _img(S1_NAME, _geotiff(descriptions=["VV"]), role="t1", imagery_id="t1"),
        _img(S1_NAME, _geotiff(descriptions=["VV"]), role="t2", imagery_id="t2"),
    ])
    assert result.valid, result.errors


# ---- error-code audit ---------------------------------------------------------------------------------


def test_image_type_mismatch_is_only_used_for_cross_image_modality_conflicts():
    import pathlib
    import app.validation as package
    users = [
        path.name for path in pathlib.Path(package.__file__).parent.glob("*.py")
        if "IMAGE_TYPE_MISMATCH" in path.read_text(encoding="utf-8") and path.name != "errors.py"
    ]
    assert users == ["change_detection_validator.py"]


# ---- API: chat profile by default, strict on request -----------------------------------------------


def _upload(client, filename, content, content_type, **form):
    response = client.post("/api/v1/imagery/upload", files={"file": (filename, content, content_type)}, data=form)
    assert response.status_code == 201, response.json()
    return response.json()["data"]["id"]


def test_endpoint_defaults_to_the_chat_profile_for_a_jpeg_pair(client, fake_supabase):
    t1 = _upload(client, "before.jpg", _image_bytes("JPEG"), "image/jpeg")
    t2 = _upload(client, "after.jpg", _image_bytes("JPEG"), "image/jpeg")
    body = client.post("/api/v1/validation/change-detection", json={"t1_imagery_id": t1, "t2_imagery_id": t2}).json()["data"]
    assert body["valid"] is True, body["errors"]
    assert body["check_details"]["geospatial_t1"]["status"] == "skipped"
    assert all(isinstance(value, bool) for value in body["checks"].values())

    strict = client.post("/api/v1/validation/change-detection", json={
        "t1_imagery_id": t1, "t2_imagery_id": t2, "profile": "strict",
    }).json()["data"]
    assert strict["valid"] is False
    assert strict["error_code"] == UNKNOWN_SENSOR


def test_endpoint_reports_sensor_in_the_image_summary(client, fake_supabase):
    t1 = _upload(client, "a.tif", _geotiff(descriptions=["VV"]), "image/tiff", sensor="Sentinel-1A")
    t2 = _upload(client, "b.tif", _geotiff(descriptions=["VV"]), "image/tiff", sensor="Sentinel-1B")
    body = client.post("/api/v1/validation/change-detection", json={
        "t1_imagery_id": t1, "t2_imagery_id": t2, "profile": "strict",
    }).json()["data"]
    assert body["valid"] is True, body["errors"]
    assert body["t1"]["sensor"] == "sentinel-1" and body["t1"]["sensor_source"] == "db_sensor"
    assert body["ordered_bands"] == {"t1": ["vv"], "t2": ["vv"]}


def test_endpoint_expected_polarisations_override(client, fake_supabase):
    t1 = _upload(client, "a.tif", _geotiff(descriptions=["VV"]), "image/tiff")
    t2 = _upload(client, "b.tif", _geotiff(descriptions=["VV"]), "image/tiff")
    body = client.post("/api/v1/validation/change-detection", json={
        "t1_imagery_id": t1, "t2_imagery_id": t2, "expected_sar_polarizations": ["vv", "vh"],
    }).json()["data"]
    assert body["error_code"] == POLARIZATION_MISMATCH


def test_analysis_chat_gate_rejects_a_dtype_mismatch_and_queues_nothing(client, fake_supabase):
    t1 = _upload(client, "a.tif", _geotiff(count=1, dtype="uint16"), "image/tiff")
    t2 = _upload(client, "b.tif", _geotiff(count=1, dtype="float32"), "image/tiff")
    before = len(fake_supabase.store.get("analysis_jobs", []))
    response = client.post("/api/v1/analysis", json={
        "imagery_id": t1, "comparison_imagery_id": t2, "analysis_type": "general_analysis", "query": "What changed?",
    })
    assert response.status_code == 422
    assert response.json()["error"]["code"] == DTYPE_MISMATCH
    assert len(fake_supabase.store.get("analysis_jobs", [])) == before
