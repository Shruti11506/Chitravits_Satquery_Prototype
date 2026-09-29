"""Input validation for Sentinel-1 / Sentinel-2 / Cartosat / RISAT:
file validation, sensor identification, Sentinel-2 band validation, the
Cartosat band config, evidence-based modality, and the change-detection
validator (incl. same-image detection). No network, no model."""
import io
import pathlib

import numpy as np
import pytest
from PIL import Image
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from app.validation import band_validator, file_validator, modality_validator, raster_validator
from app.validation.change_detection_validator import validate_change_detection_inputs
from app.validation.errors import (
    ALL_CODES,
    BAND_MISMATCH,
    BAND_MISSING,
    CRS_MISSING,
    DTYPE_MISMATCH,
    EMPTY_FILE,
    FILE_CORRUPTED,
    FILE_TOO_LARGE,
    FILE_TYPE_MISMATCH,
    GEOREFERENCE_MISSING,
    INVALID_DIMENSIONS,
    MODALITY_MISMATCH,
    NOT_DISTINCT_OBSERVATIONS,
    SAME_ACQUISITION_TIME,
    UNKNOWN_SENSOR,
    UNSUPPORTED_DTYPE,
    UNSUPPORTED_FILE_TYPE,
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
from tests.images import unique_color, unique_fill

S2_NAME = "S2A_MSIL2A_20240101T050211_N0510_R020_T43PGQ_20240101T081000.tif"
S1_NAME = "S1A_IW_GRDH_1SDV_20240101T004016_20240101T004041_051900_064526_1A2B.tif"
LANDSAT_NAME = "LC08_L2SP_144051_20240101_20240110_02_T1.tif"
S2_BANDS = ["B02", "B03", "B04", "B08"]


# ---- fixtures ---------------------------------------------------------------------


def _geotiff(*, descriptions=(), count=None, dtype="uint16", crs="EPSG:32643", width=64, height=48,
             tags=None, fill=None, compress=None):
    count = count if count is not None else (len(descriptions) or 1)
    value = unique_fill() if fill is None else fill
    profile = dict(driver="GTiff", width=width, height=height, count=count, dtype=dtype, crs=crs,
                   transform=from_origin(776000, 1440000, 10, 10))
    if compress:
        profile["compress"] = compress
    with MemoryFile() as mem:
        with mem.open(**profile) as dst:
            dst.write(np.full((count, height, width), value, dtype=dtype))
            for i, name in enumerate(descriptions, start=1):
                dst.set_band_description(i, name)
            if tags:
                dst.update_tags(**tags)
        return mem.read()


def _image_bytes(fmt, width=64, height=48, color=None):
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=color or unique_color()).save(buf, format=fmt)
    return buf.getvalue()


def _meta(label, content, filename, *, sensor=None, hint=None, imagery_id=None, with_bytes=True, **extra):
    image = ImageInput(filename=filename, content_type=None, content=content, size_bytes=len(content))
    return ChangeDetectionImageMetadata(
        label=label, facts=raster_validator.resolve_facts(image), extension=raster_validator.extension_of(filename),
        filename=filename, sensor=sensor, modality_hint=hint, imagery_id=imagery_id or label,
        content=content if with_bytes else None, **extra,
    )


def _img(filename, content, *, role="single", sensor=None, hint=None, imagery_id=None) -> ImageInput:
    return ImageInput(
        filename=filename, content_type=None, content=content, size_bytes=len(content),
        role=role, sensor=sensor, modality_hint=hint, imagery_id=imagery_id or filename,
    )


def _facts(descriptions, **kw):
    return RasterFacts(format="GeoTIFF", width=10, height=10, band_count=len(descriptions), band_descriptions=descriptions, **kw)


def _cd(t1, t2, reqs=CHAT_GATE_REQUIREMENTS):
    return validate_change_detection_inputs(t1, t2, reqs)


# ==== 1. File validation (cases 1-5, plus MIME / dimensions / dtype / digests) =====


def test_1_empty_file():
    assert [i.code for i in file_validator.validate_file("scene.tif", b"").issues] == [EMPTY_FILE]


def test_2_png_whose_bytes_are_jpeg():
    result = file_validator.validate_file("photo.png", _image_bytes("JPEG"))
    assert [i.code for i in result.issues] == [FILE_TYPE_MISMATCH]
    assert "JPEG" in result.issues[0].message


def test_3_truncated_tiff_is_corrupt():
    result = file_validator.validate_file("broken.tif", _geotiff()[:200])
    assert [i.code for i in result.issues] == [FILE_CORRUPTED]


@pytest.mark.parametrize("filename", ["setup.exe", "report.pdf"])
def test_4_unsupported_extension(filename):
    assert [i.code for i in file_validator.validate_file(filename, b"MZ whatever").issues] == [UNSUPPORTED_FILE_TYPE]


def test_5_file_over_the_size_limit(monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "MAX_UPLOAD_SIZE_MB", 0)
    assert [i.code for i in file_validator.validate_file("scene.tif", _geotiff()).issues] == [FILE_TOO_LARGE]


def test_declared_mime_must_match_the_content():
    result = file_validator.validate_file("photo.jpg", _image_bytes("JPEG"), "image/png")
    assert [i.code for i in result.issues] == [FILE_TYPE_MISMATCH]
    # A generic declared type says nothing and is ignored.
    assert file_validator.validate_file("photo.jpg", _image_bytes("JPEG"), "application/octet-stream").valid


def test_pixel_ceiling_is_invalid_dimensions(monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "VALIDATION_MAX_PIXELS", 100)
    assert [i.code for i in file_validator.validate_file("scene.tif", _geotiff()).issues] == [INVALID_DIMENSIONS]


def test_unsupported_dtype():
    result = file_validator.validate_file("scene.tif", _geotiff(dtype="float64"))
    assert [i.code for i in result.issues] == [UNSUPPORTED_DTYPE]
    assert "float64" in result.issues[0].message


@pytest.mark.parametrize("filename,fmt", [("photo.webp", "WEBP"), ("photo.png", "PNG"), ("photo.jpg", "JPEG")])
def test_supported_images_pass(filename, fmt):
    assert file_validator.validate_file(filename, _image_bytes(fmt)).valid


def test_digests_are_computed_and_pixel_digest_ignores_file_metadata():
    plain = _geotiff(fill=7)
    retagged = _geotiff(fill=7, tags={"NOTE": "re-saved"}, compress="deflate")
    a, b = file_validator.validate_file("a.tif", plain), file_validator.validate_file("b.tif", retagged)
    assert a.sha256 and b.sha256 and a.sha256 != b.sha256  # different bytes...
    assert a.pixel_sha256 == b.pixel_sha256  # ...same pixels
    assert set(a.digests()) == {"sha256", "pixel_sha256"}


def test_upload_rejects_a_mismatched_file_and_stores_digests(client, fake_supabase):
    bad = client.post("/api/v1/imagery/upload", files={"file": ("photo.png", _image_bytes("JPEG"), "image/png")})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == FILE_TYPE_MISMATCH
    assert fake_supabase.storage.objects == {}

    content = _geotiff()
    ok = client.post("/api/v1/imagery/upload", files={"file": ("scene.tif", content, "image/tiff")})
    assert ok.status_code == 201
    metadata = fake_supabase.store["imagery"][0]["metadata"]
    assert metadata["sha256"] == file_validator.sha256_of(content)
    assert metadata["pixel_sha256"]


# ==== 2. Sensor identification ===============================================================


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
    assert (found.status, found.family, found.source) == ("supported", family, source)


def test_explicit_sensor_field_outranks_the_filename():
    found = identify_sensor(sensor="RISAT-1A", filename=S1_NAME)
    assert found.family == SensorFamily.RISAT and found.source == "db_sensor"


@pytest.mark.parametrize("kwargs", [{"filename": LANDSAT_NAME}, {"sensor": "Landsat 8"}, {"sensor": "WorldView-3"}])
def test_24_out_of_scope_sensors_are_unsupported(kwargs):
    assert identify_sensor(**kwargs).status == "unsupported"


def test_no_evidence_is_unknown():
    assert identify_sensor(filename="s1.tif", facts=_facts(["B4"])).status == "unknown"


# ==== 3. Bands: Sentinel-2 validator + Cartosat config (cases 6-12) ==============================


def test_6_s2_band_b04_is_red():
    bands = band_validator.detect_named_bands(_facts(["B02", "B03", "B04", "B08", "B8A", "B11"]), identify_sensor(sensor="Sentinel-2"))
    assert bands == {"blue": 1, "green": 2, "red": 3, "nir": 4, "nir_narrow": 5, "swir1": 6}
    assert band_validator.detect_named_bands(_facts(["B4"]), identify_sensor(sensor="Sentinel-2")) == {"red": 1}


@pytest.mark.parametrize("count,expected_first,expected_last", [
    (13, "coastal", "swir2"), (12, "coastal", "swir2"), (4, "blue", "nir"),
])
def test_7_unnamed_s2_bands_map_positionally(count, expected_first, expected_last):
    facts = raster_validator.extract_from_bytes(_geotiff(count=count), "scene.tif")
    bands = band_validator.detect_named_bands(facts, identify_sensor(sensor="Sentinel-2A"))
    order = band_validator.ordered_bands(bands)
    assert len(order) == count and order[0] == expected_first and order[-1] == expected_last
    if count == 12:
        assert "cirrus" not in bands  # L2A has no B10


def test_positional_mapping_needs_non_filename_sensor_evidence_and_an_exact_count():
    thirteen = raster_validator.extract_from_bytes(_geotiff(count=13), S2_NAME)
    assert band_validator.detect_named_bands(thirteen, identify_sensor(filename=S2_NAME)) == {}
    five = raster_validator.extract_from_bytes(_geotiff(count=5), "scene.tif")
    assert band_validator.detect_named_bands(five, identify_sensor(sensor="Sentinel-2")) == {}


def test_8_band_ids_are_not_interpreted_for_an_unknown_sensor():
    facts = _facts(["B4", "B8"])
    assert band_validator.detect_named_bands(facts, identify_sensor(filename="scene.tif")) == {}
    assert band_validator.unrecognised_band_names(facts, None) == ["B4", "B8"]


def test_9_s1_and_risat_get_no_band_validation_and_are_sar():
    for sensor in ("Sentinel-1A", "RISAT-1A"):
        facts = raster_validator.extract_from_bytes(_geotiff(count=2), "scene.tif")  # unnamed bands
        sid = identify_sensor(sensor=sensor)
        assert modality_validator.infer_modality(facts, extension=".tif", sensor_id=sid, hint=None).modality == "sar"
    # No SAR workflow validates bands any more.
    from app.validation.workflow_validator import WORKFLOW_REGISTRY
    assert not any(key.startswith("sar_") for key in WORKFLOW_REGISTRY)


def test_10_cartosat_mx_bands_from_config_and_ndvi_allowed():
    image = _img("scene.tif", _geotiff(count=4, descriptions=["B1", "B2", "B3", "B4"]), sensor="Cartosat-3 MX")
    facts = raster_validator.extract_from_bytes(image.content, image.filename)
    assert band_validator.detect_named_bands(facts, identify_sensor(sensor="Cartosat-3 MX")) == {
        "blue": 1, "green": 2, "red": 3, "nir": 4,
    }
    assert validate_images(workflow="ndvi", images=[image]).valid


def test_cartosat_product_inferred_from_band_count():
    from app.validation import cartosat_bands
    sid = identify_sensor(sensor="Cartosat-3")  # no product stated
    facts = raster_validator.extract_from_bytes(_geotiff(count=4), "scene.tif")
    assert cartosat_bands.product_of(sid, facts) == ("MX", "band_count")


def test_11_cartosat_pan_fails_ndvi():
    image = _img("scene.tif", _geotiff(count=1), sensor="Cartosat-3 PAN")
    result = validate_images(workflow="ndvi", images=[image])
    assert result.valid is False
    assert BAND_MISSING in {e.code for e in result.errors}


def test_12_cartosat_unrecognised_layout_gets_no_interpretation():
    image = _img("scene.tif", _geotiff(count=3), sensor="Cartosat-3")
    facts = raster_validator.extract_from_bytes(image.content, image.filename)
    assert band_validator.detect_named_bands(facts, identify_sensor(sensor="Cartosat-3")) == {}
    messages = [e.message for e in validate_images(workflow="ndvi", images=[image]).errors if e.code == BAND_MISSING]
    assert messages and all("Cartosat product/band layout not recognised" in m for m in messages)


def test_ndvi_accepts_b8a_as_nir_and_lists_what_is_missing():
    assert validate_images(workflow="ndvi", images=[_img("scene.tif", _geotiff(descriptions=["B04", "B8A"]), sensor="Sentinel-2")]).valid
    result = validate_images(workflow="ndvi", images=[_img("scene.tif", _geotiff(descriptions=["B02", "B03", "B04"]), sensor="Sentinel-2")])
    assert [e.code for e in result.errors] == [BAND_MISSING]
    assert "NIR band is required" in result.errors[0].message


def test_unknown_sensor_fails_ndvi_but_passes_vqa():
    image = lambda: _img("scene.tif", _geotiff(descriptions=["red", "nir"]))
    assert UNKNOWN_SENSOR in {e.code for e in validate_images(workflow="ndvi", images=[image()]).errors}
    assert validate_images(workflow="visual_vqa", images=[image()]).valid


# ==== 4. Modality (cases 13-15) ===============================================================


def _decide(facts, *, extension=".tif", filename=None, sensor=None, hint=None):
    sid = identify_sensor(sensor=sensor, filename=filename, facts=facts)
    return modality_validator.infer_modality(facts, extension=extension, sensor_id=sid, hint=hint)


def test_13_unknown_four_band_raster_is_unknown():
    assert _decide(raster_validator.extract_from_bytes(_geotiff(count=4), "scene.tif")).modality == "unknown"


def test_14_s1_with_optical_hint_is_modality_mismatch():
    facts = raster_validator.extract_from_bytes(_geotiff(descriptions=["VV"]), "scene.tif")
    decision = _decide(facts, sensor="Sentinel-1A", hint="optical")
    assert decision.hint_conflict
    assert modality_validator.hint_conflict_issue(decision, input_label="x").code == MODALITY_MISMATCH
    result = validate_images(workflow="visual_vqa", images=[_img("scene.tif", _geotiff(descriptions=["VV"]), sensor="Sentinel-1A", hint="optical")])
    assert [e.code for e in result.errors] == [MODALITY_MISMATCH]


def test_hint_without_evidence_is_accepted():
    decision = _decide(raster_validator.extract_from_bytes(_geotiff(count=2), "scene.tif"), hint="sar")
    assert (decision.modality, decision.source) == ("sar", "hint")


def test_15_rgb_jpeg_fails_ndvi():
    result = validate_images(workflow="ndvi", images=[_img("photo.jpg", _image_bytes("JPEG"))])
    assert result.valid is False
    assert {BAND_MISSING, MODALITY_MISMATCH} <= {e.code for e in result.errors}


def test_cartosat_modality_by_product():
    assert _decide(raster_validator.extract_from_bytes(_geotiff(count=4), "s.tif"), sensor="Cartosat-3 MX").modality == "multispectral"
    assert _decide(raster_validator.extract_from_bytes(_geotiff(count=1), "s.tif"), sensor="Cartosat-3 PAN").modality == "optical"


# ==== 5. Change detection (cases 16-23) ========================================================


def test_16_same_imagery_id_is_identical():
    content = _geotiff()
    result = _cd(_meta("T1", content, "a.tif", imagery_id="same"), _meta("T2", content, "a.tif", imagery_id="same"))
    assert result.errors[0].code == NOT_DISTINCT_OBSERVATIONS
    assert "same id" in result.errors[0].message
    assert result.checks["distinct_images"] is False


def test_same_storage_object_is_identical():
    result = _cd(_meta("T1", _geotiff(), "a.tif", imagery_id="a", storage_path="imagery/x/a.tif"),
                 _meta("T2", _geotiff(), "a.tif", imagery_id="b", storage_path="imagery/x/a.tif"))
    assert "same file" in result.errors[0].message


def test_17_same_bytes_under_different_ids_is_identical():
    content = _geotiff()
    result = _cd(_meta("T1", content, "a.tif", imagery_id="a"), _meta("T2", content, "b.tif", imagery_id="b"))
    assert result.errors[0].code == NOT_DISTINCT_OBSERVATIONS
    assert "identical content" in result.errors[0].message


def test_18_same_pixels_different_tiff_metadata_is_identical():
    result = _cd(_meta("T1", _geotiff(fill=9), "a.tif", imagery_id="a"),
                 _meta("T2", _geotiff(fill=9, tags={"NOTE": "re-exported"}, compress="deflate"), "b.tif", imagery_id="b"))
    assert result.errors[0].code == NOT_DISTINCT_OBSERVATIONS
    assert "identical pixels" in result.errors[0].message


def test_19_two_different_s2_images_are_distinct():
    result = _cd(_meta("T1", _geotiff(descriptions=S2_BANDS), S2_NAME, imagery_id="a"),
                 _meta("T2", _geotiff(descriptions=S2_BANDS), S2_NAME, imagery_id="b"), STRICT_REQUIREMENTS)
    assert result.valid, result.errors
    assert result.check_details["distinct_images"].status == "pass"
    assert result.ordered_bands == {"t1": ["blue", "green", "red", "nir"], "t2": ["blue", "green", "red", "nir"]}


def test_stored_digests_are_used_without_reading_the_file():
    def boom():
        raise AssertionError("the original must not be read when digests are stored")
    t1 = _meta("T1", _geotiff(), "a.tif", imagery_id="a", with_bytes=False, sha256="x" * 64, pixel_sha256="p", content_loader=boom)
    t2 = _meta("T2", _geotiff(), "b.tif", imagery_id="b", with_bytes=False, sha256="x" * 64, pixel_sha256="q", content_loader=boom)
    assert "identical content" in _cd(t1, t2).errors[0].message


def test_missing_digests_are_computed_once_from_the_stored_file():
    content = _geotiff(fill=3)
    calls = []
    loader = lambda: calls.append(1) or content
    t1 = _meta("T1", content, "a.tif", imagery_id="a", with_bytes=False, content_loader=loader)
    t2 = _meta("T2", _geotiff(fill=3, compress="deflate"), "b.tif", imagery_id="b")
    assert "identical pixels" in _cd(t1, t2).errors[0].message
    assert calls == [1]


def test_20_bitemporal_change_optical_vs_sar_is_modality_mismatch():
    result = validate_images(workflow="bitemporal_change", images=[
        _img(S2_NAME, _geotiff(descriptions=S2_BANDS), role="t1", imagery_id="t1"),
        _img("s.tif", _geotiff(count=4), role="t2", imagery_id="t2", sensor="Sentinel-1A"),
    ])
    assert result.valid is False
    assert result.errors[0].code == MODALITY_MISMATCH


def test_21_s1_and_risat_same_band_count_pass_without_band_validation():
    result = _cd(_meta("T1", _geotiff(descriptions=["VV", "VH"]), "a.tif", sensor="Sentinel-1A"),
                 _meta("T2", _geotiff(descriptions=["HH", "HV"]), "b.tif", sensor="RISAT-1A"), STRICT_REQUIREMENTS)
    assert result.valid, result.errors
    assert result.check_details["band_identity"].status == "skipped"
    assert result.ordered_bands == {"t1": ["vv", "vh"], "t2": ["hh", "hv"]}  # file order, as-is


def test_sar_pair_with_different_band_counts_is_rejected():
    result = _cd(_meta("T1", _geotiff(count=2), "a.tif", sensor="Sentinel-1A"),
                 _meta("T2", _geotiff(count=1), "b.tif", sensor="RISAT-1A"))
    assert result.errors[0].code == BAND_MISMATCH


def test_22_png_t1_fails_geospatial_on_t1():
    reqs = STRICT_REQUIREMENTS.with_overrides(require_matching_format=False, require_known_sensor=False)
    result = _cd(_meta("T1", _image_bytes("PNG"), "a.png"), _meta("T2", _geotiff(count=3), "b.tif"), reqs)
    assert result.errors[0].code == GEOREFERENCE_MISSING
    assert result.errors[0].t1 == "T1" and result.errors[0].t2 is None


def test_png_t2_fails_geospatial_on_t2():
    reqs = STRICT_REQUIREMENTS.with_overrides(require_matching_format=False, require_known_sensor=False)
    result = _cd(_meta("T1", _geotiff(count=3), "a.tif"), _meta("T2", _image_bytes("PNG"), "b.png"), reqs)
    assert result.errors[0].code == GEOREFERENCE_MISSING
    assert result.errors[0].t2 == "T2" and result.errors[0].t1 is None


def test_23_defaults_skip_the_deferred_gates():
    result = _cd(_meta("T1", _geotiff(count=1, width=64, height=48), "a.tif"),
                 _meta("T2", _geotiff(count=1, width=100, height=30), "b.tif"), ChangeDetectionRequirements())
    assert result.valid, result.errors
    for name in ("aspect_ratio", "dimensions"):
        assert result.check_details[name].status == "skipped" and name not in result.checks


def test_chat_profile_keeps_the_dimension_gate_on():
    result = _cd(_meta("T1", _geotiff(count=1, width=64, height=48), "a.tif"),
                 _meta("T2", _geotiff(count=1, width=128, height=96), "b.tif"))
    assert result.errors[0].code == "IMAGE_DIMENSION_MISMATCH"


def test_24_landsat_pair_is_unsupported():
    result = _cd(_meta("T1", _geotiff(), LANDSAT_NAME), _meta("T2", _geotiff(), LANDSAT_NAME))
    assert result.errors[0].code == UNSUPPORTED_SENSOR


def test_unknown_sensor_rejected_only_under_strict():
    t1, t2 = _meta("T1", _geotiff(), "a.tif"), _meta("T2", _geotiff(), "b.tif")
    assert _cd(t1, t2).valid
    assert _cd(_meta("T1", _geotiff(), "a.tif"), _meta("T2", _geotiff(), "b.tif"), STRICT_REQUIREMENTS).errors[0].code == UNKNOWN_SENSOR


def test_file_checks_run_first_and_name_the_image():
    result = _cd(_meta("T1", _geotiff(), "a.tif"), _meta("T2", _geotiff(dtype="float64"), "b.tif"))
    assert result.errors[0].code == UNSUPPORTED_DTYPE
    assert result.errors[0].t2 == "T2" and result.checks["file_t1"] is True and result.checks["file_t2"] is False


def test_dtype_mismatch_between_t1_and_t2():
    result = _cd(_meta("T1", _geotiff(dtype="uint16"), "a.tif"), _meta("T2", _geotiff(dtype="float32"), "b.tif"))
    assert result.errors[0].code == DTYPE_MISMATCH


def test_duplicate_s2_band_is_rejected():
    result = _cd(_meta("T1", _geotiff(descriptions=["B02", "B04", "B04", "B08"]), "a.tif", sensor="Sentinel-2"),
                 _meta("T2", _geotiff(descriptions=S2_BANDS), "b.tif", sensor="Sentinel-2"))
    assert result.errors[0].code == BAND_MISMATCH and "more than once" in result.errors[0].message


def test_same_sensor_and_acquisition_time_is_a_warning_not_an_error():
    result = _cd(_meta("T1", _geotiff(descriptions=S2_BANDS), "a.tif", sensor="Sentinel-2", acquisition_date="2024-01-01T05:02:11Z"),
                 _meta("T2", _geotiff(descriptions=S2_BANDS), "b.tif", sensor="Sentinel-2", acquisition_date="2024-01-01T05:02:11Z"))
    assert result.valid, result.errors
    assert [w.code for w in result.warnings] == [SAME_ACQUISITION_TIME]


def test_chat_profile_checks_geospatial_when_one_image_is_georeferenced():
    plain = _geotiff(crs=None)
    result = _cd(_meta("T1", _geotiff(), "a.tif"), _meta("T2", plain, "b.tif"))
    assert result.errors[0].code == CRS_MISSING and result.errors[0].t2 == "T2"


def test_jpeg_pair_passes_the_chat_profile():
    result = _cd(_meta("T1", _image_bytes("JPEG"), "before.jpg"), _meta("T2", _image_bytes("JPEG"), "after.jpg"))
    assert result.valid, result.errors
    assert result.check_details["geospatial_t1"].status == "skipped" and "geospatial_t1" not in result.checks


# ==== API ======================================================================================


def _upload(client, filename, content, content_type, **form):
    response = client.post("/api/v1/imagery/upload", files={"file": (filename, content, content_type)}, data=form)
    assert response.status_code == 201, response.json()
    return response.json()["data"]["id"]


def test_17_api_two_uploads_of_the_same_bytes_are_rejected(client, fake_supabase):
    content = _geotiff()
    t1, t2 = _upload(client, "a.tif", content, "image/tiff"), _upload(client, "b.tif", content, "image/tiff")
    body = client.post("/api/v1/validation/change-detection", json={"t1_imagery_id": t1, "t2_imagery_id": t2}).json()["data"]
    assert body["error_code"] == NOT_DISTINCT_OBSERVATIONS
    before = len(fake_supabase.store.get("analysis_jobs", []))
    response = client.post("/api/v1/analysis", json={
        "imagery_id": t1, "comparison_imagery_id": t2, "analysis_type": "general_analysis", "query": "What changed?",
    })
    assert response.status_code == 422 and response.json()["error"]["code"] == NOT_DISTINCT_OBSERVATIONS
    assert len(fake_supabase.store.get("analysis_jobs", [])) == before


def test_api_endpoint_reports_check_details_and_sensor(client, fake_supabase):
    t1 = _upload(client, "a.tif", _geotiff(descriptions=["VV"]), "image/tiff", sensor="Sentinel-1A")
    t2 = _upload(client, "b.tif", _geotiff(descriptions=["VV"]), "image/tiff", sensor="Sentinel-1B")
    body = client.post("/api/v1/validation/change-detection", json={
        "t1_imagery_id": t1, "t2_imagery_id": t2, "profile": "strict",
        # removed options: accepted and ignored
        "expected_sar_polarizations": ["vv", "vh"], "sar_polarization_policy": "single_required",
    }).json()["data"]
    assert body["valid"] is True, body["errors"]
    assert body["t1"]["sensor"] == "sentinel-1"
    assert all(isinstance(value, bool) for value in body["checks"].values())
    assert body["check_details"]["distinct_images"]["status"] == "pass"


def test_analysis_gate_rejects_a_dtype_mismatch(client, fake_supabase):
    t1 = _upload(client, "a.tif", _geotiff(count=1, dtype="uint16"), "image/tiff")
    t2 = _upload(client, "b.tif", _geotiff(count=1, dtype="float32"), "image/tiff")
    response = client.post("/api/v1/analysis", json={
        "imagery_id": t1, "comparison_imagery_id": t2, "analysis_type": "general_analysis", "query": "What changed?",
    })
    assert response.status_code == 422 and response.json()["error"]["code"] == DTYPE_MISMATCH


# ==== 26. Code audit ==============================================================================

_VALIDATION = pathlib.Path(raster_validator.__file__).parent


def test_26_no_aoi_validation_left():
    assert not (_VALIDATION / "aoi_validator.py").exists()
    assert not any("AOI" in code for code in ALL_CODES)
    for path in _VALIDATION.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "shapely" not in text and "intersection_issues" not in text, path.name


def test_26_image_type_mismatch_is_no_longer_emitted():
    import re
    # Imported or passed as a code anywhere (docstrings may still mention it).
    use = re.compile(r"^\s*IMAGE_TYPE_MISMATCH,\s*$|import .*\bIMAGE_TYPE_MISMATCH\b|\(\s*IMAGE_TYPE_MISMATCH\b", re.M)
    users = [p.name for p in _VALIDATION.glob("*.py") if p.name != "errors.py" and use.search(p.read_text(encoding="utf-8"))]
    assert users == []  # defined (deprecated) in errors.py, emitted nowhere
